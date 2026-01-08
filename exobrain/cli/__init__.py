"""CLI entry point for ExoBrain."""

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

import click
import yaml
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from exobrain.agent.core import Agent
from exobrain.cli.config_commands import config_group, detect_config_files, show_config_context
from exobrain.cli.config_wizard import init_config
from exobrain.cli.constitution_commands import constitution_group
from exobrain.cli.permissions import request_permission, update_permission
from exobrain.cli.ui import CLIStatusHandler, ToolCallDisplay
from exobrain.config import Config, get_user_config_path, load_config
from exobrain.providers.factory import ModelFactory
from exobrain.tools.base import ToolRegistry
from exobrain.tools.context7_tools import Context7SearchTool
from exobrain.tools.file_tools import (
    EditFileTool,
    GrepFileTool,
    ListDirectoryTool,
    ReadFileTool,
    SearchFilesTool,
    WriteFileTool,
)
from exobrain.tools.math_tools import MathEvaluateTool
from exobrain.tools.shell_tools import GetOSInfoTool, ShellExecuteTool
from exobrain.tools.time_tools import GetCurrentTimeTool, GetWorldTimeTool
from exobrain.tools.web_tools import WebFetchTool, WebSearchTool

console = Console()
logger = logging.getLogger(__name__)

# Global reference to current agent and config for permission updates
_current_agent = None
_current_config = None


def _get_mcp_config_target_path() -> Path:
    """Choose a config file to modify for MCP operations."""
    configs = detect_config_files()
    return configs.get("project_level") or configs.get("user") or get_user_config_path()


def _load_yaml_config(path: Path) -> dict[str, Any]:
    """Load YAML config from path or return empty dict."""
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def _save_yaml_config(path: Path, data: dict[str, Any]) -> None:
    """Persist YAML config to path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def load_constitution(constitution_path: str | Path | None = None) -> str:
    """Load constitution document from file.

    Args:
        constitution_path: Path to constitution file. Can be:
            - None: uses builtin-default
            - Absolute path: used directly
            - Relative path: searched in multiple locations
            - Name without extension: auto-adds .md and searches

    Search order for relative paths:
        1. Package constitutions directory (exobrain/constitutions/<name>)
        2. Package installation directory (exobrain/<path>)
        3. Current working directory (./<path>)

    Returns:
        Constitution content as string, or empty string if file not found
    """
    try:
        # Default to builtin-default if not specified
        if constitution_path is None or constitution_path == "":
            constitution_path = "builtin-default"

        path = Path(constitution_path)

        # Auto-add .md extension if not present and not a full path
        if not path.suffix and not path.is_absolute():
            path = Path(str(path) + ".md")

        if not path.is_absolute():
            # Search order for relative paths:
            import exobrain

            package_dir = Path(exobrain.__file__).parent

            # 1. Package constitutions directory (highest priority for packaged files)
            constitutions_dir = package_dir / "constitutions" / path.name
            if constitutions_dir.exists():
                path = constitutions_dir
                logger.debug(f"Found constitution in package constitutions dir: {path}")
            # 2. Package installation directory (for backward compatibility)
            elif (package_dir / path).exists():
                path = package_dir / path
                logger.debug(f"Found constitution in package dir: {path}")
            # 3. Relative to current working directory
            elif path.exists():
                logger.debug(f"Found constitution in current dir: {path}")
                pass
            # 4. Relative to current working directory (with explicit path join)
            elif (Path.cwd() / path).exists():
                path = Path.cwd() / path
                logger.debug(f"Found constitution in cwd: {path}")
            else:
                logger.warning(f"Constitution file not found: {constitution_path}")
                logger.debug(
                    f"Searched in: {constitutions_dir}, {package_dir / path}, "
                    f"{Path.cwd() / path}, {path}"
                )
                return ""

        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
                logger.info(f"Loaded constitution from: {path}")
                return content
        else:
            logger.warning(f"Constitution file not found: {constitution_path}")
            return ""
    except Exception as e:
        logger.error(f"Error loading constitution: {e}")
        return ""


def setup_logging(level: str = "INFO", config: Config | None = None) -> None:
    """Setup logging configuration with file output support.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        config: Optional Config object for file logging configuration
    """
    # Basic console logging
    log_format = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format=log_format,
    )
    # Quiet noisy tool logs unless verbose
    tools_logger = logging.getLogger("exobrain.tools")
    skills_logger = logging.getLogger("exobrain.skills")
    httpx_logger = logging.getLogger("httpx")
    primp_logger = logging.getLogger("primp")
    markdown_it_logger = logging.getLogger("markdown_it")
    httpcore_logger = logging.getLogger("httpcore")
    new_level = logging.DEBUG if level.upper() == "DEBUG" else logging.WARNING
    tools_logger.setLevel(new_level)
    skills_logger.setLevel(new_level)
    httpx_logger.setLevel(new_level)
    primp_logger.setLevel(new_level)
    # Always silence markdown_it and httpcore - they're too noisy even in debug mode
    markdown_it_logger.setLevel(logging.WARNING)
    httpcore_logger.setLevel(logging.WARNING)

    # If config provided, setup file logging
    if config and hasattr(config, "logging"):
        log_file_path = None

        # Check for project-level logs directory first
        project_log_dir = Path.cwd() / ".exobrain" / "logs"
        if project_log_dir.exists():
            log_file_path = project_log_dir / "exobrain.log"
            logger.debug(f"Using project-level logs: {log_file_path}")
        else:
            # Use configured path (from user config or project-level config)
            configured_path = Path(config.logging.file).expanduser()
            log_file_path = configured_path

        # Create log directory if needed
        if log_file_path:
            log_file_path.parent.mkdir(parents=True, exist_ok=True)

            # Add file handler
            file_handler = logging.FileHandler(log_file_path, encoding="utf-8")
            file_handler.setLevel(getattr(logging, level.upper()))
            file_handler.setFormatter(logging.Formatter(log_format))

            # Add to root logger
            logging.getLogger().addHandler(file_handler)
            logger.debug(f"Logging to file: {log_file_path}")


def create_agent_from_config(
    config: Config, model_spec: str | None = None, enable_skills: bool = True
) -> tuple[Agent, Any]:  # Returns (agent, skills_manager)
    """Create an agent from configuration.

    Args:
        config: Application configuration
        model_spec: Optional model specification (overrides config default)
        enable_skills: Whether to enable skills (default: True)

    Returns:
        Tuple of (Configured Agent instance, Skills manager)
    """
    # Create model factory and get provider
    model_factory = ModelFactory(config)
    model_provider = model_factory.get_provider(model_spec)

    # Create tool registry
    tool_registry = ToolRegistry()

    # Register tools based on configuration
    if config.tools.file_system and config.permissions.file_system.get("enabled", True):
        fs_perms = config.permissions.file_system
        allowed_paths = fs_perms.get("allowed_paths") or []
        denied_paths = fs_perms.get("denied_paths") or []
        max_file_size = fs_perms.get("max_file_size", 10485760)
        allow_edit = fs_perms.get("allow_edit", False)

        tool_registry.register(ReadFileTool(allowed_paths, denied_paths))
        tool_registry.register(
            WriteFileTool(allowed_paths, denied_paths, max_file_size, allow_edit=allow_edit)
        )
        tool_registry.register(
            EditFileTool(allowed_paths, denied_paths, max_file_size, allow_edit=allow_edit)
        )
        tool_registry.register(ListDirectoryTool(allowed_paths, denied_paths))
        tool_registry.register(SearchFilesTool(allowed_paths, denied_paths))
        tool_registry.register(GrepFileTool(allowed_paths, denied_paths))

    if config.tools.time_management:
        tool_registry.register(GetCurrentTimeTool())
        tool_registry.register(GetWorldTimeTool())

    # Math evaluation and OS info are always available and require no extra permissions
    tool_registry.register(MathEvaluateTool())
    tool_registry.register(GetOSInfoTool())

    # Register shell execution tool if enabled
    if getattr(config.tools, "shell_execution", False) and config.permissions.shell_execution.get(
        "enabled", False
    ):
        shell_perms = config.permissions.shell_execution
        allowed_dirs = shell_perms.get("allowed_directories") or []
        denied_dirs = shell_perms.get("denied_directories") or []
        allowed_cmds = shell_perms.get("allowed_commands") or []
        denied_cmds = shell_perms.get("denied_commands") or []
        timeout = shell_perms.get("timeout", 30)

        tool_registry.register(
            ShellExecuteTool(
                allowed_directories=allowed_dirs,
                denied_directories=denied_dirs,
                allowed_commands=allowed_cmds,
                denied_commands=denied_cmds,
                timeout=timeout,
            )
        )

    # Register web tools if enabled
    if getattr(config.tools, "web_access", False) and config.permissions.web_access.get(
        "enabled", False
    ):
        max_results = config.permissions.web_access.get("max_results", 5)
        max_content_length = config.permissions.web_access.get("max_content_length", 10000)

        tool_registry.register(WebSearchTool(max_results=max_results))
        tool_registry.register(WebFetchTool(max_content_length=max_content_length))
        # Context7 search (uses the same web_access permission scope)
        ctx7_cfg = getattr(config.mcp, "context7", {}) or {}
        if ctx7_cfg.get("enabled") and ctx7_cfg.get("api_key"):
            from exobrain.mcp.context7_client import Context7Client

            ctx7_client = Context7Client(
                api_key=ctx7_cfg["api_key"],
                endpoint=ctx7_cfg.get("endpoint", "https://api.context7.com/v1/search"),
                timeout=ctx7_cfg.get("timeout", 20),
                max_results=ctx7_cfg.get("max_results", max_results),
            )
            tool_registry.register(Context7SearchTool(ctx7_client))
    # Register location tool if enabled
    if getattr(config.tools, "location", False) and config.permissions.location.get(
        "enabled", False
    ):
        from exobrain.tools.location_tools import GetUserLocationTool

        location_perms = config.permissions.location
        provider_url = location_perms.get("provider_url", "https://ipinfo.io/json")
        timeout = location_perms.get("timeout", 10)
        token = location_perms.get("token")

        tool_registry.register(
            GetUserLocationTool(provider_url=provider_url, timeout=timeout, token=token)
        )

    # Load constitution document (defaults to builtin-default if not specified)
    constitution_file = getattr(config.agent, "constitution_file", None)
    constitution_content = load_constitution(constitution_file)

    # Build system prompt with constitution
    system_prompt_parts = [config.agent.system_prompt]
    if constitution_content:
        system_prompt_parts.append("\n\n# Constitution and Behavioral Guidelines\n")
        system_prompt_parts.append(constitution_content)

    # Load skills if enabled
    skills_manager = None

    if enable_skills and getattr(config.skills, "enabled", True):
        from exobrain.skills.loader import load_default_skills
        from exobrain.skills.manager import SkillsManager
        from exobrain.tools.skill_tools import GetSkillTool, ListSkillsTool, SearchSkillsTool

        logger.debug("Loading skills...")
        loader = load_default_skills(config)
        skills_manager = SkillsManager(loader.skills)

        # Register skill tools
        if skills_manager.skills:
            get_skill_tool = GetSkillTool(skills_manager)
            search_skills_tool = SearchSkillsTool(skills_manager)
            list_skills_tool = ListSkillsTool(skills_manager)

            tool_registry.register(get_skill_tool)
            tool_registry.register(search_skills_tool)
            tool_registry.register(list_skills_tool)

            logger.debug(f"Registered {len(skills_manager.skills)} skills")

        # Add skills summary to system prompt
        skills_summary = skills_manager.get_all_skills_summary()
        if skills_summary:
            system_prompt_parts.append("\n\n# Available Skills\n")
            system_prompt_parts.append(skills_summary)
            logger.debug(f"Added skills summary to system prompt")

    # Log tool registrations with names for visibility
    tools = tool_registry.list_tools()
    tool_names = [t.name for t in tools]
    logger.debug(f"Registered {len(tools)} tools: {', '.join(tool_names)}")

    # Combine all parts into final system prompt
    system_prompt = "".join(system_prompt_parts)

    # Create agent
    agent = Agent(
        model_provider=model_provider,
        tool_registry=tool_registry,
        system_prompt=system_prompt,
        max_iterations=getattr(config.agent, "max_iterations", 100),
        temperature=getattr(config.agent, "temperature", 0.7),
        stream=config.agent.stream,
    )

    return agent, skills_manager


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
    app_config = ChatAppConfig(
        title="ExoBrain 🧠",
        subtitle="AI Assistant",
        show_welcome=True,
        scope=storage_type,
        project_name=Path.cwd().name if storage_type == "project" else None,
        config_path=config_path,
        working_dir=str(Path.cwd()),
        model=agent.model_provider.model if agent.model_provider else None,
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


@click.group()
@click.option("--config", type=click.Path(), help="Path to configuration file")
@click.option("--verbose", is_flag=True, help="Enable verbose output")
@click.pass_context
def main(ctx: click.Context, config: str | None, verbose: bool) -> None:
    """ExoBrain - Your personal AI assistant."""
    # Setup basic logging first (will be enhanced after config load)
    log_level = "DEBUG" if verbose else "INFO"
    setup_logging(log_level)

    # Check if this is a config init command - it doesn't need existing config
    import sys

    is_config_init = len(sys.argv) >= 3 and sys.argv[1] == "config" and sys.argv[2] == "init"

    # Load configuration (skip for config init)
    if not is_config_init:
        try:
            if config:
                cfg, cfg_metadata = load_config(Path(config))
            else:
                cfg, cfg_metadata = load_config()

            # Re-setup logging with config for file output
            setup_logging(log_level, cfg)

            # Show configuration source info (if verbose or project-level config found)
            if verbose or any(source[0] == "project-level" for source in cfg_metadata["sources"]):
                source_type, source_path = cfg_metadata["primary_source"]
                if source_type == "project-level":
                    console.print(
                        f"[cyan]ℹ[/cyan] Using project-level configuration: [dim]{source_path}[/dim]"
                    )
                elif verbose:
                    console.print(f"[dim]Using configuration from: {source_path}[/dim]")

        except FileNotFoundError as e:
            console.print(f"[red]Configuration file not found: {e}[/red]")
            console.print(
                "[yellow]Run 'exobrain config init' to create a configuration file.[/yellow]"
            )
            ctx.exit(1)
        except Exception as e:
            console.print(f"[red]Error loading configuration: {e}[/red]")
            ctx.exit(1)

        # Store config and metadata in context
        ctx.obj = {"config": cfg, "config_metadata": cfg_metadata}
    else:
        # For config init, just provide empty context
        ctx.obj = {}


@main.command()
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


@main.command()
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
        from exobrain.cli.permissions import request_permission, update_permission

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


# Register additional config commands to existing config_cmd group
# (config_cmd is defined later in this file)
# We'll add them after config_cmd is defined


@main.group()
@click.pass_context
def sessions(ctx: click.Context) -> None:
    """Manage conversation sessions.

    Examples:
        exobrain sessions list              # List recent sessions
        exobrain sessions show <ID>         # Show session details
        exobrain sessions delete <ID>       # Delete a session
    """
    pass


@sessions.command("list")
@click.option(
    "--limit",
    default=10,
    help="Maximum number of sessions to show per location",
)
@click.pass_context
def sessions_list(ctx: click.Context, limit: int) -> None:
    """List recent conversation sessions from both project and global storage."""
    from pathlib import Path

    from exobrain.memory.conversations import ConversationManager

    config: Config = ctx.obj["config"]

    # Initialize model provider for token counting
    from exobrain.providers.factory import ModelFactory

    try:
        model_factory = ModelFactory(config)
        model_provider = model_factory.get_provider()
    except Exception as e:
        console.print(f"[red]Error initializing model provider: {e}[/red]")
        ctx.exit(1)

    # Collect sessions from both locations
    all_sessions = []

    # 1. Project-level sessions (priority)
    project_conversations_path = Path.cwd() / ".exobrain" / "conversations"
    if project_conversations_path.parent.exists():
        project_manager = ConversationManager(
            storage_path=project_conversations_path,
            model_provider=model_provider,
            save_tool_history=config.memory.save_tool_history,
            tool_content_max_length=config.memory.tool_content_max_length,
        )
        project_sessions = project_manager.list_sessions(limit=limit)
        for session in project_sessions:
            session["_source"] = "project"
            session["_source_path"] = str(project_conversations_path)
        all_sessions.extend(project_sessions)

    # 2. Global sessions
    user_data_dir = Path.home() / ".exobrain" / "data"
    global_conversations_path = user_data_dir / "conversations"
    if global_conversations_path.exists():
        global_manager = ConversationManager(
            storage_path=global_conversations_path,
            model_provider=model_provider,
            save_tool_history=config.memory.save_tool_history,
            tool_content_max_length=config.memory.tool_content_max_length,
        )
        global_sessions = global_manager.list_sessions(limit=limit)
        for session in global_sessions:
            session["_source"] = "global"
            session["_source_path"] = str(global_conversations_path)
        all_sessions.extend(global_sessions)

    if not all_sessions:
        console.print("[yellow]No conversation sessions found.[/yellow]")
        return

    # Display sessions in a table
    from rich.table import Table

    table = Table(title="Recent Sessions")
    table.add_column("Scope", style="magenta", width=8)
    table.add_column("ID", style="cyan")
    table.add_column("Title", style="white")
    table.add_column("Messages", justify="right", style="blue")
    table.add_column("Last Activity", style="dim")

    for session in all_sessions:
        scope_label = "📁Proj" if session["_source"] == "project" else "🏠User"
        table.add_row(
            scope_label,
            session["id"],
            session.get("title", "Untitled"),
            str(session.get("message_count", 0)),
            session.get("last_activity", "Unknown")[:19],  # Truncate timestamp
        )

    console.print(table)

    # Show storage paths
    console.print()
    if any(s["_source"] == "project" for s in all_sessions):
        console.print(f"[dim]📁Project: {project_conversations_path}[/dim]")
    if any(s["_source"] == "global" for s in all_sessions):
        console.print(f"[dim]🏠User:  {global_conversations_path}[/dim]")


def _get_conversation_manager_for_session(
    session_id: str, config: Any, model_provider: Any
) -> tuple[Any, str] | None:
    """Find the conversation manager that contains the given session.

    Args:
        session_id: Session ID to find
        config: Config object
        model_provider: Model provider instance

    Returns:
        Tuple of (ConversationManager, source_label) or None if not found
    """
    from pathlib import Path

    from exobrain.memory.conversations import ConversationManager

    # Try project-level first
    project_conversations_path = Path.cwd() / ".exobrain" / "conversations"
    if project_conversations_path.parent.exists():
        project_manager = ConversationManager(
            storage_path=project_conversations_path,
            model_provider=model_provider,
            save_tool_history=config.memory.save_tool_history,
            tool_content_max_length=config.memory.tool_content_max_length,
        )
        if project_manager.get_session_metadata(session_id):
            return project_manager, "project"

    # Try global
    user_data_dir = Path.home() / ".exobrain" / "data"
    global_conversations_path = user_data_dir / "conversations"
    if global_conversations_path.exists():
        global_manager = ConversationManager(
            storage_path=global_conversations_path,
            model_provider=model_provider,
            save_tool_history=config.memory.save_tool_history,
            tool_content_max_length=config.memory.tool_content_max_length,
        )
        if global_manager.get_session_metadata(session_id):
            return global_manager, "global"

    return None


@sessions.command("show")
@click.argument("session_id")
@click.pass_context
def sessions_show(ctx: click.Context, session_id: str) -> None:
    """Show details of a specific session."""
    import json
    from pathlib import Path

    from rich.panel import Panel
    from rich.syntax import Syntax

    from exobrain.memory.conversations import ConversationManager

    config: Config = ctx.obj["config"]

    # Initialize model provider
    from exobrain.providers.factory import ModelFactory

    try:
        model_factory = ModelFactory(config)
        model_provider = model_factory.get_provider()
    except Exception as e:
        console.print(f"[red]Error initializing model provider: {e}[/red]")
        ctx.exit(1)

    # Find the session
    result = _get_conversation_manager_for_session(session_id, config, model_provider)
    if not result:
        console.print(f"[red]Session not found: {session_id}[/red]")
        ctx.exit(1)

    conversation_manager, source = result
    scope_label = "📁Project" if source == "project" else "🏠User"

    # Get session metadata
    try:
        metadata = conversation_manager.get_session_metadata(session_id)
        if not metadata:
            console.print(f"[red]Session not found: {session_id}[/red]")
            ctx.exit(1)

        # Display metadata
        info_lines = [
            f"[bold]Scope:[/bold] {scope_label}",
            f"[bold]Session ID:[/bold] {metadata['id']}",
            f"[bold]Title:[/bold] {metadata.get('title', 'Untitled')}",
            f"[bold]Model:[/bold] {metadata.get('model', 'Unknown')}",
            f"[bold]Created:[/bold] {metadata.get('created_at', 'Unknown')[:19]}",
            f"[bold]Updated:[/bold] {metadata.get('updated_at', 'Unknown')[:19]}",
            f"[bold]Message Count:[/bold] {metadata.get('message_count', 0)}",
            f"[bold]Total Tokens:[/bold] {metadata.get('total_tokens', 0):,}",
        ]

        console.print(
            Panel(
                "\n".join(info_lines),
                title="Session Details",
                border_style="cyan",
            )
        )

        # Load and display messages preview
        session_data = conversation_manager.load_session(session_id, token_budget=None)
        messages = session_data["messages"]

        if messages:
            console.print(f"\n[bold cyan]Messages ({len(messages)}):[/bold cyan]")
            for i, msg in enumerate(messages[-5:], start=max(0, len(messages) - 5)):
                role_color = "green" if msg["role"] == "user" else "cyan"
                content_preview = msg.get("content", "")[:100]
                if len(msg.get("content", "")) > 100:
                    content_preview += "..."
                console.print(
                    f"  [{role_color}]{msg['role'].upper()}[/{role_color}]: {content_preview}"
                )

            if len(messages) > 5:
                console.print(f"  [dim]... and {len(messages) - 5} more messages[/dim]")

    except Exception as e:
        console.print(f"[red]Error loading session: {e}[/red]")
        logger.exception("Error loading session")
        ctx.exit(1)


@sessions.command("delete")
@click.argument("session_ids", nargs=-1, required=False)
@click.option("--all", is_flag=True, help="Delete all sessions")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
@click.pass_context
def sessions_delete(ctx: click.Context, session_ids: tuple[str, ...], all: bool, yes: bool) -> None:
    """Delete one or more conversation sessions.

    Examples:
        exobrain sessions delete abc123              # Delete single session
        exobrain sessions delete abc123 def456       # Delete multiple sessions
        exobrain sessions delete --all               # Delete all sessions
        exobrain sessions delete --all --yes         # Delete all without confirmation
    """
    from pathlib import Path

    from rich.prompt import Confirm

    from exobrain.memory.conversations import ConversationManager

    config: Config = ctx.obj["config"]

    # Validate arguments
    if not all and not session_ids:
        console.print("[red]Error: Provide session IDs to delete or use --all flag[/red]")
        console.print("[dim]Usage: exobrain sessions delete <session_id> [<session_id> ...]")
        console.print("[dim]   or: exobrain sessions delete --all[/dim]")
        ctx.exit(1)

    if all and session_ids:
        console.print("[yellow]Warning: --all flag ignores specific session IDs[/yellow]")

    # Initialize model provider
    from exobrain.providers.factory import ModelFactory

    try:
        model_factory = ModelFactory(config)
        model_provider = model_factory.get_provider()
    except Exception as e:
        console.print(f"[red]Error initializing model provider: {e}[/red]")
        ctx.exit(1)

    # Collect all managers
    managers = []
    project_conversations_path = Path.cwd() / ".exobrain" / "conversations"
    user_data_dir = Path.home() / ".exobrain" / "data"
    global_conversations_path = user_data_dir / "conversations"

    if project_conversations_path.parent.exists():
        project_manager = ConversationManager(
            storage_path=project_conversations_path,
            model_provider=model_provider,
            save_tool_history=config.memory.save_tool_history,
            tool_content_max_length=config.memory.tool_content_max_length,
        )
        managers.append(("project", project_manager))

    if global_conversations_path.exists():
        global_manager = ConversationManager(
            storage_path=global_conversations_path,
            model_provider=model_provider,
            save_tool_history=config.memory.save_tool_history,
            tool_content_max_length=config.memory.tool_content_max_length,
        )
        managers.append(("global", global_manager))

    if not managers:
        console.print("[yellow]No conversation storage found.[/yellow]")
        return

    # Get sessions to delete
    if all:
        # Get all sessions from all managers
        sessions_to_delete = []
        for source, manager in managers:
            source_sessions = manager.list_sessions(limit=10000)
            for s in source_sessions:
                sessions_to_delete.append((s["id"], source))
        if not sessions_to_delete:
            console.print("[yellow]No sessions to delete.[/yellow]")
            return
    else:
        # Find each session in managers
        sessions_to_delete = []
        for session_id in session_ids:
            found = False
            for source, manager in managers:
                if manager.get_session_metadata(session_id):
                    sessions_to_delete.append((session_id, source))
                    found = True
                    break
            if not found:
                sessions_to_delete.append((session_id, None))

    # Verify sessions exist and get metadata
    valid_sessions = []
    invalid_sessions = []
    for item in sessions_to_delete:
        if len(item) == 2 and item[1] is not None:
            session_id, source = item
            # Find the manager
            manager = next(m for s, m in managers if s == source)
            metadata = manager.get_session_metadata(session_id)
            if metadata:
                valid_sessions.append((session_id, source, manager, metadata))
            else:
                invalid_sessions.append(session_id)
        else:
            invalid_sessions.append(item[0])

    if invalid_sessions:
        console.print(f"[yellow]Warning: {len(invalid_sessions)} session(s) not found:[/yellow]")
        for sid in invalid_sessions:
            console.print(f"  • {sid}")
        console.print()

    if not valid_sessions:
        console.print("[red]No valid sessions to delete.[/red]")
        ctx.exit(1)

    # Show what will be deleted
    console.print(f"[yellow]About to delete {len(valid_sessions)} session(s):[/yellow]")
    for session_id, source, manager, metadata in valid_sessions:
        title = metadata.get("title", "Untitled")
        scope_label = "📁" if source == "project" else "🌍"
        console.print(f"  {scope_label} {session_id[:8]} - {title}")
    console.print()

    # Confirm deletion
    if not yes:
        if all:
            confirm_msg = f"[bold red]Delete ALL {len(valid_sessions)} sessions? This cannot be undone![/bold red]"
        elif len(valid_sessions) > 1:
            confirm_msg = f"Delete these {len(valid_sessions)} sessions?"
        else:
            confirm_msg = (
                f"Delete session '{valid_sessions[0][3].get('title', valid_sessions[0][0])}'?"
            )

        confirmed = Confirm.ask(confirm_msg, default=False)
        if not confirmed:
            console.print("[yellow]Cancelled.[/yellow]")
            return

    # Delete sessions
    success_count = 0
    failed_count = 0
    try:
        for session_id, source, manager, metadata in valid_sessions:
            try:
                if manager.delete_session(session_id):
                    success_count += 1
                    scope_label = "📁" if source == "project" else "🌍"
                    # fix session id length to 8 to display date only
                    console.print(
                        f"[green]✓[/green] {scope_label} Deleted: {session_id[:8]} - {metadata.get('title', 'Untitled')}"
                    )
                else:
                    failed_count += 1
                    console.print(f"[red]✗[/red] Failed to delete: {session_id[:8]}")
            except Exception as e:
                failed_count += 1
                console.print(f"[red]✗[/red] Error deleting {session_id[:8]}: {e}")

        # Summary
        console.print()
        console.print(f"[green]Successfully deleted {success_count} session(s)[/green]")
        if failed_count > 0:
            console.print(f"[red]Failed to delete {failed_count} session(s)[/red]")

    except Exception as e:
        console.print(f"[red]Error during deletion: {e}[/red]")
        logger.exception("Error deleting sessions")
        ctx.exit(1)


@main.group()
def config_cmd() -> None:
    """Manage configuration."""
    pass


# config init is now handled by the interactive wizard from config_wizard module
# Adding it below with other config commands


@config_cmd.command("show")
@click.pass_context
def config_show(ctx: click.Context) -> None:
    """Show current configuration."""
    config: Config = ctx.obj["config"]

    console.print(
        Panel(
            f"Default Model: {config.models.default}\n"
            f"Streaming: {config.agent.stream}\n"
            f"Tools Enabled: "
            f"file_system={config.tools.file_system}, "
            f"time_management={config.tools.time_management}",
            title="Configuration",
            border_style="cyan",
        )
    )


# Add additional config commands from config_commands and config_wizard modules
from exobrain.cli.config_commands import edit, get
from exobrain.cli.config_commands import list as list_config
from exobrain.cli.config_commands import path as show_path
from exobrain.cli.config_commands import reset, set

config_cmd.add_command(init_config)  # Interactive wizard (replaces old init)
config_cmd.add_command(set)
config_cmd.add_command(get)
config_cmd.add_command(show_path)
config_cmd.add_command(list_config)
config_cmd.add_command(edit)
config_cmd.add_command(reset)


@main.group()
def models() -> None:
    """Manage models."""
    pass


@models.command("list")
@click.pass_context
def models_list(ctx: click.Context) -> None:
    """List available models."""
    config: Config = ctx.obj["config"]
    cfg_metadata = ctx.obj.get("config_metadata", {})

    try:
        factory = ModelFactory(config)
        available_models = factory.list_available_models()

        # Determine which config set the default model
        source_type, source_path = cfg_metadata.get("primary_source", ("default", "builtin"))
        source_label = {
            "user": "global user config",
            "project-level": "project-level config (.exobrain/)",
            "default": "default",
        }.get(source_type, source_type)

        # Build model list with checkmark for current default
        model_lines = []
        for model in available_models:
            if model == config.models.default:
                model_lines.append(f"[green]✓[/green] {model}")
            else:
                model_lines.append(f"  {model}")

        title = f"Available Models (current: {config.models.default})"
        if source_type != "default":
            title += f"\n[dim]Set by: {source_label}[/dim]"

        console.print(
            Panel(
                "\n".join(model_lines),
                title=title,
                border_style="cyan",
            )
        )
    except Exception as e:
        console.print(f"[red]Error listing models: {e}[/red]")


@models.command("use")
@click.argument("model_name", required=False)
@click.pass_context
def models_use(ctx: click.Context, model_name: str | None) -> None:
    """Set the default model to use.

    Examples:
        exobrain models use                    # Interactive selection
        exobrain models use openai/gpt-4o      # Direct selection
    """
    import yaml
    from rich.prompt import Prompt

    config: Config = ctx.obj["config"]

    try:
        # Get available models
        factory = ModelFactory(config)
        available_models = factory.list_available_models()

        # Interactive model selection if not provided
        if not model_name:
            console.print("[cyan]Available models:[/cyan]")
            for i, model in enumerate(available_models, 1):
                prefix = "→ " if model == config.models.default else "  "
                console.print(f"{prefix}{i}. {model}")
            console.print()

            choice = Prompt.ask(
                "Select model number (or enter custom model name)",
                default=str(available_models.index(config.models.default) + 1)
                if config.models.default in available_models
                else "1",
            )

            # Parse choice
            if choice.isdigit() and 1 <= int(choice) <= len(available_models):
                model_name = available_models[int(choice) - 1]
            else:
                model_name = choice
        else:
            # check if model is valid
            if model_name not in available_models:
                console.print(f"[red]Model not found: {model_name}[/red]")
                console.print("[cyan]Available models:[/cyan]")
                for model in available_models:
                    console.print(f"  • {model}")
                ctx.exit(1)

        # Detect available config files
        from exobrain.cli.config_commands import detect_config_files

        config_files = detect_config_files()
        available_configs = [(k, v) for k, v in config_files.items() if v is not None]

        if not available_configs:
            console.print("[red]No configuration files found.[/red]")
            console.print("[yellow]Run 'exobrain config init' to create one.[/yellow]")
            ctx.exit(1)

        # Select which config to modify
        if len(available_configs) == 1:
            config_type, config_path = available_configs[0]
        else:
            console.print("\n[cyan]Multiple configuration files detected:[/cyan]")
            for i, (ctype, cpath) in enumerate(available_configs, 1):
                label = {
                    "user": "Global user config",
                    "project_level": "Project-level config (.exobrain/)",
                }.get(ctype, ctype)
                console.print(f"  {i}. {label}")
                console.print(f"     [dim]{cpath}[/dim]")
            console.print()

            choice_idx = int(
                Prompt.ask(
                    "Which configuration to modify?",
                    choices=[str(i) for i in range(1, len(available_configs) + 1)],
                    default="1",
                )
            )
            config_type, config_path = available_configs[choice_idx - 1]

        # Load, modify, and save the config
        with open(config_path, "r", encoding="utf-8") as f:
            config_data = yaml.safe_load(f) or {}

        # Ensure models section exists
        if "models" not in config_data:
            config_data["models"] = {}

        # Update default model
        config_data["models"]["default"] = model_name

        # Save back
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(
                config_data,
                f,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            )

        # Show success message
        config_label = {
            "user": "global user",
            "project_level": "project-level",
        }.get(config_type, config_type)

        console.print(
            f"[green]✓[/green] Set default model to [bold]{model_name}[/bold] in {config_label} config"
        )
        console.print(f"[dim]Config file: {config_path}[/dim]")

        # Warn if a higher-priority config might override this change
        config_priority = {"user": 1, "project_level": 2}
        current_priority = config_priority.get(config_type, 0)

        # Check if higher-priority configs exist
        higher_priority_configs = [
            (ctype, cpath)
            for ctype, cpath in available_configs
            if config_priority.get(ctype, 0) > current_priority
        ]

        if higher_priority_configs:
            console.print(
                "\n[yellow]⚠ Warning:[/yellow] Higher-priority configuration files exist:"
            )
            for ctype, cpath in higher_priority_configs:
                hlabel = {"project_level": "Project-level config (.exobrain/)"}.get(ctype, ctype)
                console.print(f"  • {hlabel}: [dim]{cpath}[/dim]")
            console.print(
                "[yellow]These may override your change if they also set models.default[/yellow]"
            )

    except Exception as e:
        console.print(f"[red]Error setting model: {e}[/red]")
        logger.exception("Error setting model")
        ctx.exit(1)


@main.group()
@click.pass_context
def mcp(ctx: click.Context) -> None:
    """Manage MCP servers (including Context7)."""
    pass


@mcp.command("list")
@click.pass_context
def mcp_list(ctx: click.Context) -> None:
    """List configured MCP servers."""
    config: Config = ctx.obj["config"]
    cfg_metadata = ctx.obj.get("config_metadata", {})
    servers = getattr(config.mcp, "servers", []) if getattr(config, "mcp", None) else []

    table = Table(title="MCP Servers", show_header=True, header_style="bold cyan")
    table.add_column("Name")
    table.add_column("Enabled", justify="center")
    table.add_column("Transport/Type")
    table.add_column("Source")

    primary_source = cfg_metadata.get("primary_source", ("default", ""))
    source_label = primary_source[1] or primary_source[0]

    for server in servers:
        name = server.get("name", "<unnamed>")
        enabled = server.get("enabled", True)
        transport = (
            server.get("transport")
            or ("stdio" if server.get("command") else None)
            or ("http" if server.get("url") else "custom")
        )
        table.add_row(name, "✅" if enabled else "❌", transport, source_label)

    # Context7 as a built-in MCP-style service
    ctx7_cfg = getattr(config.mcp, "context7", {}) if getattr(config, "mcp", None) else {}
    if ctx7_cfg:
        table.add_row(
            "context7",
            "✅" if ctx7_cfg.get("enabled") else "❌",
            "http",
            source_label,
        )

    console.print(table)


def _toggle_mcp_server(name: str, enabled: bool) -> bool:
    """Enable/disable a server in the writable config file."""
    target_path = _get_mcp_config_target_path()
    console.print()
    show_config_context("Modifying", target_path)
    console.print()

    data = _load_yaml_config(target_path)
    mcp_cfg = data.setdefault("mcp", {})
    # Ensure global switch follows any enabled server
    if enabled:
        mcp_cfg["enabled"] = True

    if name == "context7":
        ctx7_cfg = mcp_cfg.setdefault("context7", {})
        ctx7_cfg["enabled"] = enabled
        if not enabled:
            # If everything is disabled, flip global switch off
            all_disabled = not any(
                s.get("enabled", False) for s in mcp_cfg.get("servers", [])
            ) and not ctx7_cfg.get("enabled", False)
            if all_disabled:
                mcp_cfg["enabled"] = False
        _save_yaml_config(target_path, data)
        return True

    servers = mcp_cfg.setdefault("servers", [])
    for server in servers:
        if server.get("name") == name:
            server["enabled"] = enabled
            if not enabled:
                ctx7_enabled = mcp_cfg.get("context7", {}).get("enabled", False)
                any_server_enabled = any(s.get("enabled", False) for s in servers)
                if not ctx7_enabled and not any_server_enabled:
                    mcp_cfg["enabled"] = False
            _save_yaml_config(target_path, data)
            return True

    console.print(f"[red]Server '{name}' not found in mcp.servers. Please add it first.[/red]")
    return False


@mcp.command("enable")
@click.argument("name")
def mcp_enable(name: str) -> None:
    """Enable an MCP server by name (or 'context7')."""
    if _toggle_mcp_server(name, True):
        console.print(f"[green]✓ Enabled MCP server '{name}'[/green]")


@mcp.command("disable")
@click.argument("name")
def mcp_disable(name: str) -> None:
    """Disable an MCP server by name (or 'context7')."""
    if _toggle_mcp_server(name, False):
        console.print(f"[yellow]Disabled MCP server '{name}'[/yellow]")


@main.group()
def skills() -> None:
    """Manage skills."""
    pass


@skills.command("list")
@click.option("--search", "-s", help="Search skills by name or description")
@click.pass_context
def skills_list(ctx: click.Context, search: str | None) -> None:
    """List available skills."""
    from exobrain.skills.loader import load_default_skills

    config: Config = ctx.obj["config"]

    try:
        loader = load_default_skills(config)

        if search:
            results = loader.search_skills(search)
            console.print(f"\n[cyan]Skills matching '{search}':[/cyan]\n")
        else:
            results = list(loader.skills.values())
            console.print(f"\n[cyan]All available skills ({len(results)}):[/cyan]\n")

        if not results:
            console.print("[yellow]No skills found.[/yellow]")
            return

        for skill in results:
            console.print(f"[bold green]{skill.name}[/bold green]")
            console.print(f"  {skill.description}")
            if skill.source_path:
                console.print(f"  [dim]Source: {skill.source_path.parent.name}[/dim]")
            console.print()

    except Exception as e:
        console.print(f"[red]Error listing skills: {e}[/red]")
        logger.exception("Error listing skills")


@skills.command("show")
@click.argument("skill_name")
@click.pass_context
def skills_show(ctx: click.Context, skill_name: str) -> None:
    """Show details of a specific skill."""
    from exobrain.skills.loader import load_default_skills

    config: Config = ctx.obj["config"]

    try:
        loader = load_default_skills(config)
        skill = loader.get_skill(skill_name)

        if not skill:
            console.print(f"[red]Skill not found: {skill_name}[/red]")
            return

        console.print(
            Panel(
                f"[bold]{skill.name}[/bold]\n\n"
                f"{skill.description}\n\n"
                f"[dim]Source: {skill.source_path}[/dim]",
                title="Skill Info",
                border_style="cyan",
            )
        )

        console.print("\n[bold cyan]Instructions:[/bold cyan]\n")
        console.print(Markdown(skill.instructions))

    except Exception as e:
        console.print(f"[red]Error showing skill: {e}[/red]")
        logger.exception("Error showing skill")


# Register constitution command group
main.add_command(constitution_group, name="constitution")


if __name__ == "__main__":
    main()
