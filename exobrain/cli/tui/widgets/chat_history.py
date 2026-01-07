"""Chat history container widget."""

from __future__ import annotations

from typing import Literal

from textual.containers import VerticalScroll
from textual.widget import Widget

from exobrain.cli.tui.widgets.message import MessageWidget, StreamingMessage


class ChatHistory(VerticalScroll):
    """Scrollable container for chat messages.

    Automatically scrolls to bottom when new messages are added.
    Supports both static messages and streaming messages.
    """

    DEFAULT_CSS = """
    ChatHistory {
        height: 1fr;
        padding: 1 2;
        background: $background;
    }

    ChatHistory > MessageWidget {
        margin: 0 0 1 0;
    }

    ChatHistory > StreamingMessage {
        margin: 0 0 1 0;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._streaming_message: StreamingMessage | None = None
        self._thinking_message: MessageWidget | None = None
        self._thinking_block: MessageWidget | None = None

    async def add_message(
        self,
        content: str,
        role: Literal["user", "assistant", "system", "tool"] = "assistant",
        title: str | None = None,
        border_style: str | None = None,
    ) -> MessageWidget:
        """Add a static message to the history.

        Args:
            content: Message content
            role: Message role (user, assistant, or system)
            title: Optional title override for panel-based messages
            border_style: Optional border color override

        Returns:
            The created MessageWidget
        """
        message = MessageWidget(content, role=role, title=title, border_style=border_style)
        await self.mount(message)
        self.scroll_end(animate=False)
        return message

    async def add_tool_call(
        self,
        tool_name: str,
        summary: str | None,
        is_error: bool = False,
    ) -> MessageWidget:
        """Add a tool call message with consistent styling."""
        border = "red" if is_error else "cyan"
        title = f"Tool · {tool_name}"
        content = (summary or "").strip() or "(no output)"
        return await self.add_message(content, role="tool", title=title, border_style=border)

    async def start_streaming(self) -> StreamingMessage:
        """Start a new streaming message.

        Returns:
            The StreamingMessage widget to append chunks to
        """
        # Finalize any existing streaming message first
        if self._streaming_message is not None:
            await self.finalize_streaming()

        self._streaming_message = StreamingMessage()
        await self.mount(self._streaming_message)
        self.scroll_end(animate=False)
        return self._streaming_message

    async def append_to_stream(self, chunk: str) -> None:
        """Append a chunk to the current streaming message.

        Args:
            chunk: Text chunk to append
        """
        if self._streaming_message is not None:
            await self._streaming_message.append(chunk)
            self.scroll_end(animate=False)

    async def finalize_streaming(self) -> MessageWidget | None:
        """Finalize the current streaming message.

        Converts the streaming message to a static message.

        Returns:
            The finalized MessageWidget, or None if no streaming message
        """
        if self._streaming_message is None:
            return None

        content = self._streaming_message.get_content()

        # Remove streaming widget
        await self._streaming_message.remove()

        # Add static message with final content
        if content.strip():
            message = await self.add_message(content, role="assistant")
            self._streaming_message = None
            return message

        self._streaming_message = None
        return None

    @property
    def is_streaming(self) -> bool:
        """Check if currently streaming a message."""
        return self._streaming_message is not None

    async def clear_history(self) -> None:
        """Clear all messages from history."""
        if self._streaming_message is not None:
            self._streaming_message = None

        await self.query("MessageWidget, StreamingMessage").remove()

    def scroll_to_bottom(self) -> None:
        """Scroll to the bottom of the chat history."""
        self.scroll_end(animate=False)

    async def show_thinking(self, message: str = "Thinking...") -> None:
        """Show a temporary thinking indicator.

        Args:
            message: The thinking message to display
        """
        # Remove any existing thinking message
        await self.hide_thinking()

        # Add new thinking message
        self._thinking_message = MessageWidget(f"💭 {message}", role="system")
        await self.mount(self._thinking_message)
        self.scroll_end(animate=False)

    async def hide_thinking(self) -> None:
        """Hide the thinking indicator."""
        if self._thinking_message is not None:
            await self._thinking_message.remove()
            self._thinking_message = None

    async def show_thinking_block(self, content: str) -> None:
        """Show a thinking block (model's reasoning, not saved to history).

        Args:
            content: The thinking content to display
        """
        # Remove any existing thinking block
        await self.hide_thinking_block()

        # Add new thinking block
        self._thinking_block = MessageWidget(content, role="thinking")
        await self.mount(self._thinking_block)
        self.scroll_end(animate=False)

    async def hide_thinking_block(self) -> None:
        """Hide the thinking block."""
        if self._thinking_block is not None:
            await self._thinking_block.remove()
            self._thinking_block = None
