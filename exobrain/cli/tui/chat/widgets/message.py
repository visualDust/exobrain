"""Message display widgets for chat interface."""

from __future__ import annotations

import asyncio
from typing import Literal

from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static


class MessageWidget(Static):
    """A static message widget for completed messages."""

    def __init__(
        self,
        content: str,
        role: Literal["user", "assistant", "system", "tool", "thinking"] = "assistant",
        title: str | None = None,
        border_style: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.content = content
        self.role = role
        self.title = title
        self.border_style = border_style

    def render(self):
        """Render the message with appropriate styling."""
        if self.role == "tool":
            return Panel(
                Markdown(self.content),
                title=self.title or "Tool",
                title_align="left",
                border_style=self.border_style or "blue",
            )

        if self.role == "user":
            return Panel(
                Text(self.content),
                title="You",
                title_align="left",
                border_style="green",
            )
        elif self.role == "assistant":
            return Panel(
                Markdown(self.content),
                title="Assistant",
                title_align="left",
                border_style="cyan",
            )
        elif self.role == "thinking":
            return Panel(
                Markdown(self.content),
                title="💭 Thinking",
                title_align="left",
                border_style="yellow dim",
                subtitle="(not saved to history)",
                subtitle_align="right",
            )
        else:  # system
            return Text(f"[System] {self.content}", style="yellow italic")


class StreamingMessage(Widget):
    """A message widget that supports streaming updates with throttling."""

    DEFAULT_CSS = """
    StreamingMessage {
        height: auto;
        padding: 0;
        margin: 0 0 1 0;
    }

    StreamingMessage > Static {
        height: auto;
    }
    """

    # Reactive property to track content changes
    content = reactive("", layout=True)

    # Throttle interval in seconds
    THROTTLE_INTERVAL = 0.05  # 50ms

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._buffer = ""
        self._last_update = 0.0
        self._pending_update = False
        self._update_lock = asyncio.Lock()
        self._static = Static("", id="streaming-content")

    def compose(self):
        """Compose the streaming message widget."""
        yield self._static

    def watch_content(self, new_content: str) -> None:
        """React to content changes."""
        self._update_display(new_content)

    def _update_display(self, content: str) -> None:
        """Update the display with new content."""
        if not content:
            self._static.update("")
            return

        panel = Panel(
            Markdown(content) if content.strip() else Text(content),
            title="Assistant",
            title_align="left",
            border_style="cyan dim",
            subtitle="streaming...",
            subtitle_align="right",
        )
        self._static.update(panel)

    async def append(self, chunk: str) -> None:
        """Append a chunk to the message with throttling.

        Args:
            chunk: Text chunk to append
        """
        self._buffer += chunk

        current_time = asyncio.get_event_loop().time()
        time_since_update = current_time - self._last_update

        if time_since_update >= self.THROTTLE_INTERVAL:
            # Enough time has passed, update immediately
            await self._do_update()
        elif not self._pending_update:
            # Schedule a delayed update
            self._pending_update = True
            asyncio.create_task(self._delayed_update())

    async def _delayed_update(self) -> None:
        """Perform a delayed update after throttle interval."""
        await asyncio.sleep(self.THROTTLE_INTERVAL)
        await self._do_update()
        self._pending_update = False

    async def _do_update(self) -> None:
        """Actually perform the update."""
        async with self._update_lock:
            self.content = self._buffer
            self._last_update = asyncio.get_event_loop().time()

    def finalize(self) -> MessageWidget:
        """Finalize the streaming message and return a static MessageWidget.

        Returns:
            A static MessageWidget with the final content
        """
        return MessageWidget(self._buffer, role="assistant")

    def get_content(self) -> str:
        """Get the current content buffer.

        Returns:
            The accumulated content
        """
        return self._buffer
