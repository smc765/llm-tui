from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Footer, Input, Markdown, OptionList, Label
from textual.screen import Screen
from textual.worker import Worker, WorkerState
from textual.binding import Binding
from textual.widgets.option_list import Option
import llm
from dotenv import load_dotenv
import os
import tempfile
import argparse
import logging
import time
import tkinter as tk
from tkinter import filedialog
from screenshot import get_screenshot

logger = logging.getLogger(__name__)
parser = argparse.ArgumentParser()
parser.add_argument("-d", "--debug", action="store_true")
args = parser.parse_args()
if args.debug:
    logging.basicConfig(
        level=logging.DEBUG,
        handlers=[logging.FileHandler("debug.log"),]
        )

load_dotenv(dotenv_path=os.path.abspath(os.path.join(os.path.dirname(__file__), ".env")))

# defaults
SYSTEM = None
MODEL = "gpt-4o-mini"

class Prompt(Markdown):
    """Markdown for the user prompt."""

class Response(Markdown):
    """Markdown for the reply from the LLM."""
    BORDER_TITLE = None

class InputScreen(Screen):
    BINDINGS = [("escape", "app.pop_screen", "back")]

    CSS = """
    InputScreen {
        align: center middle;
    }

    Input {
        width: 80%;
    }
    """

    def __init__(self, text: str, placeholder: str = ""):
        self.text = text
        self.placeholder = placeholder
        super().__init__()

    def compose(self) -> ComposeResult:
        yield Label(self.text)
        yield Input(placeholder=self.placeholder, type="text")

    @on(Input.Submitted)
    async def on_input(self, event: Input.Submitted) -> None:
        if event.value == "":
            self.dismiss(None)
        else:
            self.dismiss(event.value)
        event.stop()

class SetModel(Screen):
    BINDINGS = [("escape", "app.pop_screen", "back")]
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
    async def on_input(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.prompt)

class LlmApp(App):
    AUTO_FOCUS = "Input"
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        Binding("ctrl+c", "quit"),
        Binding("f1", "set_system", "Set System Prompt"),
        Binding("f2", "set_model", "Set Model"),
        Binding("f3", "clear_context", "Clear Context"),
        Binding("f4", "attach_file", "Attach File(s)"),
        Binding("f5", "screenshot", "Attach Screenshot"),
        Binding("f6", "clear_attachments", "Clear Attachments"),
        Binding("f7", "regenerate", "Regenerate"),
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
        self.model_name = MODEL
        self.model = llm.get_model(self.model_name)
        self.conversation = self.model.conversation()
        self.query_one("#chat-view").anchor()
        self.system = SYSTEM
        self.attachments = []
        self.prev_attachments = []
        self.prev_prompt = None
 
    @on(Input.Submitted)
    async def on_input(self, event: Input.Submitted) -> None:
        """When the user hits return."""
        chat_view = self.query_one("#chat-view")
        event.input.clear()
        if event.value != "":
            await chat_view.mount(Prompt(event.value))
        elif len(self.attachments) == 0:
            return # don't send empty prompt w/o attachments
        response = Response()
        response.border_title = self.model_name
        await chat_view.mount(response)
        self.send_prompt(event.value, self.attachments, response)
        
    @work(thread=True, exit_on_error=False)
    def send_prompt(self, prompt: str, attachments: list[llm.Attachment], response: Response) -> None:
        response.border_subtitle = f"Attachments: {len(attachments)}"

        llm_response = self.conversation.prompt(prompt, system=self.system, attachments=attachments)
        buf = []
        last_update = 0
        for chunk in llm_response:
            buf.append(chunk)
            t = time.time()
            if t - last_update > 0.1:
                self.call_from_thread(response.append, "".join(buf))
                buf.clear()
                last_update = t

        if buf:
            self.call_from_thread(response.append, "".join(buf))

        response.border_subtitle = f"Attachments: {len(attachments)} Input tokens: {llm_response.input_tokens} Output tokens: {llm_response.output_tokens}"
        self.prev_prompt = prompt
        self.prev_attachments = attachments.copy()
        attachments.clear()
        self.query_one(Label).content = f"Attachments: {len(self.attachments)}"
        self.refresh_bindings()

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker.state == WorkerState.ERROR:
            chat_view = self.query_one("#chat-view")
            response = chat_view.children[-1]
            response.update(str(event.worker.error))

    def action_set_system(self) -> None:
        def set_system(prompt: str | None) -> None:
            """Called when Screen is dismissed."""
            self.system = prompt
            chat_view = self.query_one("#chat-view")
            chat_view.mount(Prompt(f"system prompt set to: {self.system}"))

        self.push_screen(InputScreen(f"Current system prompt: {self.system}"), set_system)

    def action_set_model(self) -> None:
        def set_model(model: str) -> None:
            self.model_name = model
            self.model = llm.get_model(model)
            self.conversation = self.model.conversation()
            chat_view = self.query_one("#chat-view")
            chat_view.mount(Prompt(f"model set to: {model}"))

        self.push_screen(SetModel(self.model_name), set_model)

    def action_clear_context(self) -> None:
        self.conversation = self.model.conversation()
        chat_view = self.query_one("#chat-view")
        chat_view.mount(Prompt("context cleared"))

    def action_attach_file(self) -> None:
        filenames = filedialog.askopenfilenames(filetypes=[("All files", "*.*")])
        chat_view = self.query_one("#chat-view")
        for f in filenames:
            self.attachments.append(llm.Attachment(path=f))
            chat_view.mount(Prompt(f"attached file: {f}"))

        self.query_one(Label).content = f"Attachments: {len(self.attachments)}"

    def action_screenshot(self) -> None:
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".png").name
        try:
            get_screenshot(temp_file)
        except AssertionError:
            return

        self.attachments.append(llm.Attachment(path=temp_file))
        chat_view = self.query_one("#chat-view")
        chat_view.mount(Prompt(f"attached screenshot: {temp_file}"))
        self.query_one(Label).content = f"Attachments: {len(self.attachments)}"

    def action_clear_attachments(self) -> None:
        self.attachments.clear()
        self.query_one(Label).content = f"Attachments: {len(self.attachments)}"
        chat_view = self.query_one("#chat-view")
        chat_view.mount(Prompt(f"attachments cleared"))
        self.refresh_bindings()

    async def action_regenerate(self) -> None:
        """resend previous prompt"""
        assert self.prev_prompt is not None
        chat_view = self.query_one("#chat-view")
        response = Response()
        response.border_title = self.model_name
        await chat_view.mount(response)
        self.send_prompt(self.prev_prompt, self.prev_attachments, response)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool:  
        """Check if an action may run."""
        if action == "regenerate" and self.prev_prompt is None:
            return False
        if action == "clear_attachments" and len(self.attachments) == 0:
            return False
        return True

if __name__ == "__main__":
    app = LlmApp()
    app.run()