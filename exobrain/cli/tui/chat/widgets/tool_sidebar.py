"""Sidebar widget to show recent tool calls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from rich.panel import Panel
from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Static


@dataclass
class ToolEvent:
    """Lightweight representation of a tool invocation."""

    name: str
    summary: str


class ToolSidebar(VerticalScroll):
    """Collapsible sidebar that shows recent tool calls."""

    DEFAULT_CSS = """
    ToolSidebar {
        width: 32;
        min-width: 26;
        max-width: 36;
        border-left: solid $primary-darken-1;
        background: $surface;
        padding: 1 1;
    }

    ToolSidebar.collapsed {
        display: none;
    }

    ToolSidebar > .sidebar-header {
        text-align: center;
        text-style: bold;
        color: $accent;
        margin: 0 0 1 0;
        padding: 0 0 1 0;
        border-bottom: solid $primary-darken-1;
    }

    ToolSidebar > .tool-card {
        margin: 0 0 1 0;
    }

    ToolSidebar > .empty-message {
        text-align: center;
        color: $text-muted;
        margin: 2 0;
    }
    """

    def __init__(self, collapsed: bool = False, **kwargs) -> None:
        super().__init__(**kwargs)
        self._collapsed = collapsed
        self._event_count = 0
        self._header: Static | None = None
        self._empty_message: Static | None = None
        if collapsed:
            self.add_class("collapsed")

    def compose(self):
        """Compose the sidebar with header."""
        self._header = Static("📜 Event History", classes="sidebar-header")
        yield self._header
        self._empty_message = Static("No event yet 😅", classes="empty-message")
        yield self._empty_message

    def toggle(self) -> None:
        """Toggle collapsed state."""
        self._collapsed = not self._collapsed
        self.set_class(self._collapsed, "collapsed")

    async def add_event(self, event: ToolEvent) -> None:
        """Add a single tool event card."""
        # Remove empty message on first event
        if self._event_count == 0 and self._empty_message is not None:
            await self._empty_message.remove()
            self._empty_message = None

        self._event_count += 1

        title = Text(event.name, style="bold cyan")
        body = Text(event.summary or "No output", style="dim")
        card = Static(
            Panel(body, title=title, border_style="cyan", padding=(0, 1)),
            classes="tool-card",
        )
        await self.mount(card)
        self.scroll_end(animate=False)

    async def load_events(self, events: Iterable[ToolEvent]) -> None:
        """Bulk-load initial events."""
        for event in events:
            await self.add_event(event)
