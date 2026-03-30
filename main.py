from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Footer, Input, Markdown, OptionList, Label, TextArea
from textual.screen import ModalScreen
from textual.worker import Worker, WorkerState
from textual.binding import Binding
from textual.widgets.option_list import Option
import llm
from dotenv import load_dotenv
import tempfile
import argparse
import logging
import time
import tkinter as tk
from tkinter import filedialog
from screenshot import get_screenshot
import subprocess
import webbrowser

SYSTEM = "use $$...$$ delimiters for equations. use $...$ delimiters for in-line math expressions"
MODEL = "gpt-4o-mini"
RESPONSE_UPDATE_INTERVAL = 0.1

logger = logging.getLogger(__name__)
parser = argparse.ArgumentParser()
parser.add_argument("-d", "--debug", action="store_true")
args = parser.parse_args()
if args.debug:
    logging.basicConfig(
        level=logging.DEBUG,
        handlers=[logging.FileHandler("debug.log"),]
        )

load_dotenv()

class Prompt(Markdown):
    pass

class Response(Markdown):
    def __init__(self, model: str | None = None):
        super().__init__()
        self.border_title = model

class EditScreen(ModalScreen):
    BINDINGS = [
        ("ctrl+c", "app.quit"),
        ("escape", "app.pop_screen", "Back"),
        ("ctrl+s", "save", "Save"),
        ("ctrl+l", "load_file", "Load File"),
        ("ctrl+r", "clear", "Clear"),
        ]
    AUTO_FOCUS = "TextArea"

    def __init__(self, text: str | None):
        self.text = "" if text is None else text
        super().__init__()

    def compose(self) -> ComposeResult:
        yield TextArea(self.text)
        yield Footer()

    def action_save(self) -> None:
        text = self.query_one(TextArea).text
        if text.isspace() or text == "":
            text = None
        self.dismiss(text)

    def action_clear(self) -> None:
        self.query_one(TextArea).clear()

    @on(TextArea.Changed)
    def on_change(self, event: TextArea.Changed) -> None:
        self.refresh_bindings()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool:
        text_area = self.query_one(TextArea)
        if action == "clear" and text_area.text == "":
            return False
        if action == "save" and text_area.text == self.text:
            return False
        return True

    def action_load_file(self) -> None:
        filename = filedialog.askopenfilename()
        if filename == "":
            return

        with open(filename) as f:
            try:
                text = f.read()
            except UnicodeDecodeError:
                self.notify("Could not read file", title="Error")
                return
                
        text_area = self.query_one(TextArea)
        text_area.clear()
        text_area.insert(text)

class SetModel(ModalScreen):
    BINDINGS = [
        ("ctrl+c", "app.quit"),
        ("escape", "app.pop_screen", "back"),
        ]
    AUTO_FOCUS = "OptionList"

    CSS = """
    SetModel {
        align: center middle;
    }

    OptionList {
        width: 70%;
        height: 80%;
    }
    """

    def __init__(self, curr_model: str):
        self.curr_model = curr_model
        super().__init__()

    def compose(self) -> ComposeResult:
        models = [model.model_id for model in llm.get_models()]
        option_list = OptionList(*models)
        option_list.highlighted = models.index(self.curr_model)
        yield option_list

    @on(OptionList.OptionSelected)
    def on_input(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.prompt)

class LlmApp(App):
    AUTO_FOCUS = "Input"
    ENABLE_COMMAND_PALETTE = False
    NOTIFICATION_TIMEOUT = 2.5
    BINDINGS = [
        Binding("ctrl+c", "quit"),
        Binding("f1", "set_system", "Edit System Prompt"),
        Binding("f2", "set_model", "Set Model"),
        Binding("f3", "clear_context", "Clear Context"),
        Binding("f4", "attach_file", "Attach File(s)"),
        Binding("f5", "screenshot", "Screenshot"),
        Binding("f6", "clear_attachments", "Clear Attachments"),
        Binding("f7", "regenerate", "Regenerate"),
        Binding("f8", "open_in_browser", "Open in Browser"),
    ]

    CSS = """
    Prompt {
        background: $primary 10%;
        color: $text;
        margin: 1;        
        margin-right: 8;
        padding: 1 2 0 2;
    }

    Response {
        border: wide $success;
        background: $success 10%;   
        color: $text;             
        margin: 1;      
        margin-left: 8; 
        padding: 1 2 0 2;
    }
    """

    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="chat-view")
        yield Label("Attachments: 0")
        yield Input(placeholder="Enter prompt")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#chat-view").anchor()
        self.model = llm.get_model(MODEL)
        self.conversation = self.model.conversation()
        self.system = SYSTEM
        self.attachments = []
        self.prev_attachments = []
        self.prev_prompt = None
 
    @on(Input.Submitted)
    async def on_input(self, event: Input.Submitted) -> None:
        chat_view = self.query_one("#chat-view")
        event.input.clear()
        if event.value != "":
            await chat_view.mount(Prompt(event.value))
        elif len(self.attachments) == 0:
            return # don't send empty prompt w/o attachments
        response = Response(self.model.model_id)
        await chat_view.mount(response)
        self.prev_prompt = event.value
        self.prev_attachments = self.attachments.copy()
        self.clear_attachments()
        self.send_prompt(event.value, self.prev_attachments, response)
        
    @work(thread=True, exit_on_error=False)
    def send_prompt(self, prompt: str, attachments: list[llm.Attachment], response: Response) -> None:
        response.border_subtitle = f"Attachments: {len(attachments)}"

        llm_response = self.conversation.prompt(prompt, system=self.system, attachments=attachments)
        buf = []
        last_update = 0
        for chunk in llm_response:
            buf.append(chunk)
            t = time.time()
            if t - last_update > RESPONSE_UPDATE_INTERVAL:
                self.call_from_thread(response.append, "".join(buf))
                buf.clear()
                last_update = t

        if buf:
            self.call_from_thread(response.append, "".join(buf))

        response.border_subtitle += f" Input tokens: {llm_response.input_tokens} Output tokens: {llm_response.output_tokens}"

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.state == WorkerState.ERROR:
            response = self.query(Response).last()
            response.update(f"ERROR: {event.worker.error}")

    def action_set_system(self) -> None:
        def set_system(prompt: str | None) -> None:
            self.system = prompt
            self.info_message(f"system prompt set to: {self.system}")

        self.push_screen(EditScreen(self.system), set_system)

    def action_set_model(self) -> None:
        def set_model(model: str) -> None:
            self.model = llm.get_model(model)
            self.conversation = self.model.conversation()
            self.notify(f"model set to: {model}")

        self.push_screen(SetModel(self.model.model_id), set_model)

    def action_clear_context(self) -> None:
        self.conversation = self.model.conversation()
        self.notify("context cleared")

    def action_attach_file(self) -> None:
        filenames = filedialog.askopenfilenames()
        for f in filenames:
            self.attachments.append(llm.Attachment(path=f))
            self.info_message(f"attached file: {f}")

        self.update_attachment_count()

    def action_screenshot(self) -> None:
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        temp_file.close()
        try:
            get_screenshot(temp_file.name)
        except AssertionError:
            return

        self.attachments.append(llm.Attachment(path=temp_file.name))
        self.info_message(f"attached screenshot: {temp_file.name}")
        self.update_attachment_count()

    def info_message(self, message: str) -> None:
        self.query_one("#chat-view").mount(Prompt(message))

    def action_clear_attachments(self) -> None:
        self.clear_attachments()
        self.notify("attachments cleared")

    def clear_attachments(self) -> None:
        self.attachments.clear()
        self.update_attachment_count()
    
    def update_attachment_count(self) -> None:
        self.query_one(Label).content = f"Attachments: {len(self.attachments)}"
        self.refresh_bindings()

    async def action_regenerate(self) -> None:
        chat_view = self.query_one("#chat-view")
        response = Response(self.model.model_id)
        await chat_view.mount(response)
        self.send_prompt(self.prev_prompt, self.prev_attachments, response)

    def action_open_in_browser(self) -> None:
        response = self.query(Response).last()
        with tempfile.NamedTemporaryFile(delete_on_close=False, suffix=".md", mode="w", encoding="utf-8") as temp_md:
            temp_md.write(response.source)
            temp_md.close()
            subprocess.run(["pandoc", temp_md.name, "-s", "--mathjax", "-o", "out.html"])
            webbrowser.open("out.html")

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool:  
        if action == "regenerate" and self.prev_prompt is None:
            return False
        if action == "clear_attachments" and len(self.attachments) == 0:
            return False
        if action == "open_in_browser" and self.prev_prompt is None:
            return False
        return True

if __name__ == "__main__":
    app = LlmApp()
    app.run()