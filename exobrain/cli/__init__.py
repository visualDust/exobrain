"""CLI entry point for ExoBrain."""

import logging
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.panel import Panel

from exobrain.agent.core import Agent
from exobrain.cli.config_wizard import init_config
from exobrain.cli.constitution_commands import constitution_group
from exobrain.cli.mcp_commands import mcp
from exobrain.cli.models_commands import models
from exobrain.cli.sessions_commands import sessions
from exobrain.cli.skills_commands import skills
from exobrain.config import Config, load_config
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
main.add_command(models)
main.add_command(sessions)
main.add_command(mcp)
main.add_command(skills)

# Register constitution command group
main.add_command(constitution_group, name="constitution")

# Import and register chat and ask commands
# These need to be imported after create_agent_from_config is defined
from exobrain.cli import chat_commands

# Inject create_agent_from_config into agent_commands module so it can use it
chat_commands.create_agent_from_config = create_agent_from_config

# Register the commands
main.add_command(chat_commands.chat)
main.add_command(chat_commands.ask)


if __name__ == "__main__":
    main()
