"""Rich-based UI components for ExoBrain CLI."""

from typing import Optional

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.text import Text

from exobrain.agent.core import AgentState


class StatusPanel:
    """Real-time status panel for agent execution."""

    def __init__(self, console: Console):
        self.console = console
        self.state: AgentState = AgentState.IDLE
        self.iteration = 0
        self.max_iterations = 500
        self.current_tool = None
        self.token_usage = {"prompt": 0, "completion": 0, "total": 0}

    def update(
        self,
        state: Optional[AgentState | str] = None,
        iteration: Optional[int] = None,
        tool: Optional[str] = None,
        tokens: Optional[dict] = None,
    ):
        """Update status values."""
        if state is not None:
            if isinstance(state, AgentState):
                self.state = state
            elif isinstance(state, str):
                normalized = state.lower().replace(" ", "_")
                alias_map = {
                    "calling_tools": AgentState.TOOL_CALLING,
                    "finished": AgentState.FINISHED,
                    "idle": AgentState.IDLE,
                    "thinking": AgentState.THINKING,
                }
                try:
                    self.state = alias_map.get(normalized, AgentState(normalized))
                except Exception:
                    self.state = AgentState.IDLE
        if iteration is not None:
            self.iteration = iteration
        if tool is not None:
            self.current_tool = tool
        if tokens is not None:
            self.token_usage.update(tokens)

    def render(self) -> Panel:
        """Render the status panel."""
        # State indicator with emoji
        state_display = {
            AgentState.IDLE: ("Idle", "💤", "dim"),
            AgentState.THINKING: ("Thinking", "🤔", "yellow"),
            AgentState.TOOL_CALLING: ("Calling Tools", "🔧", "cyan"),
            AgentState.WAITING: ("Waiting", "⏳", "blue"),
            AgentState.ERROR: ("Error", "❌", "red"),
            AgentState.FINISHED: ("Finished", "✅", "green"),
            AgentState.STREAMING: ("Streaming", "▶", "green"),
        }
        label, icon, style = state_display.get(self.state, ("Working", "●", "white"))
        busy = self.state not in (AgentState.IDLE, AgentState.FINISHED, AgentState.ERROR)

        # Build status line
        status_parts = [
            Text(f"{icon} ", style=style),
            Text(" State: ", style="bold"),
            Text(label, style=style),
            Text(" | ", style="dim"),
            Text(f"Iteration: ", style="bold"),
            Text(f"{self.iteration}/{self.max_iterations}", style="cyan"),
        ]

        # Add token usage if available
        if self.token_usage["total"] > 0:
            status_parts.extend(
                [
                    Text(" | ", style="dim"),
                    Text(f"Tokens: ", style="bold"),
                    Text(f"{self.token_usage['total']}", style="magenta"),
                ]
            )

        status_line = Text.assemble(*status_parts)

        # Tool line (if executing tool)
        tool_line = None
        if self.current_tool:
            tool_line = Text.assemble(
                Text("Tool: ", style="bold"),
                Text(self.current_tool, style="cyan italic"),
            )

        # Combine lines
        if tool_line:
            content = Group(status_line, tool_line)
        else:
            content = status_line

        return Panel(
            content,
            title="🧠 [bold cyan]ExoBrain Status[/bold cyan]",
            border_style="cyan",
            padding=(0, 1),
        )


class ToolCallDisplay:
    """Display tool calls in a clean, collapsible format."""

    @staticmethod
    def render_tool_call(
        tool_name: str,
        args: dict,
        result: Optional[str] = None,
        collapsed: bool = True,
    ) -> Panel:
        """Render a tool call with optional result.

        Args:
            tool_name: Name of the tool
            args: Tool arguments
            result: Tool execution result (if available)
            collapsed: Whether to show collapsed view
        """
        # Format arguments
        args_text = Text()
        if args:
            for key, value in args.items():
                args_text.append(f"{key}=", style="bold")
                # Truncate long values
                value_str = str(value)
                if len(value_str) > 60:
                    value_str = value_str[:57] + "..."
                args_text.append(f"{value_str}", style="yellow")
                args_text.append(" ")

        # Tool header
        header = Text.assemble(
            Text("🔧 ", style="cyan"),
            Text(tool_name, style="bold cyan"),
            Text(" ", style=""),
            args_text,
        )

        # Result (if available)
        if result:
            # Check if result indicates error
            is_error = "error" in result.lower() or "access denied" in result.lower()
            result_style = "red" if is_error else "green"
            result_icon = "❌" if is_error else "✅"

            if collapsed:
                # Show only first line of result
                first_line = result.split("\n")[0]
                if len(first_line) > 80:
                    first_line = first_line[:77] + "..."
                result_text = Text.assemble(
                    Text(f"{result_icon} ", style=result_style),
                    Text(first_line, style=result_style),
                )
            else:
                # Show full result
                result_text = Text.assemble(
                    Text(
                        f"{result_icon} Result:\n",
                        style=f"bold {result_style}",
                    ),
                    Text(result, style=result_style),
                )

            content = Group(header, result_text)
        else:
            # Tool is executing
            spinner = Spinner("dots", text=Text("Executing...", style="yellow"))
            content = Group(header, spinner)

        return Panel(
            content,
            border_style="cyan" if not result else ("red" if is_error else "green"),
            padding=(0, 1),
            expand=False,
        )

    @staticmethod
    def render_tool_summary(tool_name: str, success: bool, message: str = "") -> Text:
        """Render a one-line summary of a tool call.

        Args:
            tool_name: Name of the tool
            success: Whether the tool succeeded
            message: Brief message about the result
        """
        icon = "✅" if success else "❌"
        style = "green" if success else "red"

        parts = [
            Text(f"{icon} ", style=style),
            Text(tool_name, style=f"bold {style}"),
        ]

        if message:
            parts.append(Text(f" - {message}", style=style))

        return Text.assemble(*parts)


class ConversationDisplay:
    """Display conversation messages with proper formatting."""

    @staticmethod
    def render_user_message(message: str) -> Panel:
        """Render a user message."""
        return Panel(
            Text(message, style="white"),
            title="[bold green]You[/bold green]",
            border_style="green",
            padding=(0, 1),
        )

    @staticmethod
    def render_assistant_message(message: str) -> Panel:
        """Render an assistant message."""
        return Panel(
            Text(message, style="white"),
            title="[bold cyan]Assistant[/bold cyan]",
            border_style="cyan",
            padding=(0, 1),
        )

    @staticmethod
    def render_system_message(message: str) -> Text:
        """Render a system message (info, warnings, etc.)."""
        return Text(f"ℹ️  {message}", style="yellow italic")


class LiveStatusDisplay:
    """Live-updating status display using Rich Live."""

    def __init__(self, console: Console, status_panel: StatusPanel):
        self.console = console
        self.status_panel = status_panel
        self.live: Optional[Live] = None

    def start(self):
        """Start the live display."""
        # If live display is already running, stop it first
        if self.live is not None:
            try:
                self.live.stop()
            except Exception:
                pass  # Ignore errors if it's already stopped
            self.live = None

        # Also check if console has any active live display and clear it
        if hasattr(self.console, "_live") and self.console._live is not None:
            try:
                self.console._live.stop()
                self.console._live = None
            except Exception:
                pass

        self.live = Live(
            self.status_panel.render(),
            console=self.console,
            refresh_per_second=8,
            transient=False,  # Keep status visible
        )
        self.live.start()

    def update(self):
        """Update the live display."""
        if self.live:
            self.live.update(self.status_panel.render())

    def stop(self, final_print: bool = False):
        """Stop the live display."""
        if self.live:
            if final_print:
                # Render one last time so it ends on its own line
                self.live.update(self.status_panel.render(), refresh=True)
            self.live.stop()
            self.live = None


class CLIStatusHandler:
    """Shared status callback handler for CLI (non-TUI) sessions."""

    BUSY_STATES = {
        AgentState.THINKING,
        AgentState.TOOL_CALLING,
        AgentState.WAITING,
        AgentState.STREAMING,
    }

    def __init__(self, console: Console):
        self.console = console
        self.panel = StatusPanel(console)
        self.display = LiveStatusDisplay(console, self.panel)
        self._active = False

    def _ensure_display(self) -> None:
        if not self._active:
            self.display.start()
            self._active = True

    async def __call__(self, state: AgentState, details: dict | None = None) -> None:
        """Update status panel based on agent callbacks."""
        details = details or {}
        self.panel.update(
            state=state,
            iteration=details.get("iteration"),
            tool=details.get("tool"),
        )

        # Inline tool events as chat-like entries
        tool_event = details.get("tool_event")
        if tool_event:
            summary = tool_event.get("summary", "")
            name = tool_event.get("name", "tool")
            is_error = tool_event.get("error", False)
            style = "red" if is_error else "cyan"
            # Limit summary to 3 lines for non-TUI display
            lines = [line.strip() for line in summary.splitlines() if line.strip()]
            summary_compact = "\n".join(lines[:3]) if lines else "(no output)"
            if len(lines) > 3:
                summary_compact += "\n..."
            self.console.print(
                Panel(
                    summary_compact,
                    title=f"[bold]{name}[/bold]",
                    border_style=style,
                    padding=(0, 1),
                )
            )

        if state in self.BUSY_STATES:
            self._ensure_display()
            self.display.update()
        else:
            # Show final state then stop live display
            if self._active:
                self.display.update()
                self.display.stop(final_print=True)
                self._active = False
                self.console.print()
            else:
                # Render once without keeping live display running
                self.console.print()
                self.console.print(self.panel.render())

    def close(self, final_print: bool = False) -> None:
        """Clean up live display if running."""
        if self._active:
            self.display.stop(final_print=final_print)
            self._active = False
