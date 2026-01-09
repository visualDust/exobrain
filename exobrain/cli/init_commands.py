"""Project initialization commands for ExoBrain."""

import logging
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel

console = Console()
logger = logging.getLogger(__name__)


@click.command("init")
@click.option(
    "--force",
    "-f",
    is_flag=True,
    help="Force initialization even if .exobrain directory exists",
)
@click.option(
    "--minimal",
    "-m",
    is_flag=True,
    help="Create minimal structure without example config",
)
def init(force: bool, minimal: bool) -> None:
    """Initialize project-level .exobrain directory structure.

    Creates the following structure in the current directory:

    \b
    .exobrain/
    ├── config.yaml          # Project-level configuration (optional)
    ├── constitutions/       # Project-level personality definitions
    ├── skills/              # Project-specific skills
    ├── conversations/       # Project conversation history
    │   └── sessions/
    └── logs/                # Project-level logs

    Examples:
        exobrain init                  # Create full structure with example config
        exobrain init --minimal        # Create structure without config file
        exobrain init --force          # Reinitialize even if directory exists
    """
    exobrain_dir = Path.cwd() / ".exobrain"

    # Check if directory already exists
    if exobrain_dir.exists() and not force:
        console.print("[yellow]⚠[/yellow] .exobrain directory already exists in current directory")
        console.print(f"[dim]Path: {exobrain_dir}[/dim]")
        console.print("\nUse --force to reinitialize")
        return

    try:
        # Create directory structure
        directories = [
            exobrain_dir,
            exobrain_dir / "constitutions",
            exobrain_dir / "skills",
            exobrain_dir / "conversations" / "sessions",
            exobrain_dir / "logs",
        ]

        created_dirs = []
        for directory in directories:
            if not directory.exists():
                directory.mkdir(parents=True, exist_ok=True)
                created_dirs.append(directory)
                logger.debug(f"Created directory: {directory}")

        # Create example config file (unless minimal mode)
        config_file = exobrain_dir / "config.yaml"
        if not minimal and not config_file.exists():
            example_config = """# ExoBrain Project-Level Configuration
# This file has the highest priority and overrides global settings
# Only specify the settings you want to override

# Example: Override default model for this project
# models:
#   default: "openai/gpt-4o-mini"

# Example: Project-specific agent configuration
# agent:
#   system_prompt: "You are a helpful AI assistant for this project."
#   constitution_file: "project-assistant"
#   temperature: 0.7

# Example: Enable/disable specific tools
# tools:
#   file_system: true
#   web_access: true
#   shell_execution: true

# For more configuration options, see:
# https://github.com/your-org/exobrain/blob/main/docs/configuration.md
"""
            config_file.write_text(example_config, encoding="utf-8")
            logger.debug(f"Created example config: {config_file}")

        # Create .gitignore if it doesn't exist
        gitignore_file = exobrain_dir / ".gitignore"
        if not gitignore_file.exists():
            gitignore_content = """# ExoBrain project-level data (user-specific)
conversations/
logs/

# Keep configuration and definitions (team-shared)
!config.yaml
!constitutions/
!skills/
"""
            gitignore_file.write_text(gitignore_content, encoding="utf-8")
            logger.debug(f"Created .gitignore: {gitignore_file}")

        # Success message
        console.print(
            Panel(
                f"[green]✓[/green] Initialized .exobrain directory structure\n\n"
                f"Location: [cyan]{exobrain_dir}[/cyan]\n\n"
                f"Created:\n"
                f"  • constitutions/  - Project-specific AI personalities\n"
                f"  • skills/         - Project-specific skills\n"
                f"  • conversations/  - Project conversation history\n"
                f"  • logs/           - Project-level logs\n"
                + (
                    f"  • config.yaml     - Project configuration (example)\n"
                    if not minimal
                    else ""
                )
                + f"  • .gitignore      - Git ignore patterns\n\n"
                f"[dim]Next steps:[/dim]\n"
                + (
                    f"  1. Edit config.yaml to customize project settings\n"
                    if not minimal
                    else "  1. Create config.yaml if needed\n"
                )
                + f"  2. Create project-specific constitutions in constitutions/\n"
                f"  3. Add project skills in skills/\n"
                f"  4. Start a project chat with: exobrain chat --project",
                title="Project Initialized",
                border_style="green",
            )
        )

        # Show .gitignore reminder
        root_gitignore = Path.cwd() / ".gitignore"
        if root_gitignore.exists():
            console.print(
                "\n[yellow]ℹ[/yellow] [dim]Consider adding .exobrain/ patterns to your root .gitignore[/dim]"
            )
        else:
            console.print(
                "\n[yellow]ℹ[/yellow] [dim]Consider creating a .gitignore file in your project root[/dim]"
            )

    except Exception as e:
        console.print(f"[red]✗[/red] Failed to initialize .exobrain directory: {e}")
        logger.exception("Failed to initialize project structure")
        raise click.Abort()
