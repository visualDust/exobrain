"""Header widget for displaying session info."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from rich.console import RenderableType
from rich.table import Table
from rich.text import Text
from textual.widgets import Static


@dataclass
class HeaderInfo:
    """Information to display in the header."""

    scope: str = "global"  # "project" or "global"
    project_name: Optional[str] = None
    config_path: Optional[str] = None
    working_dir: Optional[str] = None
    model: Optional[str] = None
    session_id: Optional[str] = None
    session_name: Optional[str] = None


class Header(Static):
    """Header widget showing session information.

    Displays:
    - Session scope (project/global)
    - Config file path
    - Current working directory
    - Model name
    """

    DEFAULT_CSS = """
    Header {
        dock: top;
        height: 1;
        background: $primary-darken-2;
        color: $text;
        padding: 0 1;
    }
    """

    def __init__(self, info: Optional[HeaderInfo] = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._info = info or HeaderInfo()

    def render(self) -> RenderableType:
        """Render the header content."""
        info = self._info

        # Create a single-row table for layout
        table = Table.grid(expand=True)
        table.add_column("left", justify="left", ratio=1)
        table.add_column("center", justify="center", ratio=1)
        table.add_column("right", justify="right", ratio=1)

        # Left: Scope and project info
        left = Text()
        scope_icon = "📁" if info.scope == "project" else "🏠"
        if info.scope == "project":
            left.append(f"{scope_icon} Session scope: ", style="dim")
            left.append("Project", style="bold blue")
            if info.project_name:
                left.append(f" {info.project_name}", style="cyan")
        else:
            left.append(f"{scope_icon} Session scope: ", style="dim")
            left.append("User", style="bold green")

        # Center: Chat title and session ID
        center = Text()
        if info.session_name:
            # Show chat title
            title = info.session_name
            if len(title) > 40:
                title = title[:37] + "..."
            center.append(title, style="bold white")
            if info.session_id:
                center.append(f" (󰮯 {info.session_id[:8]})", style="dim")
        elif info.session_id:
            # Only show session ID if no title
            center.append("󰮯 ", style="dim yellow")
            center.append(info.session_id[:8], style="yellow")
        else:
            # No session yet
            center.append("ExoBrain", style="bold white")

        # Right: Working directory (truncated)
        right = Text()
        if info.working_dir:
            wd = info.working_dir
            # Truncate if too long
            if len(wd) > 35:
                wd = "..." + wd[-32:]
            right.append(" ", style="dim")
            right.append(wd, style="dim")

        table.add_row(left, center, right)

        return table

    def update_info(self, info: HeaderInfo) -> None:
        """Update the header information.

        Args:
            info: New header information
        """
        self._info = info
        self.refresh()

    def set_session_id(self, session_id: Optional[str]) -> None:
        """Update just the session ID.

        Args:
            session_id: New session ID
        """
        self._info.session_id = session_id
        self.refresh()
