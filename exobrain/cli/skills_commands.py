"""Commands for managing skills."""

import logging

import click
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from exobrain.config import Config

console = Console()
logger = logging.getLogger(__name__)


@click.group(invoke_without_command=True)
@click.option(
    "--scope",
    "-s",
    type=click.Choice(["user", "project"]),
    default="user",
    help="Configuration scope: 'user' for global config, 'project' for project-level config",
)
@click.pass_context
def skills(ctx: click.Context, scope: str) -> None:
    """Manage skills.

    By default, launches the TUI for managing skills.
    Use subcommands for specific actions.
    """
    # If no subcommand is provided, launch TUI
    if ctx.invoked_subcommand is None:
        from pathlib import Path

        from exobrain.cli.tui.skills import SkillsApp
        from exobrain.skills.loader import load_default_skills

        config: Config = ctx.obj["config"]

        try:
            # Check if in project directory for project scope
            if scope == "project":
                project_config = Path.cwd() / ".exobrain"
                if not project_config.exists():
                    console.print(
                        "[yellow]No .exobrain directory found in current directory.[/yellow]\n"
                        "[dim]Project scope requires a .exobrain directory.[/dim]\n"
                        "[dim]Use --scope user for global configuration.[/dim]"
                    )
                    return

            # Load skills
            loader = load_default_skills(config)

            # Launch TUI
            app = SkillsApp(config, loader, config_scope=scope)
            app.run()

        except Exception as e:
            console.print(f"[red]Error launching skills manager: {e}[/red]")
            logger.exception("Error launching skills manager")


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


@skills.command("enable")
@click.argument("skill_names", nargs=-1, required=True)
@click.option(
    "--scope",
    "-s",
    type=click.Choice(["user", "project"]),
    default="user",
    help="Configuration scope: 'user' for global config, 'project' for project-level config",
)
@click.pass_context
def skills_enable(ctx: click.Context, skill_names: tuple[str, ...], scope: str) -> None:
    """Enable one or more skills."""
    from pathlib import Path

    import yaml

    from exobrain.config import get_user_config_path
    from exobrain.skills.loader import load_default_skills

    config: Config = ctx.obj["config"]

    try:
        # Determine config file path
        if scope == "project":
            config_path = Path.cwd() / ".exobrain" / "config.yaml"
            if not config_path.parent.exists():
                console.print(
                    "[red]No .exobrain directory found. Use --scope user for global config.[/red]"
                )
                return
        else:
            config_path = get_user_config_path()

        # Ensure directory exists
        config_path.parent.mkdir(parents=True, exist_ok=True)

        # Load existing config
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                config_data = yaml.safe_load(f) or {}
        else:
            config_data = {}

        # Get disabled skills list
        if "skills" not in config_data:
            config_data["skills"] = {}
        if "disabled_skills" not in config_data["skills"]:
            config_data["skills"]["disabled_skills"] = []

        disabled_skills = set(config_data["skills"]["disabled_skills"])

        # Load skills to verify they exist
        loader = load_default_skills(config)
        all_skills = loader.get_all_skills()

        # Enable skills (remove from disabled list)
        enabled = []
        not_found = []
        for skill_name in skill_names:
            if skill_name not in all_skills:
                not_found.append(skill_name)
                continue

            if skill_name in disabled_skills:
                disabled_skills.discard(skill_name)
                enabled.append(skill_name)
            else:
                console.print(f"[yellow]Skill already enabled: {skill_name}[/yellow]")

        # Update config
        config_data["skills"]["disabled_skills"] = sorted(list(disabled_skills))

        # Save config
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f, default_flow_style=False, sort_keys=False)

        # Report results
        if enabled:
            console.print(f"\n[green]✓ Enabled {len(enabled)} skill(s):[/green]")
            for skill in enabled:
                console.print(f"  • {skill}")

        if not_found:
            console.print(f"\n[red]✗ Skills not found:[/red]")
            for skill in not_found:
                console.print(f"  • {skill}")

        if enabled:
            console.print(f"\n[dim]Saved to: {config_path}[/dim]")

    except Exception as e:
        console.print(f"[red]Error enabling skills: {e}[/red]")
        logger.exception("Error enabling skills")


@skills.command("disable")
@click.argument("skill_names", nargs=-1, required=True)
@click.option(
    "--scope",
    "-s",
    type=click.Choice(["user", "project"]),
    default="user",
    help="Configuration scope: 'user' for global config, 'project' for project-level config",
)
@click.pass_context
def skills_disable(ctx: click.Context, skill_names: tuple[str, ...], scope: str) -> None:
    """Disable one or more skills."""
    from pathlib import Path

    import yaml

    from exobrain.config import get_user_config_path
    from exobrain.skills.loader import load_default_skills

    config: Config = ctx.obj["config"]

    try:
        # Determine config file path
        if scope == "project":
            config_path = Path.cwd() / ".exobrain" / "config.yaml"
            if not config_path.parent.exists():
                console.print(
                    "[red]No .exobrain directory found. Use --scope user for global config.[/red]"
                )
                return
        else:
            config_path = get_user_config_path()

        # Ensure directory exists
        config_path.parent.mkdir(parents=True, exist_ok=True)

        # Load existing config
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                config_data = yaml.safe_load(f) or {}
        else:
            config_data = {}

        # Get disabled skills list
        if "skills" not in config_data:
            config_data["skills"] = {}
        if "disabled_skills" not in config_data["skills"]:
            config_data["skills"]["disabled_skills"] = []

        disabled_skills = set(config_data["skills"]["disabled_skills"])

        # Load skills to verify they exist
        loader = load_default_skills(config)
        all_skills = loader.get_all_skills()

        # Disable skills (add to disabled list)
        disabled = []
        not_found = []
        for skill_name in skill_names:
            if skill_name not in all_skills:
                not_found.append(skill_name)
                continue

            if skill_name not in disabled_skills:
                disabled_skills.add(skill_name)
                disabled.append(skill_name)
            else:
                console.print(f"[yellow]Skill already disabled: {skill_name}[/yellow]")

        # Update config
        config_data["skills"]["disabled_skills"] = sorted(list(disabled_skills))

        # Save config
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f, default_flow_style=False, sort_keys=False)

        # Report results
        if disabled:
            console.print(f"\n[yellow]Disabled {len(disabled)} skill(s):[/yellow]")
            for skill in disabled:
                console.print(f"  • {skill}")

        if not_found:
            console.print(f"\n[red]✗ Skills not found:[/red]")
            for skill in not_found:
                console.print(f"  • {skill}")

        if disabled:
            console.print(f"\n[dim]Saved to: {config_path}[/dim]")

    except Exception as e:
        console.print(f"[red]Error disabling skills: {e}[/red]")
        logger.exception("Error disabling skills")
