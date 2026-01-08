"""Chat and ask commands for ExoBrain CLI."""

import asyncio
import logging
from typing import Any

import click
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt

from exobrain.agent.core import Agent
from exobrain.cli.chat_permissions import request_permission, update_permission
from exobrain.cli.chat_ui import CLIStatusHandler, ToolCallDisplay
from exobrain.config import Config

console = Console()
logger = logging.getLogger(__name__)


def _prepare_history_preview(
    messages: list[dict[str, Any]],
    max_messages: int = 8,
    max_chars: int = 800,
) -> tuple[list[dict[str, str]], bool]:
    """Trim stored messages for preview.

    Returns a list of role/content pairs and whether anything was truncated.
    """
    if not messages:
        return [], False

    trimmed_messages = messages[-max_messages:]
    truncated = len(messages) > max_messages

    preview: list[dict[str, str]] = []
    for msg in trimmed_messages:
        role = msg.get("role", "assistant")
        content = str(msg.get("content", ""))
        if len(content) > max_chars:
            content = content[: max_chars - 3] + "..."
            truncated = True
        preview.append({"role": role, "content": content})

    return preview, truncated


def _render_history_preview(
    console: Console, preview: list[dict[str, str]], truncated: bool
) -> None:
    """Render a brief history preview to the console."""
    if not preview:
        return

    role_labels = {
        "user": "You",
        "assistant": "Assistant",
        "system": "System",
        "tool": "Tool",
    }

    lines = []
    for msg in preview:
        role = msg.get("role", "assistant")
        label = role_labels.get(role, role.title())
        content = msg.get("content", "")
        lines.append(f"[bold]{label}[/bold]: {content}")

    if truncated:
        lines.append("[dim]...older messages not shown[/dim]")

    console.print(
        Panel(
            "\n\n".join(lines),
            title="Previous conversation",
            border_style="blue",
            padding=(1, 2),
        )
    )


def _summarize_text(text: str, max_lines: int = 3, max_chars: int = 200) -> str:
    """Produce a brief summary of text for UI cards."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    summary = "\n".join(lines[:max_lines])
    if len(summary) > max_chars:
        summary = summary[: max_chars - 3] + "..."
    elif len(lines) > max_lines:
        summary += " ..."
    return summary


def _extract_tool_events(
    messages: list[dict[str, Any]], max_events: int = 30
) -> list[dict[str, str]]:
    """Extract recent tool events from stored messages."""
    events: list[dict[str, str]] = []
    for msg in messages:
        if msg.get("role") != "tool":
            continue
        name = msg.get("name") or msg.get("tool_call_id") or "tool"
        content = str(msg.get("content", ""))
        events.append({"name": name, "summary": _summarize_text(content)})
    # Keep only most recent events
    if len(events) > max_events:
        events = events[-max_events:]
    return events


async def run_streaming_chat(
    agent: Agent, user_input: str, console: Console, render_markdown: bool = False
) -> None:
    """Run streaming chat with enhanced UI.

    Args:
        agent: The agent instance
        user_input: User's message
        console: Rich console for output
        render_markdown: Whether to render the final assistant reply as Markdown
    """
    # Buffer for collecting tool output
    current_tool_output = []
    current_tool_name = None
    in_tool_section = False
    assistant_response = ""

    # Clear the "(generating...)" indicator and start output
    console.print("\r[bold cyan]Assistant[/bold cyan] [dim](thinking...)[/dim]")
    live: Live | None = None

    # Temporarily disable status handler's live display if using markdown
    status_handler = agent.status_callback if hasattr(agent, "status_callback") else None
    original_ensure_display = None
    if render_markdown and status_handler and hasattr(status_handler, "_ensure_display"):
        # Save original method and replace with no-op to prevent live display conflicts
        original_ensure_display = status_handler._ensure_display
        status_handler._ensure_display = lambda: None

    if render_markdown:
        live = Live(Markdown(""), console=console, refresh_per_second=8, transient=False)
        live.start()

    # Process message
    response_stream = await agent.process_message(user_input)

    try:
        async for chunk in response_stream:
            # Detect tool call start
            if chunk.startswith("\n\n[Tool:"):
                # Start collecting tool output
                in_tool_section = True
                current_tool_output = [chunk]

                # Extract tool name
                if "]" in chunk:
                    tool_name = chunk.split("[Tool:")[1].split("]")[0].strip()
                    current_tool_name = tool_name
                continue

            if in_tool_section:
                # Collecting tool output
                current_tool_output.append(chunk)

                # Check if we've moved past tool output (assistant starts responding)
                # Tool output ends when we see content that's NOT part of the tool format
                if (
                    not chunk.startswith("\n")
                    and not chunk.startswith("[")
                    and len(current_tool_output) > 3
                ):
                    # We've moved to assistant response, render the tool output
                    full_output = "".join(current_tool_output[:-1])  # Exclude current chunk

                    # Parse tool output
                    lines = [line.strip() for line in full_output.split("\n") if line.strip()]
                    first_line = lines[0] if lines else ""
                    summary_text = first_line[:180] + ("..." if len(first_line) > 180 else "")
                    if len(lines) > 1 and len(summary_text) < 120:
                        summary_text += " " + lines[1][: 120 - len(summary_text)]

                    success = "Exit code: 0" in full_output or "Successfully" in full_output
                    is_error = (
                        "Access denied" in full_output
                        or "Error" in full_output
                        or ("Exit code:" in full_output and "Exit code: 0" not in full_output)
                    )

                    # Show collapsible tool call
                    if is_error:
                        # Show full error
                        if live:
                            live.stop()
                            live = None
                        console.print(full_output, style="red dim")
                    else:
                        # Show compact success with richer summary
                        summary = ToolCallDisplay.render_tool_summary(
                            current_tool_name,
                            success=True,
                            message=summary_text or "completed",
                        )
                        if live:
                            live.console.print(summary)
                        else:
                            console.print(summary)

                    # Reset tool section
                    in_tool_section = False
                    current_tool_output = []
                    current_tool_name = None

                    # Don't continue - process this chunk as assistant response below
                else:
                    continue  # Still collecting tool output

            # Regular assistant response
            if not chunk.startswith("\n\n[Tool:"):
                assistant_response += chunk
                if render_markdown and live:
                    live.update(Markdown(assistant_response))
                else:
                    console.print(chunk, end="")

    except KeyboardInterrupt:
        if live:
            live.stop()
        console.print("\n\n[yellow]Response generation interrupted.[/yellow]")
        return

    # Final rendering and completion indicator
    if live:
        live.stop()
        # Live already displayed the content, just show completion
        if assistant_response:
            console.print()
            console.print("[dim]✓ Response complete[/dim]")
    else:
        # Non-markdown streaming already printed content inline
        if assistant_response:
            console.print()
            console.print("[dim]✓ Response complete[/dim]")

    # Restore original _ensure_display method if we replaced it
    if original_ensure_display and status_handler:
        status_handler._ensure_display = original_ensure_display


async def run_chat_session(
    agent: Agent,
    config: Config,
    session_mode: dict[str, Any] | None = None,
    skills_manager: Any | None = None,
) -> None:
    """Run an interactive chat session.

    Args:
        agent: The agent instance
        config: Application configuration
        session_mode: Session management options (continue, session_id, new)
    """
    from pathlib import Path

    from exobrain.memory.conversations import ConversationManager
    from exobrain.memory.loader import TokenBudgetCalculator, format_load_stats
    from exobrain.providers.base import Message

    # Initialize session mode if not provided
    if session_mode is None:
        session_mode = {
            "continue": False,
            "session_id": None,
            "new": False,
            "use_project": False,
            "use_global": False,
        }

    # Determine conversation storage path
    project_exobrain_dir = Path.cwd() / ".exobrain"
    project_conversations_path = project_exobrain_dir / "conversations"
    user_data_dir = Path.home() / ".exobrain" / "data"
    global_conversations_path = user_data_dir / "conversations"

    # Initialize default values
    conversations_path = global_conversations_path
    storage_type = "global"

    # Handle explicit storage preference
    if session_mode.get("use_project"):
        # User explicitly requested project-level storage
        if not project_exobrain_dir.exists():
            console.print(f"[yellow]Project-level .exobrain directory does not exist.[/yellow]")
            from rich.prompt import Confirm

            if Confirm.ask(f"Create .exobrain directory in {Path.cwd()}?", default=True):
                project_exobrain_dir.mkdir(parents=True, exist_ok=True)
                console.print(f"[green]Created {project_exobrain_dir}[/green]")
                conversations_path = project_conversations_path
                storage_type = "project"
            else:
                console.print("[yellow]Using global storage instead.[/yellow]")
                conversations_path = global_conversations_path
                storage_type = "global"
        else:
            conversations_path = project_conversations_path
            storage_type = "project"
    elif session_mode.get("use_global"):
        # User explicitly requested global storage
        conversations_path = global_conversations_path
        storage_type = "global"
    else:
        # Auto-detect: prefer project-level if exists
        if project_exobrain_dir.exists():
            conversations_path = project_conversations_path
            storage_type = "project"
        else:
            conversations_path = global_conversations_path
            storage_type = "global"

    logger.debug(f"Using {storage_type} conversations storage: {conversations_path}")

    # Initialize conversation manager
    conversation_manager = ConversationManager(
        storage_path=conversations_path,
        model_provider=agent.model_provider,
        save_tool_history=config.memory.save_tool_history,
        tool_content_max_length=config.memory.tool_content_max_length,
    )

    # Initialize token budget calculator
    token_calculator = TokenBudgetCalculator(model_provider=agent.model_provider, config=config)

    # Determine which session to use
    current_session_id = None
    is_new_session = False
    history_preview: list[dict[str, str]] = []
    history_truncated = False
    initial_tool_events: list[dict[str, str]] = []

    if session_mode.get("session_id"):
        # Resume specific session
        session_id = session_mode["session_id"]
        try:
            # Calculate token budget for loading
            budget = token_calculator.calculate_budget()

            # Load session with budget
            session_data = conversation_manager.load_session(session_id, budget)
            current_session_id = session_id
            history_preview, history_truncated = _prepare_history_preview(session_data["messages"])
            first_user_message = False
            initial_tool_events = _extract_tool_events(session_data["messages"])

            # Restore conversation history to agent
            for msg_data in session_data["messages"]:
                msg = Message(
                    role=msg_data["role"],
                    content=msg_data["content"],
                    name=msg_data.get("name"),
                    tool_calls=msg_data.get("tool_calls"),
                    tool_call_id=msg_data.get("tool_call_id"),
                )
                agent.add_message(msg)

            # Show session info
            console.print(
                f"[cyan]ℹ[/cyan] Resumed session [bold]{session_id}[/bold]: "
                f"{format_load_stats(session_data['stats'])}"
            )
        except ValueError as e:
            console.print(f"[red]Error: {e}[/red]")
            console.print("[yellow]Starting new session instead.[/yellow]")
            is_new_session = True
    elif session_mode.get("continue"):
        # Continue last session - check both project and global, prefer project
        last_session = None
        session_source = None

        # If user didn't specify storage preference, check both locations
        if not session_mode.get("use_project") and not session_mode.get("use_global"):
            # Try project-level first if it exists
            if project_exobrain_dir.exists():
                project_manager = ConversationManager(
                    storage_path=project_conversations_path,
                    model_provider=agent.model_provider,
                    save_tool_history=config.memory.save_tool_history,
                    tool_content_max_length=config.memory.tool_content_max_length,
                )
                project_session = project_manager.get_current_session()

                # Also check global
                global_manager = ConversationManager(
                    storage_path=global_conversations_path,
                    model_provider=agent.model_provider,
                    save_tool_history=config.memory.save_tool_history,
                    tool_content_max_length=config.memory.tool_content_max_length,
                )
                global_session = global_manager.get_current_session()

                # Prefer project session if it exists
                if project_session:
                    last_session = project_session
                    session_source = "project"
                    conversation_manager = project_manager
                    conversations_path = project_conversations_path
                elif global_session:
                    last_session = global_session
                    session_source = "global"
                    conversation_manager = global_manager
                    conversations_path = global_conversations_path
            else:
                # Only global exists
                last_session = conversation_manager.get_current_session()
                session_source = "global"
        else:
            # User specified preference, use the selected manager
            last_session = conversation_manager.get_current_session()
            session_source = storage_type

        if last_session:
            try:
                # Calculate token budget
                budget = token_calculator.calculate_budget()

                # Load session
                session_data = conversation_manager.load_session(last_session, budget)
                current_session_id = last_session
                history_preview, history_truncated = _prepare_history_preview(
                    session_data["messages"]
                )
                first_user_message = False
                initial_tool_events = _extract_tool_events(session_data["messages"])

                # Restore conversation history
                for msg_data in session_data["messages"]:
                    msg = Message(
                        role=msg_data["role"],
                        content=msg_data["content"],
                        name=msg_data.get("name"),
                        tool_calls=msg_data.get("tool_calls"),
                        tool_call_id=msg_data.get("tool_call_id"),
                    )
                    agent.add_message(msg)

                # Show session info
                console.print(
                    f"[cyan]ℹ[/cyan] Continuing {session_source} session [bold]{last_session}[/bold]: "
                    f"{format_load_stats(session_data['stats'])}"
                )
            except Exception as e:
                console.print(f"[red]Error loading session: {e}[/red]")
                console.print("[yellow]Starting new session instead.[/yellow]")
                is_new_session = True
        else:
            console.print("[yellow]No previous session found. Starting new session.[/yellow]")
            is_new_session = True
    else:
        # New session (default or explicit --new)
        is_new_session = True

    # Don't create new session immediately - wait for first message (lazy creation)
    # This prevents empty sessions when user exits without sending any messages
    if is_new_session or current_session_id is None:
        # Mark that we need to create a session on first message
        current_session_id = None
        is_new_session = True

    # Track if this is the first user message (for auto-title generation and session creation)
    first_user_message = True

    # Build session scope info
    scope_icon = "📁" if storage_type == "project" else "🏠"
    scope_label = f"Project {Path.cwd().name[:10]}" if storage_type == "project" else "User"
    scope_info = f"[dim]{scope_icon} Session scope: {scope_label}[/dim]"
    model_info = (
        f"[dim]Model: {agent.model_provider.model}[/dim]" if agent and agent.model_provider else ""
    )
    constitution_info = ""
    if config and hasattr(config, "agent") and hasattr(config.agent, "constitution_file"):
        constitution_name = config.agent.constitution_file or "builtin-default"
        constitution_info = f"[dim]Constitution: {constitution_name}[/dim]"
    tool_info = ""
    if agent and agent.tool_registry:
        tool_count = len(agent.tool_registry.list_tools())
        tool_info = f"[dim]Tools loaded: {tool_count}[/dim]"
    skills_info = ""
    if skills_manager and getattr(skills_manager, "skills", None):
        skills_info = f"[dim]Skills loaded: {len(skills_manager.skills)}[/dim]"

    console.print(
        Panel.fit(
            "[bold cyan]ExoBrain[/bold cyan]\n"
            "Your personal AI assistant\n\n"
            f"{scope_info}\n"
            f"{model_info}\n"
            f"{constitution_info}\n"
            f"{tool_info}\n"
            f"{skills_info}\n\n"
            "Commands:\n"
            "  /help         - Show this help message\n"
            "  /clear        - Clear conversation history\n"
            "  /history      - Show conversation history\n"
            "  /exit, /quit  - Exit the chat\n\n"
            "Shortcuts:\n"
            "  Ctrl+D        - Exit the chat\n"
            "  Ctrl+C        - Cancel current input",
            title="Welcome",
            border_style="cyan",
        )
    )

    if history_preview and (session_mode.get("continue") or session_mode.get("session_id")):
        _render_history_preview(console, history_preview, history_truncated)

    # Create status handler first
    status_handler = CLIStatusHandler(console)

    # Setup permission callback
    async def permission_handler(denied_info: dict[str, Any]) -> bool:
        """Handle permission requests from agent."""
        # Stop live display to avoid interfering with user input
        status_handler.close(final_print=False)

        granted, scope = await request_permission(denied_info, console)

        if granted and scope != "once":
            # Update permissions for session or always
            update_permission(denied_info, scope, agent, config)

        return granted

    agent.permission_callback = permission_handler
    # Share status updates with the TUI
    agent.status_callback = status_handler

    while True:
        try:
            # Visual separator before input
            console.print("\n" + "─" * 80)
            # Get user input
            user_input = Prompt.ask("[bold green]You[/bold green]")
        except EOFError:
            # Handle Ctrl+D
            console.print("\n[yellow]Goodbye![/yellow]")
            break
        except KeyboardInterrupt:
            # Handle Ctrl+C
            console.print("\n[yellow]Input cancelled. Type /exit or press Ctrl+D to quit.[/yellow]")
            continue

        try:
            if not user_input.strip():
                continue

            # Visual separator after input
            console.print("─" * 80)

            # Handle commands
            if user_input.startswith("/"):
                command = user_input[1:].lower().strip()

                if command in ["exit", "quit"]:
                    console.print("[yellow]Goodbye![/yellow]")
                    break
                elif command == "clear":
                    agent.clear_history()
                    # Mark for new session creation on next message (lazy)
                    current_session_id = None
                    first_user_message = True
                    console.print("[yellow]Conversation history cleared.[/yellow]")
                    continue
                elif command == "history":
                    history = agent.get_history_text()
                    if history:
                        console.print(
                            Panel(
                                history,
                                title="Conversation History",
                                border_style="blue",
                            )
                        )
                    else:
                        console.print("[yellow]No conversation history.[/yellow]")
                    continue
                elif command == "help":
                    console.print(
                        Panel.fit(
                            "Commands:\n"
                            "  /help         - Show this help message\n"
                            "  /clear        - Clear conversation history\n"
                            "  /history      - Show conversation history\n"
                            "  /exit, /quit  - Exit the chat\n\n"
                            "Shortcuts:\n"
                            "  Ctrl+D        - Exit the chat\n"
                            "  Ctrl+C        - Cancel current input or interrupt response",
                            title="Help",
                            border_style="cyan",
                        )
                    )
                    continue
                else:
                    console.print(f"[red]Unknown command: {command}[/red]")
                    continue

            # Track history length before processing
            history_len_before = len(agent.conversation_history)

            # Show assistant header and processing indicator
            console.print("\n[bold cyan]Assistant[/bold cyan] [dim](thinking...)[/dim]")

            # Process message with agent
            if agent.stream:
                # Streaming mode with enhanced UI
                await run_streaming_chat(
                    agent,
                    user_input,
                    console,
                    render_markdown=config.cli.render_markdown,
                )
            else:
                # Non-streaming mode
                # Clear the "(generating...)" indicator
                console.print("\r[bold cyan]Assistant[/bold cyan] [dim](thinking...)[/dim]")

                response = await agent.process_message(user_input)

                if config.cli.render_markdown and response:
                    console.print(
                        Panel(
                            Markdown(response),
                            border_style="cyan",
                            padding=(1, 2),
                        )
                    )
                    console.print()  # Spacer before status panel
                else:
                    console.print(response)
                    console.print()  # Ensure trailing newline before status output

                # Show completion indicator
                console.print("[dim]✓ Response complete[/dim]")

            # Get new messages from agent's conversation history
            new_messages = agent.conversation_history[history_len_before:]

            # Create session lazily on first message (if not already created)
            if current_session_id is None and new_messages:
                model_name = agent.model_provider.model
                current_session_id = conversation_manager.create_session(model=model_name)

                # Determine storage type for display
                if conversations_path == project_conversations_path:
                    storage_display = "project"
                else:
                    storage_display = "global"

                logger.debug(
                    f"Created new {storage_display} session on first message: {current_session_id}"
                )

            # Save new messages to conversation manager
            if current_session_id:  # Only save if we have a session
                for msg in new_messages:
                    conversation_manager.save_message(current_session_id, msg)

                # Auto-generate title from first user message
                if first_user_message and new_messages:
                    # Find the user message (should be first in new_messages)
                    for msg in new_messages:
                        if msg.role == "user" and msg.content:
                            conversation_manager.auto_generate_title(
                                current_session_id, msg.content
                            )
                            first_user_message = False
                            break

            # Show token usage if enabled
            if config.cli.show_token_usage:
                # This would need to be implemented in the agent
                pass

        except KeyboardInterrupt:
            console.print("\n[yellow]Input cancelled. Type /exit or press Ctrl+D to quit.[/yellow]")
            continue
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            logger.exception("Error in chat session")

    status_handler.close(final_print=True)


async def run_tui_chat_session(
    agent: Agent,
    config: Config,
    session_mode: dict[str, Any] | None = None,
    skills_manager: Any | None = None,
) -> None:
    """Run an interactive TUI chat session.

    Args:
        agent: The agent instance
        config: Application configuration
        session_mode: Session management options (continue, session_id, new)
    """
    from pathlib import Path

    from exobrain.cli.tui.app import ChatApp, ChatAppCallbacks, ChatAppConfig
    from exobrain.memory.conversations import ConversationManager
    from exobrain.memory.loader import TokenBudgetCalculator, format_load_stats
    from exobrain.providers.base import Message

    # Initialize session mode if not provided
    if session_mode is None:
        session_mode = {
            "continue": False,
            "session_id": None,
            "new": False,
            "use_project": False,
            "use_global": False,
        }

    # Determine conversation storage path (same logic as run_chat_session)
    project_exobrain_dir = Path.cwd() / ".exobrain"
    project_conversations_path = project_exobrain_dir / "conversations"
    user_data_dir = Path.home() / ".exobrain" / "data"
    global_conversations_path = user_data_dir / "conversations"

    conversations_path = global_conversations_path
    storage_type = "global"

    if session_mode.get("use_project"):
        if project_exobrain_dir.exists():
            conversations_path = project_conversations_path
            storage_type = "project"
        else:
            # For TUI, we'll create the directory automatically
            project_exobrain_dir.mkdir(parents=True, exist_ok=True)
            conversations_path = project_conversations_path
            storage_type = "project"
    elif session_mode.get("use_global"):
        conversations_path = global_conversations_path
        storage_type = "global"
    else:
        if project_exobrain_dir.exists():
            conversations_path = project_conversations_path
            storage_type = "project"
        else:
            conversations_path = global_conversations_path
            storage_type = "global"

    logger.debug(f"TUI using {storage_type} conversations storage: {conversations_path}")

    # Initialize conversation manager
    conversation_manager = ConversationManager(
        storage_path=conversations_path,
        model_provider=agent.model_provider,
        save_tool_history=config.memory.save_tool_history,
        tool_content_max_length=config.memory.tool_content_max_length,
    )

    # Initialize token budget calculator
    token_calculator = TokenBudgetCalculator(model_provider=agent.model_provider, config=config)

    # Session management variables
    current_session_id = None
    first_user_message = True
    history_preview: list[dict[str, str]] = []
    history_truncated = False
    initial_tool_events: list[dict[str, str]] = []

    # Handle session continuation
    if session_mode.get("session_id"):
        session_id = session_mode["session_id"]
        try:
            budget = token_calculator.calculate_budget()
            session_data = conversation_manager.load_session(session_id, budget)
            current_session_id = session_id
            history_preview, history_truncated = _prepare_history_preview(session_data["messages"])
            first_user_message = False
            initial_tool_events = _extract_tool_events(session_data["messages"])

            for msg_data in session_data["messages"]:
                msg = Message(
                    role=msg_data["role"],
                    content=msg_data["content"],
                    name=msg_data.get("name"),
                    tool_calls=msg_data.get("tool_calls"),
                    tool_call_id=msg_data.get("tool_call_id"),
                )
                agent.add_message(msg)

            logger.info(f"Resumed session {session_id}: {format_load_stats(session_data['stats'])}")
        except ValueError as e:
            logger.warning(f"Could not load session {session_id}: {e}")

    elif session_mode.get("continue"):
        last_session = conversation_manager.get_current_session()
        if last_session:
            try:
                budget = token_calculator.calculate_budget()
                session_data = conversation_manager.load_session(last_session, budget)
                current_session_id = last_session
                history_preview, history_truncated = _prepare_history_preview(
                    session_data["messages"]
                )

                for msg_data in session_data["messages"]:
                    msg = Message(
                        role=msg_data["role"],
                        content=msg_data["content"],
                        name=msg_data.get("name"),
                        tool_calls=msg_data.get("tool_calls"),
                        tool_call_id=msg_data.get("tool_call_id"),
                    )
                    agent.add_message(msg)

                logger.debug(
                    f"Continuing session {last_session}: {format_load_stats(session_data['stats'])}"
                )
                first_user_message = False
                initial_tool_events = _extract_tool_events(session_data["messages"])
            except Exception as e:
                logger.warning(f"Could not continue session: {e}")

    # Get config path for display
    config_path = None
    if hasattr(config, "_config_path"):
        config_path = str(config._config_path)
    elif project_exobrain_dir.exists():
        project_config = project_exobrain_dir / "config.yaml"
        if project_config.exists():
            config_path = str(project_config)

    # Get session name if resuming
    session_name = None
    if current_session_id:
        session_info = conversation_manager.get_session_metadata(current_session_id)
        if session_info:
            session_name = session_info.get("title")

    # Create app config
    constitution_name = None
    if config and hasattr(config, "agent") and hasattr(config.agent, "constitution_file"):
        constitution_name = config.agent.constitution_file or "builtin-default"

    app_config = ChatAppConfig(
        title="ExoBrain 🧠",
        subtitle="AI Assistant",
        show_welcome=True,
        scope=storage_type,
        project_name=Path.cwd().name if storage_type == "project" else None,
        config_path=config_path,
        working_dir=str(Path.cwd()),
        model=agent.model_provider.model if agent.model_provider else None,
        constitution=constitution_name,
        session_id=current_session_id,
        session_name=session_name,
    )

    # Create app first so callbacks can reference it
    app = ChatApp(
        agent=agent,
        config=app_config,
        initial_history=history_preview,
        history_truncated=history_truncated,
        initial_tool_events=initial_tool_events,
    )
    # Store skills manager for header counts
    app._skills_manager = skills_manager

    # Setup permission callback now that the app exists
    async def permission_handler(denied_info: dict[str, Any]) -> bool:
        """Handle permission requests from agent using the TUI modal."""
        granted, scope = await app.request_permission(denied_info)

        if granted and scope != "once":
            update_permission(denied_info, scope, agent, config)

        return granted

    agent.permission_callback = permission_handler
    agent.status_callback = app.handle_agent_status

    # Callback to save messages
    def on_message(
        role: str,
        content: str,
        name: str | None = None,
        tool_call_id: str | None = None,
        timestamp: str | None = None,
    ) -> None:
        nonlocal current_session_id, first_user_message

        # Create session on first user message
        if current_session_id is None and role == "user":
            model_name = agent.model_provider.model
            current_session_id = conversation_manager.create_session(model=model_name)
            logger.debug(f"Created new {storage_type} session: {current_session_id}")
            # Update header with new session ID
            app.set_session(current_session_id)

        # Save message
        if current_session_id:
            msg = Message(
                role=role,
                content=content,
                name=name,
                tool_call_id=tool_call_id,
                timestamp=timestamp,
            )
            conversation_manager.save_message(current_session_id, msg)

            # Auto-generate title from first user message
            if first_user_message and role == "user":
                title = conversation_manager.auto_generate_title(current_session_id, content)
                first_user_message = False
                # Update header with session title
                app.set_session(current_session_id, title)

    def on_clear() -> None:
        nonlocal current_session_id, first_user_message
        current_session_id = None
        first_user_message = True
        # Clear session from header
        app.set_session("", None)

    # Set callbacks
    app._callbacks = ChatAppCallbacks(
        on_message=on_message,
        on_clear=on_clear,
    )

    await app.run_async()


@click.command()
@click.option(
    "--model",
    help="Model to use (e.g., openai/gpt-4o, gemini/gemini-pro, local/Qwen3-30B)",
)
@click.option("--no-stream", is_flag=True, help="Disable streaming")
@click.option("--no-skills", is_flag=True, help="Disable skills")
@click.option(
    "-c",
    "--continue",
    "continue_session",
    is_flag=True,
    help="Continue last session",
)
@click.option("-s", "--session", "session_id", help="Resume a specific session by ID")
@click.option(
    "-n",
    "--new",
    "new_session",
    is_flag=True,
    help="Force create a new session",
)
@click.option(
    "-p",
    "--project",
    "use_project",
    is_flag=True,
    help="Use project-level storage (.exobrain/)",
)
@click.option(
    "-g",
    "--global",
    "use_global",
    is_flag=True,
    help="Use global user storage",
)
@click.option(
    "--no-tui",
    "use_tui",
    is_flag=True,
    default=False,
    help="Disable TUI and use plain CLI mode",
)
@click.pass_context
def chat(
    ctx: click.Context,
    model: str | None,
    no_stream: bool,
    no_skills: bool,
    continue_session: bool,
    session_id: str | None,
    new_session: bool,
    use_project: bool,
    use_global: bool,
    use_tui: bool,
) -> None:
    """Start an interactive chat session.

    Examples:
        exobrain chat                    # Start new or continue based on config (non-TUI)
        exobrain chat --continue         # Continue last session (project-level priority)
        exobrain chat --session <ID>     # Resume specific session
        exobrain chat --new              # Force new session
        exobrain chat --new --project    # Create new project-level session
        exobrain chat --new --global     # Create new global session
        exobrain chat --model openai/gpt-4o
        exobrain chat --tui              # Use experimental TUI
    """
    config: Config = ctx.obj["config"]

    # Override stream setting if requested
    if no_stream:
        config.agent.stream = False

    try:
        # Create agent
        agent, skills_manager = create_agent_from_config(config, model, enable_skills=not no_skills)

        # Validate storage options
        if use_project and use_global:
            console.print("[red]Error: Cannot use both --project and --global options[/red]")
            ctx.exit(1)

        # Determine session behavior
        session_mode = {
            "continue": continue_session,
            "session_id": session_id,
            "new": new_session,
            "use_project": use_project,
            "use_global": use_global,
        }

        # Run chat session - default to TUI; allow fallback with --no-tui
        if use_tui:
            asyncio.run(run_chat_session(agent, config, session_mode, skills_manager))
        else:
            asyncio.run(run_tui_chat_session(agent, config, session_mode, skills_manager))

    except Exception as e:
        console.print(f"[red]Error starting chat: {e}[/red]")
        logger.exception("Error starting chat")
        ctx.exit(1)


@click.command()
@click.argument("query")
@click.option(
    "--model",
    help="Model to use (e.g., openai/gpt-4o, gemini/gemini-pro, local/Qwen3-30B)",
)
@click.option("--no-skills", is_flag=True, help="Disable skills")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed tool execution info")
@click.pass_context
def ask(
    ctx: click.Context,
    query: str,
    model: str | None,
    no_skills: bool,
    verbose: bool,
) -> None:
    """Ask a single question.

    Examples:
        exobrain ask "What is AI?"
        exobrain ask --model openai/gpt-4o "Explain quantum computing"
        exobrain ask --model gemini/gemini-pro --no-skills "Hello"
    """
    config: Config = ctx.obj["config"]

    try:
        # Create agent
        agent, skills_manager = create_agent_from_config(config, model, enable_skills=not no_skills)

        # Set verbose mode if requested
        agent.verbose = verbose

        # Set up permission handler for ask command
        from exobrain.cli.chat_permissions import request_permission, update_permission

        # Store live display reference to stop it during permission requests
        current_live: dict[str, Live | None] = {"live": None}

        async def permission_handler(denied_info: dict[str, Any]) -> bool:
            """Handle permission requests from agent."""
            # Stop live display if running to avoid interfering with user input
            if current_live["live"]:
                try:
                    current_live["live"].stop()
                    current_live["live"] = None
                except Exception:
                    pass

            granted, scope = await request_permission(denied_info, console)

            if granted and scope != "once":
                # Update permissions for session or always
                update_permission(denied_info, scope, agent, config)

            return granted

        agent.permission_callback = permission_handler

        # Process query
        async def process() -> None:
            response = await agent.process_message(query)

            if isinstance(response, str):
                if config.cli.render_markdown:
                    console.print(Markdown(response))
                else:
                    console.print(response)
            else:
                # Streaming
                assistant_response = ""
                live: Live | None = None
                try:
                    if config.cli.render_markdown:
                        live = Live(
                            Markdown(""), console=console, refresh_per_second=8, transient=False
                        )
                        current_live["live"] = live
                        live.start()

                    async for chunk in response:
                        assistant_response += chunk
                        if live:
                            live.update(Markdown(assistant_response))
                        else:
                            console.print(chunk, end="")
                finally:
                    if live:
                        live.stop()
                        current_live["live"] = None

                # Only print newline if not using Live (Live already shows the content)
                if not live:
                    console.print()

        asyncio.run(process())

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        logger.exception("Error processing query")
        ctx.exit(1)
