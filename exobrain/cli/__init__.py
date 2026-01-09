"""CLI entry point for ExoBrain."""

import logging
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.panel import Panel

from exobrain.cli.config_wizard import init_config
from exobrain.cli.constitution_commands import constitution_group
from exobrain.cli.init_commands import init
from exobrain.cli.mcp_commands import mcp
from exobrain.cli.models_commands import models
from exobrain.cli.sessions_commands import sessions
from exobrain.cli.skills_commands import skills
from exobrain.config import Config, load_config

console = Console()
logger = logging.getLogger(__name__)


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
                logger.debug(f"Loaded constitution from: {path}")
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
    # Get log format from config or use default
    log_format = "[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s"
    if config and hasattr(config, "logging"):
        log_format = config.logging.format

    # Basic console logging
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format=log_format,
    )
    # Quiet noisy tool logs unless verbose
    httpx_logger = logging.getLogger("httpx")
    primp_logger = logging.getLogger("primp")
    markdown_it_logger = logging.getLogger("markdown_it")
    httpcore_logger = logging.getLogger("httpcore")
    new_level = logging.DEBUG if level.upper() == "DEBUG" else logging.WARNING
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

            # Add file handler with rotation support if enabled
            if config.logging.rotate:
                from logging.handlers import RotatingFileHandler

                file_handler = RotatingFileHandler(
                    log_file_path,
                    maxBytes=config.logging.max_size,
                    backupCount=5,
                    encoding="utf-8",
                )
            else:
                file_handler = logging.FileHandler(log_file_path, encoding="utf-8")

            file_handler.setLevel(getattr(logging, level.upper()))
            file_handler.setFormatter(logging.Formatter(log_format))

            # Add to root logger
            logging.getLogger().addHandler(file_handler)
            logger.debug(f"Logging to file: {log_file_path}")


# Register additional config commands to existing config_cmd group
# (config_cmd is defined later in this file)
# We'll add them after config_cmd is defined


@click.group()
@click.option("--config", type=click.Path(), help="Path to configuration file")
@click.option("--verbose", is_flag=True, help="Enable verbose output")
@click.pass_context
def main(ctx: click.Context, config: str | None, verbose: bool) -> None:
    """ExoBrain - Your personal AI assistant."""
    # Setup basic logging first (will be enhanced after config load)
    log_level = "DEBUG" if verbose else "INFO"
    setup_logging(log_level)

    # Check if this is a command that doesn't need existing config
    import sys

    is_config_init = len(sys.argv) >= 3 and sys.argv[1] == "config" and sys.argv[2] == "init"
    is_project_init = len(sys.argv) >= 2 and sys.argv[1] == "init"

    # Load configuration (skip for init commands that don't need config)
    if not is_config_init and not is_project_init:
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
        # For init commands, just provide empty context
        ctx.obj = {}


@main.group()
def config_cmd() -> None:
    """Manage configuration."""


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


# Register command groups
main.add_command(init)  # Project initialization command
main.add_command(models)
main.add_command(sessions)
main.add_command(mcp)
main.add_command(skills)

# Register constitution command group
main.add_command(constitution_group, name="constitution")

# Import and register chat and ask commands
from exobrain.cli import chat_commands

# Register the commands
main.add_command(chat_commands.chat)
main.add_command(chat_commands.ask)


if __name__ == "__main__":
    main()
