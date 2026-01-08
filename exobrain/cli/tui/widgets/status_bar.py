"""Status bar widget for displaying agent state."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from rich.console import Group
from rich.table import Table
from rich.text import Text
from textual.reactive import reactive
from textual.timer import Timer
from textual.widgets import Static


class AgentState(Enum):
    """Agent execution states."""

    IDLE = "idle"
    THINKING = "thinking"
    TOOL_CALLING = "tool_calling"
    WAITING = "waiting"
    STREAMING = "streaming"
    ERROR = "error"
    FINISHED = "finished"


@dataclass
class StatusInfo:
    """Container for status information."""

    state: AgentState = AgentState.IDLE
    current_tool: Optional[str] = None
    tool_args: Optional[str] = None
    iteration: int = 0
    max_iterations: int = 500
    tokens_used: int = 0
    error_message: Optional[str] = None


class StatusBar(Static):
    """A status bar showing agent state.

    Wide layout (>60 cols):  [State] [Details...] [Progress]
    Narrow layout:           [State]
                            [Details]
    """

    DEFAULT_CSS = """
    StatusBar {
        height: auto;
        min-height: 1;
        max-height: 2;
        background: $surface;
        border-top: solid $primary-darken-2;
        padding: 0 1;
    }
    """

    # State icons and colors
    STATE_DISPLAY = {
        AgentState.IDLE: ("●", "Ready", "dim"),
        AgentState.THINKING: ("◐", "Thinking", "yellow"),
        AgentState.TOOL_CALLING: ("⚙", "Tool", "blue"),
        AgentState.WAITING: ("◷", "Waiting", "cyan"),
        AgentState.STREAMING: ("▶", "Streaming", "green"),
        AgentState.ERROR: ("✗", "Error", "red"),
        AgentState.FINISHED: ("✓", "Done", "green"),
    }

    # Reactive status info
    status = reactive(StatusInfo())
    spinner_index = reactive(0)
    BUSY_STATES = {
        AgentState.THINKING,
        AgentState.TOOL_CALLING,
        AgentState.WAITING,
        AgentState.STREAMING,
    }
    SPINNER_FRAMES = ["◐", "◓", "◑", "◒"]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._spinner_timer: Timer | None = None
        self._meta_text: str = ""

    def on_mount(self) -> None:
        """Set up spinner refresh timer."""
        self._spinner_timer = self.set_interval(0.2, self._advance_spinner, pause=True)

    def watch_status(self, new_status: StatusInfo) -> None:
        """React to status changes and re-render."""
        if self._spinner_timer:
            if new_status.state in self.BUSY_STATES:
                self._spinner_timer.resume()
            else:
                self.spinner_index = 0
                self._spinner_timer.pause()
        self.refresh()

    def _advance_spinner(self) -> None:
        """Advance spinner frame for busy states."""
        if self.status.state in self.BUSY_STATES:
            self.spinner_index = (self.spinner_index + 1) % len(self.SPINNER_FRAMES)
            self.refresh()

    def set_meta(
        self,
        model: str | None = None,
        constitution: str | None = None,
        tools: int | None = None,
        skills: int | None = None,
    ) -> None:
        """Set static metadata such as model, constitution, and tool/skill counts."""
        parts: list[str] = []
        if model:
            parts.append(model)
        if constitution:
            parts.append(f"📜 {constitution}")
        if tools is not None:
            parts.append(f"🛠️  {tools}")
        if skills is not None:
            parts.append(f"📚 {skills}")
        self._meta_text = " | ".join(parts)
        self.refresh()

    def render(self):
        """Render the status bar content."""
        status = self.status
        icon, state_label, color = self.STATE_DISPLAY.get(status.state, ("?", "Unknown", "white"))
        if status.state in self.BUSY_STATES:
            icon = self.SPINNER_FRAMES[self.spinner_index]

        # Get width
        width = self.size.width if self.size.width > 0 else 80

        # Build state part
        state_text = Text()
        state_text.append(f" {icon} ", style=f"bold {color}")
        state_text.append(state_label, style=color)

        # Build details part
        details_text = Text()
        if status.state == AgentState.TOOL_CALLING and status.current_tool:
            details_text.append(status.current_tool, style="cyan")
            if status.tool_args:
                max_args = 30 if width < 100 else 50
                args_display = status.tool_args[:max_args]
                if len(status.tool_args) > max_args:
                    args_display += "..."
                details_text.append(f"({args_display})", style="dim")
        elif status.state == AgentState.ERROR and status.error_message:
            max_err = 40 if width < 100 else 60
            details_text.append(status.error_message[:max_err], style="red")
        elif status.state == AgentState.STREAMING:
            details_text.append("receiving...", style="dim green")
        elif status.state == AgentState.THINKING:
            details_text.append("processing...", style="dim yellow")

        # Wide layout: single line with table
        if width >= 60:
            table = Table.grid(expand=True)
            table.add_column("state", justify="left", width=15)
            table.add_column("details", justify="left", ratio=1)
            table.add_column("meta", justify="right", no_wrap=True)
            # If streaming/working and no explicit details, show subtle placeholder
            if not details_text.plain and status.state in self.BUSY_STATES:
                details_text = Text("working...", style="dim")
            table.add_row(state_text, details_text, Text(self._meta_text, style="dim"))
            return table
        else:
            # Narrow layout: stack vertically
            blocks = [state_text]
            if details_text.plain:
                blocks.append(details_text)
            if self._meta_text:
                blocks.append(Text(self._meta_text, style="dim"))
            return Group(*blocks)

    def update_state(
        self,
        state: AgentState,
        current_tool: Optional[str] = None,
        tool_args: Optional[str] = None,
        iteration: Optional[int] = None,
        tokens_used: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Update the status bar state."""
        new_status = StatusInfo(
            state=state,
            current_tool=current_tool,
            tool_args=tool_args,
            iteration=iteration if iteration is not None else self.status.iteration,
            max_iterations=self.status.max_iterations,
            tokens_used=tokens_used if tokens_used is not None else self.status.tokens_used,
            error_message=error_message,
        )
        self.status = new_status

    def set_idle(self) -> None:
        """Set status to idle."""
        self.update_state(AgentState.IDLE)

    def set_thinking(self) -> None:
        """Set status to thinking."""
        self.update_state(AgentState.THINKING)

    def set_streaming(self) -> None:
        """Set status to streaming."""
        self.update_state(AgentState.STREAMING)

    def set_tool_calling(self, tool_name: str, args: Optional[str] = None) -> None:
        """Set status to tool calling."""
        self.update_state(AgentState.TOOL_CALLING, current_tool=tool_name, tool_args=args)

    def set_finished(self) -> None:
        """Set status to finished."""
        self.update_state(AgentState.FINISHED)

    def set_error(self, message: str = "") -> None:
        """Set status to error."""
        self.update_state(AgentState.ERROR, error_message=message)
