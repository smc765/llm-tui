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

    @on(Button.Pressed, "#regenerate")
    def regenerate(self) -> None:
        self.post_message(self.Regenerate(self.prompt, self.attachments))

    @on(Button.Pressed, "#cancel")
    def cancel(self) -> None:
        if self.worker:
            self.worker.cancel()

    @on(Button.Pressed, "#open_in_browser")
    def open_in_browser(self) -> None:
        with tempfile.NamedTemporaryFile(delete_on_close=False, suffix=".md", mode="w", encoding="utf-8") as temp_md:
            temp_md.write(self.source)
            temp_md.close()
            cmd = [
                "pandoc", temp_md.name,
                "-s", "--mathjax",
                "-o", "out.html",
            ]
            try:
                subprocess.run(cmd, check=True)

            except subprocess.CalledProcessError as e:
                logger.error(e)
                return

            webbrowser.open("out.html")

    def finalize(self, input_tokens: int | None, output_tokens: int | None) -> None:
        if input_tokens and output_tokens:
            self.border_subtitle += f" Input tokens: {input_tokens} Output tokens: {output_tokens}"

        self.query_one("#cancel").remove()


class PromptInput(Input):

    def _on_paste(self, event: Paste) -> None:
        event.stop()
        if self.value or not event.text:
            return

        if len(event.text.splitlines()) > 1:
            self.post_message(self.Submitted(self, event.text, None))


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
        ("f6", "multiline_prompt", "Multiline Prompt"),
        ("f7", "clear_attachments", "Clear Attachments"),
    ]

    def __init__(self, temp_dir: str):
        super().__init__()
        self.temp_dir = temp_dir
        self.model = llm.get_model(os.getenv("DEFAULT_MODEL", DEFAULT_MODEL))
        self.conversation = self.model.conversation()
        self.system_prompt: str | None = os.getenv("DEFAULT_SYSTEM_PROMPT")
        self.attachments: list[llm.Attachment] = []
        self.model_options: dict[str, Any] = {}

        if model_options := os.getenv("MODEL_OPTIONS"):
            self.model_options = ast.literal_eval(model_options)

    def compose(self) -> ComposeResult:
        yield VerticalScroll()
        yield Label("Attachments: 0")
        yield PromptInput()
        yield Footer()

    def on_mount(self) -> None:
        self.get_vertical_scroll()

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
        self.conversation = self.model.conversation()
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

    def action_multiline_prompt(self) -> None:
        self.push_screen(TextEditor(), self.send_prompt)

    def action_clear_attachments(self) -> None:
        self.clear_attachments()
        self.notify("attachments cleared")

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool:  
        if action == "clear_attachments":
            return bool(self.attachments)

        if action == "attach_screenshot":
            return "image/png" in self.model.attachment_types

        if action == "attach_file":
            return bool(self.model.attachment_types)

        return True

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
    
    def update_gui(self) -> None:
        self.query_one(Label).update(f"Attachments: {len(self.attachments)}")
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
        response = Response(prompt, attachments, self.model.model_id)
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
            self.call_from_thread(response.finalize, input_tokens, output_tokens)

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