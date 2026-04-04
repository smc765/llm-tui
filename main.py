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
from tkinter import filedialog
from typing import Any
from dataclasses import dataclass

import llm
from dotenv import load_dotenv

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll, HorizontalGroup
from textual.widgets import Footer, Input, Markdown, OptionList, Label, TextArea, Button
from textual.screen import ModalScreen
from textual.worker import Worker
from textual.message import Message

from screenshot import get_screenshot

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-4o-mini"
RESPONSE_UPDATE_INTERVAL = 0.1


class Prompt(Markdown):
    """Markdown for prompt."""


class Response(Markdown):
    """Markdown for llm response."""

    @dataclass
    class Regenerate(Message):
        prompt: str
        attachments: list[llm.Attachment]

    def __init__(self, prompt: str, attachments: list[llm.Attachment], model: str):
        super().__init__()
        self.prompt = prompt
        self.attachments = attachments
        self.border_title = model
        self.border_subtitle = f"Attachments: {len(attachments)}"
        self.worker: Worker | None = None

    def compose(self) -> ComposeResult:
        yield HorizontalGroup(
            Button("Regenerate", id="regenerate"),
            Button("Open in Browser", id="open_in_browser"),
            Button("Cancel", id="cancel"),
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "open_in_browser":
            self.open_in_browser()

        if event.button.id == "regenerate":
            self.post_message(self.Regenerate(self.prompt, self.attachments))

        if event.button.id == "cancel":
            if self.worker is not None:
                self.worker.cancel()

    def open_in_browser(self) -> None:
        with tempfile.NamedTemporaryFile(delete_on_close=False, suffix=".md", mode="w", encoding="utf-8") as temp_md:
            temp_md.write(self.source)
            temp_md.close()
            try:
                subprocess.run(["pandoc", temp_md.name, "-s", "--mathjax", "-o", "out.html"], check=True)

            except subprocess.CalledProcessError as e:
                logger.error(f"pandoc error: {e}")
                return

            webbrowser.open("out.html")

    def finalize(self, input_tokens: int | None, output_tokens: int | None) -> None:
        self.query_one("#cancel").remove()
        if None not in (input_tokens, output_tokens):
            self.border_subtitle += f" Input tokens: {input_tokens} Output tokens: {output_tokens}"


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
        ("f7", "clear_attachments", "Clear Attachments"),
    ]

    def __init__(self, temp_dir: str):
        super().__init__()
        self.temp_dir = temp_dir
        self.model: llm.Model = llm.get_model(os.getenv("DEFAULT_MODEL", DEFAULT_MODEL))
        self.conversation: llm.Conversation = self.model.conversation()
        self.system_prompt: str | None = os.getenv("DEFAULT_SYSTEM_PROMPT")
        self.attachments: list[llm.Attachment] = []

        if model_options := os.getenv("MODEL_OPTIONS"):
            self.model_options = ast.literal_eval(model_options)

        else:
            self.model_options = {}

    def compose(self) -> ComposeResult:
        yield VerticalScroll()
        yield Label("Attachments: 0")
        yield Input()
        yield Footer()

    def on_mount(self) -> None:
        self.query_one(VerticalScroll).anchor()

    @on(Input.Submitted)
    async def on_input(self, event: Input.Submitted) -> None:
        event.input.clear()
        await self.send_prompt(event.value)

    @on(Response.Regenerate)
    async def regenerate(self, event: Response.Regenerate) -> None:
        await self.get_response(event.prompt, event.attachments)

    def action_set_model(self) -> None:
        def set_model(model: str) -> None:
            self.model = llm.get_model(model)
            self.conversation = self.model.conversation()
            self.notify(f"model set to: {model}")

        self.push_screen(ModelMenu(self.model.model_id), set_model)
    
    def action_edit_system_prompt(self) -> None:
        def set_system_prompt(prompt: str) -> None:
            if prompt.isspace() or prompt == "":
                self.system_prompt = None

            else:
                self.system_prompt = prompt

            self.query_one(VerticalScroll).mount(Prompt(f"system prompt set to: {self.system_prompt}"))

        self.push_screen(TextEditor(self.system_prompt), set_system_prompt)

    def action_clear_context(self) -> None:
        self.conversation = self.model.conversation()
        self.notify("context cleared")

    def action_attach_file(self) -> None:
        filetypes = []
        for mime_type in self.model.attachment_types:
            filetypes.extend((mime_type, ext) for ext in mimetypes.guess_all_extensions(mime_type))

        if not filetypes:
            self.notify("this model does not support file uploads", title="Error")
            return

        filenames = filedialog.askopenfilenames(filetypes=filetypes)
        for f in filenames:
            self.attach_file(f)

    def action_attach_screenshot(self) -> None:
        if "image/png" not in self.model.attachment_types:
            self.notify("this model does not support image uploads", title="Error")
            return

        with tempfile.NamedTemporaryFile(delete=False, suffix=".png", dir=self.temp_dir) as temp:
            try:
                get_screenshot(temp)

            except AssertionError:
                return

            self.attach_file(temp.name)

    def action_multiline_prompt(self) -> None:
        self.push_screen(TextEditor(), self.send_prompt)

    def action_clear_attachments(self) -> None:
        self.clear_attachments()
        self.notify("attachments cleared")

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool:  
        if action == "clear_attachments" and len(self.attachments) == 0:
            return False

        return True

    def attach_file(self, filename: str) -> None:
        self.attachments.append(llm.Attachment(path=filename))
        self.query_one(VerticalScroll).mount(Prompt(f"Attached File: {filename}"))
        self.update_attachment_count()

    def clear_attachments(self) -> None:
        self.attachments.clear()
        self.update_attachment_count()
    
    def update_attachment_count(self) -> None:
        self.query_one(Label).update(f"Attachments: {len(self.attachments)}")
        self.refresh_bindings()

    async def send_prompt(self, prompt: str)-> None:
        if prompt != "":
            await self.query_one(VerticalScroll).mount(Prompt(prompt))

        elif len(self.attachments) == 0:
            return

        attachments = self.attachments.copy()
        self.clear_attachments()
        await self.get_response(prompt, attachments)

    async def get_response(self, prompt: str, attachments: list[llm.Attachment]) -> None:
        response = Response(prompt, attachments, self.model.model_id)
        await self.query_one(VerticalScroll).mount(response)
        model_options = self.get_supported_model_options(self.model, self.model_options)
        response.worker = self.stream_response(response, model_options)
        
        logger.debug(f"model={self.model.model_id}")
        logger.debug(f"system_prompt={self.system_prompt}")
        logger.debug(f"prompt={prompt}")
        logger.debug(f"attachments={attachments}")
        logger.debug(f"model_options={model_options}")
    
    def get_supported_model_options(self, model: llm.Model, options: dict[str, Any]) -> dict[str, Any]:
        model_keys = model.Options.model_fields.keys()
        return {k: options[k] for k in model_keys if k in options}
    
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

            input_tokens, output_tokens = llm_response.input_tokens, llm_response.output_tokens

        except Exception as e:
            self.call_from_thread(response.update, f"### Error\n>{e}")
            logger.error(e)

        finally:
            self.call_from_thread(response.finalize, input_tokens, output_tokens)

    def get_api_key(self, model: llm.Model) -> str | None:
        try:
            return model.get_key()

        except llm.errors.NeedsKeyException:
            if model.key_env_var:
                if key := os.getenv(model.key_env_var):
                    return key

            raise


class TextEditor(ModalScreen):

    AUTO_FOCUS = "TextArea"
    BINDINGS = [
        ("ctrl+c", "app.quit"),
        ("escape", "app.pop_screen", "Back"),
        ("f1", "submit", "Submit"),
        ("f2", "clear", "Clear"),
        ("f3", "load_file", "Load File"),
    ]

    def __init__(self, text: str | None = None):
        super().__init__()
        self.text = text if text else ""

    def compose(self) -> ComposeResult:
        yield TextArea(self.text)
        yield Footer()

    def action_submit(self) -> None:
        text = self.query_one(TextArea).text
        self.dismiss(text)

    def action_clear(self) -> None:
        self.query_one(TextArea).clear()

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


class ModelMenu(ModalScreen):

    AUTO_FOCUS = "OptionList"
    BINDINGS = [
        ("ctrl+c", "app.quit"),
        ("escape", "app.pop_screen", "back"),
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

    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("-d", "--debug", action="store_true")
    args = parser.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG, filename="debug.log")

    with tempfile.TemporaryDirectory() as temp_dir:
        app = TuiApp(temp_dir)
        app.run()


if __name__ == "__main__":
    main()