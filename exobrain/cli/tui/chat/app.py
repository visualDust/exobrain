"""Main TUI application for exobrain chat interface."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Callable, Optional

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Label, Static

from exobrain.agent.base import AgentState as CoreAgentState
from exobrain.agent.events import BaseEvent, StateChangedEvent, ToolCompletedEvent
from exobrain.cli.tui.chat.widgets import ChatHistory, InputArea, StatusBar, ToolSidebar
from exobrain.cli.tui.chat.widgets.header import Header, HeaderInfo
from exobrain.cli.tui.chat.widgets.status_bar import AgentState
from exobrain.cli.tui.chat.widgets.tool_sidebar import ToolEvent

if TYPE_CHECKING:
    from exobrain.agent.base import Agent


@dataclass
class ChatAppCallbacks:
    """Callbacks for integrating ChatApp with external systems."""

    on_message: Optional[
        Callable[
            [str, str, Optional[str], Optional[str], Optional[list[dict[str, Any]]], Optional[str]],
            None,
        ]
    ] = None
    on_clear: Optional[Callable[[], None]] = None
    on_exit: Optional[Callable[[], None]] = None
    permission_handler: Optional[Callable[[dict], Any]] = None


@dataclass
class ChatAppConfig:
    """Configuration for ChatApp."""

    title: str = "ExoBrain"
    subtitle: str = ""
    show_welcome: bool = True
    scope: str = "global"
    project_name: Optional[str] = None
    config_path: Optional[str] = None
    working_dir: Optional[str] = None
    model: Optional[str] = None
    constitution: Optional[str] = None
    session_id: Optional[str] = None
    session_name: Optional[str] = None


class PermissionDialog(ModalScreen[tuple[bool, str]]):
    """Modal dialog for permission requests."""

    DEFAULT_CSS = """
    PermissionDialog {
        align: center middle;
    }

    PermissionDialog > Container {
        width: 60;
        height: auto;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    PermissionDialog .title {
        text-align: center;
        text-style: bold;
        color: $warning;
        margin-bottom: 1;
    }

    PermissionDialog .info {
        margin-bottom: 1;
    }

    PermissionDialog .buttons {
        layout: grid;
        grid-size: 2;
        grid-columns: 1fr 1fr;
        grid-gutter: 1 1;
        width: 100%;
        height: auto;
        align: center middle;
        margin-top: 1;
    }

    PermissionDialog .buttons Button {
        width: 100%;
        min-width: 0;
        padding: 0 1;
    }
    """

    def __init__(self, permission_info: dict, **kwargs):
        super().__init__(**kwargs)
        self.permission_info = permission_info

    def compose(self) -> ComposeResult:
        info = self.permission_info
        tool_name = info.get("tool", "Unknown")
        action = info.get("action", "perform action")
        resource = info.get("resource", "")

        with Container():
            yield Label("Permission Required", classes="title")
            yield Static(f"Tool: [bold]{tool_name}[/bold]", classes="info")
            yield Static(f"Action: {action}", classes="info")
            if resource:
                yield Static(f"Resource: [dim]{resource[:50]}[/dim]", classes="info")
            with Container(classes="buttons"):
                yield Button("Yes, once", id="once", variant="primary")
                yield Button("Yes, session", id="session", variant="default")
                yield Button("Yes, always", id="always", variant="success")
                yield Button("No", id="deny", variant="error")

    @on(Button.Pressed)
    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id
        if button_id == "deny":
            self.dismiss((False, "once"))
        elif button_id == "once":
            self.dismiss((True, "once"))
        elif button_id == "session":
            self.dismiss((True, "session"))
        elif button_id == "always":
            self.dismiss((True, "always"))


class ChatApp(App):
    """Main TUI application for chat interface."""

    CSS = """
    Screen {
        layout: vertical;
    }

    #chat-container {
        layout: horizontal;
        height: 1fr;
    }

    ChatHistory {
        height: 1fr;
        width: 1fr;
    }

    StatusBar {
        height: auto;
        min-height: 1;
        max-height: 2;
        background: $surface;
        border-top: solid $primary-darken-2;
    }

    InputArea {
        height: auto;
        min-height: 3;
        max-height: 8;
        background: $surface;
        border-top: solid $primary-darken-1;
    }

    ToolSidebar {
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("ctrl+d", "quit", "Exit"),
        Binding("ctrl+l", "clear", "Clear"),
        Binding("ctrl+c", "cancel", "Cancel", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("ctrl+b", "toggle_sidebar", "Toggle Tools"),
    ]

    def __init__(
        self,
        agent: Optional[Agent] = None,
        message_handler: Optional[Callable[[str], AsyncIterator[str]]] = None,
        callbacks: Optional[ChatAppCallbacks] = None,
        config: Optional[ChatAppConfig] = None,
        initial_history: Optional[list[dict[str, str]]] = None,
        history_truncated: bool = False,
        initial_tool_events: Optional[list[dict[str, str]]] = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._agent = agent
        self._message_handler = message_handler
        self._callbacks = callbacks or ChatAppCallbacks()
        self._config = config or ChatAppConfig()
        self._processing = False
        self._initial_history = initial_history or []
        self._history_truncated = history_truncated
        self._initial_tool_events = initial_tool_events or []

    def compose(self) -> ComposeResult:
        """Compose the application layout."""
        # Build subtitle with scope and model info
        subtitle_parts = []
        if self._config.scope == "project" and self._config.project_name:
            subtitle_parts.append(f"Project: {self._config.project_name}")
        else:
            subtitle_parts.append("Global")
        if self._config.model:
            subtitle_parts.append(self._config.model)
        if self._config.working_dir:
            wd = self._config.working_dir
            if len(wd) > 30:
                wd = "..." + wd[-27:]
            subtitle_parts.append(wd)

        # Create header with info from config
        header_info = HeaderInfo(
            scope=self._config.scope,
            project_name=self._config.project_name,
            config_path=self._config.config_path,
            working_dir=self._config.working_dir,
            model=self._config.model,
            session_id=self._config.session_id,
            session_name=self._config.session_name,
        )
        yield Header(info=header_info)
        with Container(id="chat-container"):
            yield ChatHistory(id="chat-history")
            yield ToolSidebar(id="tool-sidebar", collapsed=False)
        yield StatusBar(id="status-bar")
        yield InputArea(id="input-area")
        yield Footer()

    def on_mount(self) -> None:
        """Handle application mount."""
        # Set title
        self.title = self._config.title

        # Build and set subtitle
        self._update_subtitle()

        # Set model/tool/skill meta in status bar (update in case agent was reattached)
        status_bar = self.query_one("#status-bar", StatusBar)
        model_name = self._config.model
        constitution_name = self._config.constitution
        tool_count = len(self._agent.tool_registry.list_tools()) if self._agent else None
        skill_count = None
        if getattr(self, "_skills_manager", None) and getattr(self._skills_manager, "skills", None):
            skill_count = len(self._skills_manager.skills)
        status_bar.set_meta(
            model=model_name, constitution=constitution_name, tools=tool_count, skills=skill_count
        )

        # Show welcome message
        if self._config.show_welcome:
            self._show_welcome()

        if self._initial_history:
            asyncio.create_task(self._load_initial_history())

        if self._initial_tool_events:
            asyncio.create_task(self._load_initial_tool_events())

        # Focus input
        input_area = self.query_one("#input-area", InputArea)
        input_area.focus_input()

    def _update_subtitle(self) -> None:
        """Update the subtitle with current config."""
        parts = []
        if self._config.scope == "project" and self._config.project_name:
            parts.append(f"[{self._config.project_name}]")
        if self._config.session_name:
            parts.append(f"📝 {self._config.session_name}")
        elif self._config.session_id:
            parts.append(f"#{self._config.session_id[:8]}")
        self.sub_title = " | ".join(parts) if parts else ""

    def _map_agent_state(self, state: CoreAgentState) -> AgentState:
        """Map core AgentState to TUI AgentState."""
        mapping = {
            CoreAgentState.IDLE: AgentState.IDLE,
            CoreAgentState.THINKING: AgentState.THINKING,
            CoreAgentState.TOOL_CALLING: AgentState.TOOL_CALLING,
            CoreAgentState.WAITING: AgentState.WAITING,
            CoreAgentState.STREAMING: AgentState.STREAMING,
            CoreAgentState.ERROR: AgentState.ERROR,
            CoreAgentState.FINISHED: AgentState.FINISHED,
        }
        return mapping.get(state, AgentState.THINKING)

    def _summarize_tool_output(
        self, output: str | None, max_lines: int = 3, max_chars: int = 200
    ) -> str:
        """Compress tool output for inline display without processing entire payload."""
        text = "" if output is None else str(output)
        lines: list[str] = []
        more_content = False

        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            lines.append(stripped)
            if len(lines) >= max_lines:
                more_content = True
                break

        if not lines:
            return ""

        summary = "\n".join(lines)
        if len(summary) > max_chars:
            return summary[: max_chars - 3] + "..."

        if more_content:
            summary += " ..."
        return summary

    async def handle_agent_event(self, event: BaseEvent) -> None:
        """Handle agent events.

        Args:
            event: The event to handle
        """
        if isinstance(event, StateChangedEvent):
            await self._handle_state_change(event)
        elif isinstance(event, ToolCompletedEvent):
            await self._handle_tool_completed(event)

    async def _handle_state_change(self, event: StateChangedEvent) -> None:
        """Handle state change events."""
        # Convert string state back to CoreAgentState enum
        try:
            state = CoreAgentState(event.new_state)
        except ValueError:
            state = CoreAgentState.IDLE

        mapped_state = self._map_agent_state(state)

        status_bar = self.query_one("#status-bar", StatusBar)
        chat_history = self.query_one("#chat-history", ChatHistory)

        status_bar.update_state(
            mapped_state,
            current_tool=event.details.get("tool"),
            iteration=event.iteration,
            error_message=event.details.get("error"),
        )

        # Show/hide thinking indicator based on state
        if state == CoreAgentState.THINKING:
            iteration = event.iteration or 0
            await chat_history.show_thinking(f"Thinking... (iteration {iteration})")
        elif state in (
            CoreAgentState.STREAMING,
            CoreAgentState.TOOL_CALLING,
            CoreAgentState.FINISHED,
        ):
            await chat_history.hide_thinking()

        # Handle thinking blocks (if provided)
        thinking_content = event.details.get("thinking")
        if thinking_content:
            await chat_history.show_thinking_block(thinking_content)
        elif state == CoreAgentState.STREAMING:
            # Hide thinking block when starting to stream response
            await chat_history.hide_thinking_block()

    async def _handle_tool_completed(self, event: ToolCompletedEvent) -> None:
        """Handle tool completed events."""
        if not event.summary:
            return

        summary = self._summarize_tool_output(event.summary)
        is_error = not event.success

        if not summary:
            summary = "(no output)"

        sidebar = self.query_one("#tool-sidebar", ToolSidebar)
        await sidebar.add_event(ToolEvent(name=event.tool_name, summary=summary))

        # Also inline in chat history like a participant with dedicated styling
        chat_history = self.query_one("#chat-history", ChatHistory)
        await chat_history.add_tool_call(event.tool_name, summary, is_error=is_error)

    def set_session(self, session_id: str, session_name: Optional[str] = None) -> None:
        """Update the session info in the header.

        Args:
            session_id: Session ID
            session_name: Optional session name/title
        """
        self._config.session_id = session_id
        self._config.session_name = session_name
        self._update_subtitle()

    async def _show_welcome(self) -> None:
        """Show welcome message in chat history."""
        chat_history = self.query_one("#chat-history", ChatHistory)
        await chat_history.add_message(
            "Welcome to **ExoBrain**. Type `/help` for commands.", role="system"
        )

    async def _load_initial_history(self) -> None:
        """Load previously saved messages into the chat view."""
        chat_history = self.query_one("#chat-history", ChatHistory)
        await chat_history.add_message(
            "Resumed previous conversation (latest messages shown).", role="system"
        )

        for msg in self._initial_history:
            role = msg.get("role", "assistant")
            content = str(msg.get("content", ""))

            if role == "tool":
                tool_name = msg.get("name") or msg.get("tool_call_id") or "tool"
                summary = self._summarize_tool_output(content)
                await chat_history.add_tool_call(tool_name, summary or "(no output)")
            else:
                display_role = role if role in ["user", "assistant", "system"] else "system"
                await chat_history.add_message(content, role=display_role)

        if self._history_truncated:
            await chat_history.add_message("...older messages not shown...", role="system")
        chat_history.scroll_to_bottom()

    async def _load_initial_tool_events(self) -> None:
        """Load saved tool events into sidebar."""
        sidebar = self.query_one("#tool-sidebar", ToolSidebar)
        for event in self._initial_tool_events:
            name = event.get("name", "tool")
            summary = self._summarize_tool_output(event.get("summary", ""))
            await sidebar.add_event(ToolEvent(name, summary))

    @on(InputArea.Submitted)
    async def on_input_submitted(self, event: InputArea.Submitted) -> None:
        """Handle user input submission."""
        if self._processing:
            return

        user_message = event.value.strip()
        if not user_message:
            return

        if user_message.startswith("/"):
            await self._handle_command(user_message[1:].lower())
            return

        chat_history = self.query_one("#chat-history", ChatHistory)
        await chat_history.add_message(user_message, role="user")

        if self._callbacks.on_message:
            # Generate timestamp when user submits message
            timestamp = datetime.now().isoformat()
            self._callbacks.on_message("user", user_message, None, None, None, timestamp)

        self._process_message(user_message)

    async def _handle_command(self, command: str) -> None:
        """Handle slash commands."""
        chat_history = self.query_one("#chat-history", ChatHistory)

        if command in ["exit", "quit"]:
            self.action_quit()
        elif command == "clear":
            await chat_history.clear_history()
            if self._callbacks.on_clear:
                self._callbacks.on_clear()
            if self._agent:
                self._agent.clear_history()
            await chat_history.add_message("History cleared.", role="system")
        elif command == "history":
            if self._agent:
                history_text = self._agent.get_history_text()
                if history_text:
                    await chat_history.add_message(f"**History:**\n\n{history_text}", role="system")
                else:
                    await chat_history.add_message("No history.", role="system")
            else:
                await chat_history.add_message("History not available.", role="system")
        elif command == "help":
            await chat_history.add_message(
                "**Commands:** `/help` `/clear` `/history` `/exit`\n\n"
                "**Keys:** `Ctrl+Enter` Send | `Ctrl+L` Clear | `Ctrl+D` Exit",
                role="system",
            )
        else:
            await chat_history.add_message(f"Unknown: `{command}`", role="system")

    @work(exclusive=True)
    async def _process_message(self, user_message: str) -> None:
        """Process a user message in a background worker."""
        self._processing = True
        status_bar = self.query_one("#status-bar", StatusBar)
        input_area = self.query_one("#input-area", InputArea)
        chat_history = self.query_one("#chat-history", ChatHistory)

        input_area.set_enabled(False)

        # Track conversation history length before processing
        history_len_before = len(self._agent.conversation_history) if self._agent else 0

        try:
            if self._message_handler:
                response_stream = self._message_handler(user_message)
            elif self._agent:
                response_stream = await self._agent.process_message(user_message)
            else:
                response_stream = self._demo_stream(user_message)

            # Hide thinking indicators when starting to stream
            await chat_history.hide_thinking()
            await chat_history.hide_thinking_block()

            await chat_history.start_streaming()

            full_response = ""

            async for chunk in response_stream:
                if chunk.startswith("\n\n[Tool:"):
                    tool_name = self._extract_tool_name(chunk)
                    status_bar.set_tool_calling(tool_name)
                    continue
                elif chunk.startswith("[/Tool]"):
                    continue

                await chat_history.append_to_stream(chunk)
                full_response += chunk

            await chat_history.finalize_streaming()

            # Generate timestamp for assistant response
            assistant_timestamp = datetime.now().isoformat()

            if self._callbacks.on_message and full_response.strip():
                self._callbacks.on_message(
                    "assistant", full_response, None, None, None, assistant_timestamp
                )

            # Save all new messages including tool messages
            if self._agent and self._callbacks.on_message:
                new_messages = self._agent.conversation_history[history_len_before:]
                for msg in new_messages:
                    # Skip user messages as they are already saved
                    # Save assistant messages with tool_calls, and all tool messages
                    if msg.role == "user":
                        continue
                    elif msg.role == "assistant":
                        # Only save assistant messages that have tool_calls
                        # (the final text response was already saved above)
                        if msg.tool_calls:
                            # For assistant messages with tool_calls, content can be None or non-empty
                            # OpenAI API doesn't accept empty string for assistant with tool_calls
                            content = msg.content if msg.content else None
                            self._callbacks.on_message(
                                msg.role,
                                content or "",  # Convert None to "" for storage
                                name=msg.name,
                                tool_call_id=msg.tool_call_id,
                                tool_calls=msg.tool_calls,
                                timestamp=msg.timestamp,
                            )
                    else:
                        # Save tool and other message types with full metadata
                        self._callbacks.on_message(
                            msg.role,
                            msg.content or "",
                            name=msg.name,
                            tool_call_id=msg.tool_call_id,
                            tool_calls=None,
                            timestamp=msg.timestamp,
                        )

            await asyncio.sleep(0.3)
            status_bar.set_idle()

        except asyncio.CancelledError:
            await chat_history.finalize_streaming()
            status_bar.set_idle()

        except Exception as e:
            status_bar.set_error(str(e))
            await chat_history.finalize_streaming()
            await chat_history.add_message(f"Error: {e}", role="system")

        finally:
            self._processing = False
            input_area.set_enabled(True)
            input_area.focus_input()

    def _extract_tool_name(self, chunk: str) -> str:
        """Extract tool name from a tool call chunk."""
        try:
            if "[Tool:" in chunk and "]" in chunk:
                return chunk.split("[Tool:")[1].split("]")[0].strip()
        except (IndexError, ValueError):
            pass
        return "unknown"

    async def _demo_stream(self, user_message: str) -> AsyncIterator[str]:
        """Demo streaming response generator."""
        response = f"""I received: "{user_message}"

This is a **demo response** showing streaming.

Features:
- Real-time streaming
- Markdown support
- Status bar updates"""
        words = response.split(" ")
        for i, word in enumerate(words):
            yield word + " "
            await asyncio.sleep(0.02 + (0.03 if i % 5 == 0 else 0))

    async def request_permission(self, permission_info: dict) -> tuple[bool, str]:
        """Request permission from user via modal dialog."""
        return await self.push_screen_wait(PermissionDialog(permission_info))

    def action_quit(self) -> None:
        """Quit the application."""
        if self._callbacks.on_exit:
            self._callbacks.on_exit()
        self.exit()

    def action_clear(self) -> None:
        """Clear the chat history."""
        chat_history = self.query_one("#chat-history", ChatHistory)

        async def do_clear():
            await chat_history.clear_history()
            if self._callbacks.on_clear:
                self._callbacks.on_clear()
            if self._agent:
                self._agent.clear_history()

        self.call_later(do_clear)

    def action_cancel(self) -> None:
        """Cancel current operation."""
        if self._processing:
            self.workers.cancel_all()

    def action_toggle_sidebar(self) -> None:
        """Toggle tool sidebar visibility."""
        sidebar = self.query_one("#tool-sidebar", ToolSidebar)
        sidebar.toggle()


async def run_chat_app(
    agent: Optional[Agent] = None,
    message_handler: Optional[Callable[[str], AsyncIterator[str]]] = None,
    callbacks: Optional[ChatAppCallbacks] = None,
    config: Optional[ChatAppConfig] = None,
) -> None:
    """Run the chat TUI application."""
    app = ChatApp(
        agent=agent,
        message_handler=message_handler,
        callbacks=callbacks,
        config=config,
    )
    await app.run_async()
