"""Commands for managing skills."""

import logging

import click
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from exobrain.config import Config

console = Console()
logger = logging.getLogger(__name__)


@click.group()
def skills() -> None:
    """Manage skills."""


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
