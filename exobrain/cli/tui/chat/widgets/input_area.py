"""Input area widget for user messages."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.events import Key
from textual.message import Message
from textual.widgets import Button, Static, TextArea


class ChatTextArea(TextArea):
    """Custom TextArea that emits submit on Ctrl+Enter."""

    class Submit(Message):
        """Message sent when user presses Ctrl+Enter."""

    def _on_key(self, event: Key) -> None:
        """Handle key events before default processing."""
        # Ctrl+Enter can appear as different key combinations depending on terminal
        # Common mappings: ctrl+enter, ctrl+j, ctrl+m
        if event.key in ("ctrl+enter", "ctrl+j", "ctrl+m"):
            self.post_message(self.Submit())
            event.prevent_default()
            event.stop()
            return
        # Let parent handle other keys
        super()._on_key(event)


class InputArea(Static, can_focus=False):
    """Input area with expandable text input and submit button."""

    # Define bindings that bubble up to app level
    BINDINGS = [
        Binding("ctrl+d", "app.quit", "Exit", priority=True),
        Binding("ctrl+l", "app.clear", "Clear", priority=True),
    ]

    DEFAULT_CSS = """
    InputArea {
        height: auto;
        min-height: 3;
        max-height: 8;
        background: $surface;
        padding: 0 1;
    }

    InputArea > Horizontal {
        height: auto;
        min-height: 3;
        align: center middle;
    }

    InputArea ChatTextArea {
        height: auto;
        min-height: 1;
        max-height: 6;
        border: none;
        background: $surface;
        padding: 0 1;
        width: 1fr;
    }

    InputArea ChatTextArea:focus {
        border: none;
    }

    InputArea Button {
        width: 8;
        height: 3;
        min-width: 8;
        margin: 0 0 0 1;
    }

    InputArea .prompt-label {
        width: 2;
        height: 3;
        content-align: center middle;
        color: $primary;
    }
    """

    class Submitted(Message):
        """Message sent when user submits input."""

        def __init__(self, value: str) -> None:
            self.value = value
            super().__init__()

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._text_area = ChatTextArea(id="user-input")
        self._text_area.show_line_numbers = False
        self._submit_button = Button("Send", id="submit-btn", variant="primary")

    def compose(self) -> ComposeResult:
        """Compose the input area."""
        with Horizontal():
            yield Static(">", classes="prompt-label")
            yield self._text_area
            yield self._submit_button

    def on_mount(self) -> None:
        """Focus the text area on mount."""
        self._text_area.focus()

    @on(Button.Pressed, "#submit-btn")
    def on_submit_pressed(self) -> None:
        """Handle submit button press."""
        self._submit()

    @on(ChatTextArea.Submit)
    def on_text_area_submit(self) -> None:
        """Handle Ctrl+Enter from text area."""
        self._submit()

    def _on_key(self, event: Key) -> None:
        """Forward app-level shortcuts even when text area has focus."""
        if event.key == "ctrl+d":
            self.app.action_quit()
            event.stop()
        elif event.key == "ctrl+l":
            self.app.action_clear()
            event.stop()

    def _submit(self) -> None:
        """Submit the current input."""
        text = self._text_area.text.strip()
        if text:
            self.post_message(self.Submitted(text))
            self._text_area.clear()
            self._text_area.focus()

    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable the input area."""
        self._text_area.disabled = not enabled
        self._submit_button.disabled = not enabled

    def focus_input(self) -> None:
        """Focus the text input."""
        self._text_area.focus()

    @property
    def text(self) -> str:
        """Get the current input text."""
        return self._text_area.text
