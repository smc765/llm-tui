from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Footer, Input, Markdown, OptionList, Label
from textual.screen import Screen
import llm
from dotenv import load_dotenv
import os
from textual.binding import Binding
from textual.widgets.option_list import Option
import tkinter as tk
from tkinter import filedialog
from screenshot import get_screenshot
import tempfile

import logging
logging.basicConfig(
    level=logging.DEBUG,
    handlers=[logging.FileHandler('debug.log'),]
    )
logger = logging.getLogger(__name__)

load_dotenv(dotenv_path=os.path.abspath(os.path.join(os.path.dirname(__file__), '.env')))

# defaults
SYSTEM = None
MODEL = "gpt-4o-mini"

def file_picker():
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    fpath = filedialog.askopenfilenames(filetypes=[('All files', '*.*')])
    root.destroy()
    return fpath

class Prompt(Markdown):
    """Markdown for the user prompt."""


class Response(Markdown):
    """Markdown for the reply from the LLM."""

    BORDER_TITLE = None

class SetSystem(Screen):
    BINDINGS = [("escape", "app.pop_screen", "back")]

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Enter system prompt", type="text")

    @on(Input.Submitted)
    async def on_input(self, event: Input.Submitted) -> None:
        if event.value == "":
            self.dismiss(None)
        else:
            self.dismiss(event.value)
        event.stop()

class SetModel(Screen):
    BINDINGS = [("escape", "app.pop_screen", "back")]

    def compose(self) -> ComposeResult:
        yield OptionList(
            Option('GPT-5.4', id='gpt-5.4'),
            Option('GPT-5.4 mini', id='gpt-5.4-mini'),
            Option('GPT-4o', id='gpt-4o'),
            Option('GPT-4.1', id='gpt-4.1'),
            Option('Claude Opus 4.6', id='claude-opus-4.6'),
            Option('Claude Sonnet 4.6', id='claude-sonnet-4.6'),
            Option('Claude Haiku 4.5', id='claude-haiku-4.5'),
            Option('Deepseek Chat', id='deepseek-chat'),
            Option('Deepseek Coder', id='deepseek-coder'),
            Option('Deepseek Reasoner', id='deepseek-reasoner'),
            Option('Grok 4.1 Reasoning', id='grok-4-1-fast-reasoning-latest'),
        ) 

    @on(OptionList.OptionSelected)
    async def on_input(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option_id)

class LlmApp(App):
    AUTO_FOCUS = "Input"
    # COMMAND_PALETTE_BINDING = "escape"
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
        
    @work(thread=True)
    def send_prompt(self, prompt: str, attachments: list[llm.Attachment], response: Response) -> None:
        """Get the response in a thread."""
        llm_response = self.conversation.prompt(prompt, system=self.system, attachments=attachments)
        response.border_subtitle = f"Attachments: {len(attachments)}"
        response_content = ""
        for n, chunk in enumerate(llm_response, 1):
            response_content += chunk
            step = (n + 4) // 5
            if n % step == 0:
                self.call_from_thread(response.update, response_content)
        
        self.call_from_thread(response.update, response_content)
        response.border_subtitle = f"Attachments: {len(attachments)} Input tokens: {llm_response.input_tokens} Output tokens: {llm_response.output_tokens}"
        self.prev_prompt = prompt
        self.prev_attachments = attachments.copy()
        attachments.clear()
        self.query_one(Label).content = f"Attachments: {len(self.attachments)}"
        self.refresh_bindings()

    def action_set_system(self) -> None:
        def set_system(prompt: str | None) -> None:
            """Called when Screen is dismissed."""
            self.system = prompt
            chat_view = self.query_one("#chat-view")
            chat_view.mount(Prompt(f"system prompt set to: {self.system}"))

        self.push_screen(SetSystem(), set_system)

    def action_set_model(self) -> None:
        def set_model(model: str) -> None:
            self.model_name = model
            self.model = llm.get_model(model)
            self.conversation = self.model.conversation()
            chat_view = self.query_one("#chat-view")
            chat_view.mount(Prompt(f"model set to: {model}"))

        self.push_screen(SetModel(), set_model)

    def action_clear_context(self) -> None:
        self.conversation = self.model.conversation()
        chat_view = self.query_one("#chat-view")
        chat_view.mount(Prompt("context cleared"))

    def action_attach_file(self) -> None:
        files = file_picker()
        chat_view = self.query_one("#chat-view")
        for f in files:
            self.attachments.append(llm.Attachment(path=f))
            chat_view.mount(Prompt(f"attached file: {f}"))

        self.query_one(Label).content = f"Attachments: {len(self.attachments)}"

    def action_screenshot(self) -> None:
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.png').name
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
        '''resend previous prompt'''
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
