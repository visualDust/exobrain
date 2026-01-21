"""Permission request and management for ExoBrain CLI."""

import logging
from pathlib import Path
from typing import Any

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

logger = logging.getLogger(__name__)


async def request_permission(denied_info: dict[str, Any], console: Console) -> tuple[bool, str]:
    """Request permission from user for a denied action.

    Args:
        denied_info: Information about the denied action
        console: Rich console for output

    Returns:
        Tuple of (granted: bool, scope: str)
        scope is one of: "once", "session", "always"
    """
    # Build permission request panel
    info_table = Table(show_header=False, box=None, padding=(0, 1))
    info_table.add_column("Key", style="bold yellow")
    info_table.add_column("Value", style="white")

    info_table.add_row("Tool", denied_info.get("tool", "unknown"))
    info_table.add_row("Action", denied_info.get("action", "unknown"))
    info_table.add_row("Resource", Text(denied_info.get("resource", ""), style="cyan"))
    info_table.add_row("Reason", denied_info.get("reason", "unknown"))

    # Build panel content using Rich Group for proper rendering
    from rich.console import Group

    panel_content = Group(
        Text("⚠️  Permission Required\n", style="bold yellow"),
        Text(""),
        info_table,
        Text(""),
        Text("Grant permission for this action?", style="bold"),
        Text(""),
        Text("  [y] Yes, once       [n] No", style="dim"),
        Text("  [s] Yes, session    [a] Yes, always", style="dim"),
    )

    console.print(
        Panel(
            panel_content,
            title="[yellow]Permission Request[/yellow]",
            border_style="yellow",
            padding=(1, 2),
        )
    )

    # Prompt for choice
    choice = Prompt.ask(
        "\n[bold]Your choice[/bold]",
        choices=["y", "n", "s", "a"],
        default="n",
        console=console,
        show_choices=True,
    )

    if choice == "n":
        console.print("[red]✗ Permission denied[/red]\n")
        return False, "none"

    # Grant permission based on scope
    scope = {
        "y": "once",
        "s": "session",
        "a": "always",
    }.get(choice, "once")

    console.print(f"[green]✓ Permission granted ({scope})[/green]\n")

    return True, scope


def update_permission(denied_info: dict[str, Any], scope: str, agent: Any, config: Any) -> None:
    """Update permissions based on scope.

    Args:
        denied_info: Information about the denied action
        scope: Permission scope (once, session, always)
        agent: Agent instance (for runtime permissions)
        config: Config instance (for permanent permissions)
    """
    permission_type = denied_info.get("type", "unknown")
    resource = denied_info.get("resource", "")
    tool_name = denied_info.get("tool", "")

    # For "once" and "session", update the tool's configuration to allow the retry
    # For "session", also track it in runtime_permissions
    if scope in ["once", "session"]:
        # Update tool's configuration to allow the operation
        if tool_name == "shell_execute":
            shell_tool = agent.tool_registry.get("shell_execute")
            if shell_tool:
                if permission_type == "directory":
                    # Add to tool's allowed directories
                    resolved_path = Path(resource).expanduser().resolve()
                    if resolved_path not in shell_tool._allowed_directories:
                        shell_tool._allowed_directories.append(resolved_path)
                        logger.info(f"Added directory to shell tool ({scope}): {resolved_path}")
                elif permission_type == "command":
                    # Add to tool's allowed commands
                    if resource not in shell_tool._allowed_commands:
                        shell_tool._allowed_commands.append(resource)
                        logger.info(f"Added command to shell tool ({scope}): {resource}")

        # For session scope, also track in runtime permissions
        if scope == "session":
            permission_key = agent._make_permission_key(denied_info)
            agent.runtime_permissions[permission_key] = denied_info
            logger.info(f"Tracked session permission: {permission_key}")

    elif scope == "always":
        # Add to config file
        config_path = Path("config.yaml")
        if not config_path.exists():
            config_path = Path.home() / ".exobrain" / "config.yaml"

        try:
            # Load current config
            with open(config_path, "r", encoding="utf-8") as f:
                config_data = yaml.safe_load(f)

            # Update permissions based on type
            if permission_type == "command":
                if "permissions" not in config_data:
                    config_data["permissions"] = {}
                if "shell_execution" not in config_data["permissions"]:
                    config_data["permissions"]["shell_execution"] = {}
                if "allowed_commands" not in config_data["permissions"]["shell_execution"]:
                    config_data["permissions"]["shell_execution"]["allowed_commands"] = []

                # Add command if not already there
                if (
                    resource
                    not in config_data["permissions"]["shell_execution"]["allowed_commands"]
                ):
                    config_data["permissions"]["shell_execution"]["allowed_commands"].append(
                        resource
                    )
                    logger.info(f"Added command to config: {resource}")

            elif permission_type == "path":
                if "permissions" not in config_data:
                    config_data["permissions"] = {}
                if "file_system" not in config_data["permissions"]:
                    config_data["permissions"]["file_system"] = {}
                if "allowed_paths" not in config_data["permissions"]["file_system"]:
                    config_data["permissions"]["file_system"]["allowed_paths"] = []

                # Add path if not already there
                if resource not in config_data["permissions"]["file_system"]["allowed_paths"]:
                    config_data["permissions"]["file_system"]["allowed_paths"].append(resource)
                    logger.info(f"Added path to config: {resource}")

            elif permission_type == "directory":
                if "permissions" not in config_data:
                    config_data["permissions"] = {}
                if "shell_execution" not in config_data["permissions"]:
                    config_data["permissions"]["shell_execution"] = {}
                if "allowed_directories" not in config_data["permissions"]["shell_execution"]:
                    config_data["permissions"]["shell_execution"]["allowed_directories"] = []

                # Add directory if not already there
                if (
                    resource
                    not in config_data["permissions"]["shell_execution"]["allowed_directories"]
                ):
                    config_data["permissions"]["shell_execution"]["allowed_directories"].append(
                        resource
                    )
                    logger.info(f"Added directory to config: {resource}")

            # Save config
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.dump(
                    config_data,
                    f,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False,
                )

            logger.info(f"Updated config file: {config_path}")

        except Exception as e:
            logger.error(f"Failed to update config: {e}")
