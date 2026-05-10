import subprocess
import webbrowser
import os
import mimetypes
import ast
import tempfile
import argparse
import logging
import time
import tkinter as tk
import re
from tkinter import filedialog
from typing import Any
from dataclasses import dataclass

import llm
from dotenv import load_dotenv
import pyperclip

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll, HorizontalGroup
from textual.screen import ModalScreen
from textual.worker import Worker
from textual.message import Message
from textual.events import Paste
from textual.widgets import (
    Footer,
    Input,
    Markdown,
    OptionList,
    Label,
    TextArea,
    Button,
)

from screenshot import get_screenshot

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-4o-mini"
RESPONSE_UPDATE_INTERVAL = 0.1


class Prompt(Markdown):
    """Markdown for prompt."""


class Response(Markdown):
    """Markdown for llm response."""

    def __init__(self, prompt: str, attachments: list[llm.Attachment], model_id: str, pandoc_path: str | None):
        super().__init__()
        self.prompt = prompt
        self.attachments = attachments
        self.model_id = model_id
        self.worker: Worker | None = None
        self.pandoc_path = pandoc_path

    def compose(self) -> ComposeResult:
        yield HorizontalGroup(
            Button("Regenerate", id="regenerate"),
            Button("Open in Browser", id="open_in_browser"),
            Button("Cancel", id="cancel"),
            Button("Copy to Clipboard", id="copy"),
            # Button("Save As", id="save_as"), # TODO
        )

    def on_mount(self) -> None:
        self.border_title = self.model_id
        self.update_subtitle()
        # if self.pandoc_path is None:
        #     self.query_one("#open_in_brownser").remove()

    @on(Button.Pressed, "#regenerate")
    async def regenerate(self) -> None:
        await self.app.get_response(self.prompt, self.attachments)

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        if self.worker:
            self.worker.cancel()

    @on(Button.Pressed, "#open_in_browser")
    def open_in_browser(self) -> None:
        if self.pandoc_path is None:
            self.app.get_vertical_scroll().mount(Prompt("Install [Pandoc](https://pandoc.org/installing.html) to use this feature or set the PANDOC_PATH environment variable if already installed."))
            return

        # text = re.sub(r"\\\[(.*?)\\\]", r"$$\1$$", self.source, flags=re.DOTALL) # failed attempt to convert delimiters

        with tempfile.NamedTemporaryFile(delete_on_close=False, suffix=".md", mode="w", encoding="utf-8") as temp_md:
            temp_md.write(self.source)
            temp_md.close()
            cmd = [
                self.pandoc_path, temp_md.name,
                "-s", "--mathjax",
                "-o", "out.html",
            ]
            try:
                subprocess.run(cmd, check=True)

            except subprocess.CalledProcessError as e:
                logger.error(e)
                return

#         with open("out.html","w") as f:
#             f.write(f'''
# <!DOCTYPE html>
# <html>
#     <head>
#         <title>{self.model_id}</title>
#         <style>
#             :root {{color-scheme: dark;
#             font-family: Arial, Helvetica, sans-serif;}}
#         </style>
#     </head>
#     <body>
#         <script id="MathJax-script" async src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"></script>
#         <div>
#         {self.source} # TODO
#         </div>
#     </body>
# </html>'''
#             )

        if os.path.isfile("out.html"):
            webbrowser.open("out.html")

    @on(Button.Pressed, "#copy")
    def copy(self) -> None:
        pyperclip.copy(self.source)

    @on(Button.Pressed, "#save_as")
    def save_as(self) -> None:
        raise NotImplementedError

    def update_subtitle(self, input_tokens: int = 0, output_tokens: int = 0) -> None:
        if input_tokens and output_tokens:
            self.border_subtitle = f"Attachments: {len(self.attachments)} Input tokens: {input_tokens} Output tokens: {output_tokens}"
            
        else:
            self.border_subtitle = f"Attachments: {len(self.attachments)}"


class PromptInput(Input):

    @dataclass
    class FixPaste(Message):
        input: Input
        first_line: str

    def _on_paste(self, event: Paste) -> None:
        if event.text:
            first_line = event.text.splitlines()[0]
            text = re.sub(r"\r?\n", " ", event.text)
            selection = self.selection
            if selection.is_empty:
                self.insert_text_at_cursor(text)
            else:
                self.replace(text, *selection)
                
            self.post_message(self.FixPaste(self, first_line))

        event.stop()


class TuiApp(App):

    AUTO_FOCUS = "Input"
    ENABLE_COMMAND_PALETTE = False
    CSS_PATH = "app.tcss"
    BINDINGS = [
        ("ctrl+c", "quit"),
        ("f1", "set_model", "Set Model"),
        ("f2", "edit_system_prompt", "Edit System Prompt"),
        ("f3", "attach_file", "Attach File(s)"),
        ("f4", "attach_screenshot", "Screenshot"),
        ("f5", "clear_context", "Clear Context"),
        ("f6", "edit_prompt", "Prompt Editor"),
        ("f7", "clear_attachments", "Clear Attachments"),
        ("f8", "edit_model_options", "Model Options"),
    ]

    def __init__(self, temp_dir: str):
        super().__init__()
        self.temp_dir = temp_dir
        self.model = llm.get_model(os.getenv("DEFAULT_MODEL", DEFAULT_MODEL))
        self.system_prompt = os.getenv("DEFAULT_SYSTEM_PROMPT")
        self.attachments: list[llm.Attachment] = []

        self.parse_model_options(os.getenv("MODEL_OPTIONS"))

        self.pandoc_path = None
        if (path := os.getenv("PANDOC_PATH")) and os.path.isfile(path):
            self.pandoc_path = path

        elif "pandoc" in os.getenv("PATH", "").lower():
            self.pandoc_path = "pandoc"

    def compose(self) -> ComposeResult:
        yield VerticalScroll()
        yield Label()
        yield PromptInput()
        yield Footer()

    def on_mount(self) -> None:
        self.get_vertical_scroll()
        self.new_conversation()

    @on(Input.Submitted)
    async def on_input(self, event: Input.Submitted) -> None:
        event.input.clear()
        await self.send_prompt(event.value)

    @on(PromptInput.FixPaste)
    def fix_paste(self, event: PromptInput.FixPaste) -> None:
        event.input.value = event.input.value.removesuffix(event.first_line)

    def action_set_model(self) -> None:
        def set_model(model: str) -> None:
            if model != self.model.model_id:
                self.model = llm.get_model(model)
                self.new_conversation()
                
            self.notify(f"Model set to: {model}")

        self.push_screen(ModelMenu(self.model.model_id), set_model)
    
    def action_edit_system_prompt(self) -> None:
        def set_system_prompt(prompt: str) -> None:
            if not prompt.strip():
                self.system_prompt = None

            else:
                self.system_prompt = prompt

            self.get_vertical_scroll().mount(Prompt(f"System prompt set to: {self.system_prompt}"))

        self.push_screen(TextEditor(self.system_prompt), set_system_prompt)

    def action_clear_context(self) -> None:
        self.new_conversation()
        self.notify("Context cleared")

    def action_attach_file(self) -> None:
        filetypes = []
        for mime in self.model.attachment_types:
            filetypes.extend((mime, ext) for ext in mimetypes.guess_all_extensions(mime))

        filenames = filedialog.askopenfilenames(filetypes=filetypes)
        for f in filenames:
            self.attach_file(f)

    def action_attach_screenshot(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".png", dir=self.temp_dir) as temp:
            try:
                get_screenshot(temp)

            except AssertionError:
                return

            self.attach_file(temp.name)

    def action_edit_prompt(self) -> None:
        self.push_screen(TextEditor(self.query_one(Input).value, update_input=True), self.send_prompt)

    def action_clear_attachments(self) -> None:
        self.clear_attachments()
        self.notify("attachments cleared")

    def action_edit_model_options(self) -> None:
        self.push_screen(TextEditor(str(self.model_options)), self.parse_model_options)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool:  
        if action == "clear_attachments":
            return bool(self.attachments)

        if action == "attach_screenshot":
            return "image/png" in self.model.attachment_types

        if action == "attach_file":
            return bool(self.model.attachment_types)

        if action == "clear_context":
            return self.input_tokens != 0

        return True

    def parse_model_options(self, text: str | None):
        self.model_options = {}
        if not text:
            return

        try:
            self.model_options = ast.literal_eval(text)
        except Exception as e:
            logger.error(e)
            self.notify("Could not parse model options. Check syntax.", title="Error")

    def attach_file(self, filename: str) -> None:
        mime, _ = mimetypes.guess_type(filename)
        if mime not in self.model.attachment_types:
            self.notify("File type not supported by this model.", title="Warning")

        self.attachments.append(llm.Attachment(path=filename))
        self.get_vertical_scroll().mount(Prompt(f"Attached file: {filename}"))
        self.update_gui()

    def clear_attachments(self) -> None:
        self.attachments.clear()
        self.update_gui()

    def new_conversation(self) -> None:
        self.conversation = self.model.conversation()
        self.input_tokens = self.output_tokens = 0
        self.update_gui()
    
    def update_gui(self) -> None:
        text = f"Attachments: {len(self.attachments)} " if self.model.attachment_types else ''
        
        if self.input_tokens != -1:
            text += f"Input Tokens: {self.input_tokens} Output Tokens: {self.output_tokens}"

        self.query_one(Label).update(text)
        self.refresh_bindings()

    async def send_prompt(self, prompt: str) -> None:
        if prompt:
            await self.get_vertical_scroll().mount(Prompt(prompt))

        elif not self.attachments:
            return

        attachments = self.attachments.copy()
        self.clear_attachments()
        await self.get_response(prompt, attachments)

    async def get_response(self, prompt: str, attachments: list[llm.Attachment]) -> None:
        response = Response(prompt, attachments, self.model.model_id, self.pandoc_path)
        await self.get_vertical_scroll().mount(response)
        model_options = self.get_supported_options(self.model, self.model_options)
        response.worker = self.stream_response(response, model_options)
        
        logger.debug(f"model={self.model.model_id}")
        logger.debug(f"system_prompt={self.system_prompt}")
        logger.debug(f"prompt={prompt}")
        logger.debug(f"attachments={attachments}")
        logger.debug(f"model_options={model_options}")
    
    @work(thread=True)
    def stream_response(self, response: Response, model_options: dict[str, Any]) -> None:
        input_tokens = output_tokens = None
        try:
            api_key = self.get_api_key(self.model)

            llm_response = self.conversation.prompt(
                response.prompt, 
                system=self.system_prompt, 
                attachments=response.attachments, 
                key=api_key, 
                **model_options
            )
            buf = []
            last_update = 0
            for chunk in llm_response:
                if response.worker.is_cancelled:
                    break

                buf.append(chunk)
                t = time.time()
                if t - last_update > RESPONSE_UPDATE_INTERVAL:
                    self.call_from_thread(response.append, "".join(buf))
                    buf.clear()
                    last_update = t

            if buf:
                self.call_from_thread(response.append, "".join(buf))

            input_tokens = llm_response.input_tokens
            output_tokens = llm_response.output_tokens

        except Exception as e:
            self.call_from_thread(response.update, f"### Error\n>{e}")
            logger.error(e)

        finally:
            response.query_one("#cancel").remove()

            if input_tokens and output_tokens:
                if self.input_tokens == -1:
                    self.input_tokens = input_tokens
                    self.output_tokens = output_tokens
                else:
                    self.input_tokens += input_tokens
                    self.output_tokens += output_tokens

                self.call_from_thread(response.update_subtitle, input_tokens, output_tokens)

            else:
                self.input_tokens = -1

            self.call_from_thread(self.update_gui)

    def get_api_key(self, model: llm.Model) -> str | None:
        try:
            return model.get_key()

        except llm.errors.NeedsKeyException:
            if model.key_env_var:
                if key := os.getenv(model.key_env_var):
                    return key

            raise
    
    def get_supported_options(self, model: llm.Model, options: dict[str, Any]) -> dict[str, Any]:
        keys = model.Options.model_fields.keys()
        return {k: v for k, v in options.items() if k in keys}

    def get_vertical_scroll(self) -> VerticalScroll:
        vs = self.query_one(VerticalScroll)
        vs.anchor()
        return vs


class TextEditor(ModalScreen):

    AUTO_FOCUS = "TextArea"
    BINDINGS = [
        ("ctrl+c", "app.quit"),
        ("escape", "back", "Back"),
        ("f1", "submit", "Submit"),
        ("f2", "clear", "Clear"),
        ("f3", "load_file", "Load File"),
    ]

    def __init__(self, text: str | None = None, update_input: bool = False):
        super().__init__()
        self.text = text if text else ""
        self.update_input = update_input

    def compose(self) -> ComposeResult:
        yield TextArea(self.text)
        yield Footer()

    def action_submit(self) -> None:
        text = self.query_one(TextArea).text
        self.dismiss(text)

    def action_back(self) -> None:
        if self.update_input:
            text = re.sub(r"\r?\n", " ", self.query_one(TextArea).text)
            self.app.query_one(PromptInput).value = text

        self.app.pop_screen()

    def action_clear(self) -> None:
        self.query_one(TextArea).clear()

    def action_load_file(self) -> None:
        filename = filedialog.askopenfilename()
        if not filename:
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


class ModelMenu(ModalScreen):

    AUTO_FOCUS = "OptionList"
    BINDINGS = [
        ("ctrl+c", "app.quit"),
        ("escape", "app.pop_screen", "Back"),
    ]

    def __init__(self, curr_model: str):
        super().__init__()
        self.curr_model = curr_model

    def compose(self) -> ComposeResult:
        models = [model.model_id for model in llm.get_models()]
        option_list = OptionList(*models)
        option_list.highlighted = models.index(self.curr_model)
        yield option_list
        yield Footer()

    @on(OptionList.OptionSelected)
    def on_input(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option.prompt)


def main():

    parser = argparse.ArgumentParser()
    parser.add_argument("-d", "--debug", action="store_true")
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG, filename="debug.log")

    load_dotenv()

    with tempfile.TemporaryDirectory() as temp_dir:
        app = TuiApp(temp_dir)
        app.run()


if __name__ == "__main__":
    main()