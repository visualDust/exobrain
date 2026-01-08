"""Constitution (personality) management commands for ExoBrain CLI."""

import os
import subprocess
from pathlib import Path
from typing import Optional

import click
import yaml
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from exobrain.config import get_user_config_directory, get_user_config_path

console = Console()


def get_constitutions_directory() -> Path:
    """Get the constitutions directory path in user config folder."""
    return get_user_config_directory() / "constitutions"


def find_constitution_file(name: str) -> Optional[Path]:
    """Find a constitution file by name.

    Search order (lowest to highest priority):
    1. Package built-in constitutions (exobrain/constitutions/<name>.md) - lowest priority
    2. User global constitutions (~/.config/exobrain/constitutions/<name>.md)
    3. Project-level constitutions (./.exobrain/constitutions/<name>.md)
    4. Project constitutions directory (./constitutions/<name>.md)
    5. Project root (./<name>.md or ./CONSTITUTION.md) - highest priority

    Args:
        name: Constitution name (with or without .md extension)

    Returns:
        Path to the constitution file if found, None otherwise
    """
    # Normalize name
    if not name.endswith(".md"):
        name_with_ext = f"{name}.md"
    else:
        name_with_ext = name
        name = name[:-3]

    # Special case: "default" or "CONSTITUTION" refers to project root CONSTITUTION.md
    if name.lower() in ["default", "constitution"]:
        project_constitution = Path("CONSTITUTION.md")
        if project_constitution.exists():
            return project_constitution.resolve()

    # Search in priority order (return the highest priority match)
    candidates = []

    # 1. Package built-in constitutions (lowest priority)
    try:
        import exobrain

        package_dir = Path(exobrain.__file__).parent
        package_constitution = package_dir / "constitutions" / name_with_ext
        if package_constitution.exists():
            candidates.append(("package", package_constitution.resolve()))
    except Exception:
        pass

    # 2. User global constitutions directory
    user_constitution = get_constitutions_directory() / name_with_ext
    if user_constitution.exists():
        candidates.append(("user", user_constitution))

    # 3. Project-level constitutions directory (.exobrain/constitutions/)
    project_level_constitution = Path(".exobrain") / "constitutions" / name_with_ext
    if project_level_constitution.exists():
        candidates.append(("project-level", project_level_constitution.resolve()))

    # 4. Project constitutions directory (./constitutions/)
    project_dir_constitution = Path("constitutions") / name_with_ext
    if project_dir_constitution.exists():
        candidates.append(("project-dir", project_dir_constitution.resolve()))

    # 5. Project root (./<name>.md)
    project_root_constitution = Path(name_with_ext)
    if project_root_constitution.exists():
        candidates.append(("project-root", project_root_constitution.resolve()))

    # Return the highest priority match (last in list)
    if candidates:
        return candidates[-1][1]

    return None


def list_available_constitutions() -> dict[str, list[Path]]:
    """List all available constitution files.

    Returns:
        Dictionary with keys: "user", "project-level", "builtin", "package"
    """
    constitutions = {"user": [], "project-level": [], "builtin": [], "package": []}

    # Package built-in constitutions (exobrain/constitutions/)
    try:
        import exobrain

        package_dir = Path(exobrain.__file__).parent
        package_constitutions_dir = package_dir / "constitutions"
        if package_constitutions_dir.exists():
            constitutions["package"] = sorted(package_constitutions_dir.glob("*.md"))
    except Exception:
        pass

    # User global constitutions
    user_dir = get_constitutions_directory()
    if user_dir.exists():
        constitutions["user"] = sorted(user_dir.glob("*.md"))

    # Project-level constitutions (.exobrain/constitutions/)
    project_level_dir = Path(".exobrain") / "constitutions"
    if project_level_dir.exists():
        constitutions["project-level"] = sorted(project_level_dir.glob("*.md"))

    # Project constitutions directory (./constitutions/)
    project_dir = Path("constitutions")
    if project_dir.exists():
        constitutions["builtin"].extend(project_dir.glob("*.md"))

    # Default CONSTITUTION.md in project root
    default_constitution = Path("CONSTITUTION.md")
    if default_constitution.exists():
        constitutions["builtin"].append(default_constitution)

    constitutions["builtin"] = sorted(set(constitutions["builtin"]))

    return constitutions


def is_builtin_constitution(path: Path) -> bool:
    """Check if a constitution is a built-in (package) constitution.

    Args:
        path: Path to the constitution file

    Returns:
        True if the constitution is in the package constitutions directory
    """
    try:
        import exobrain

        package_dir = Path(exobrain.__file__).parent
        package_constitutions_dir = package_dir / "constitutions"

        # Resolve paths for comparison
        resolved_path = path.resolve()
        resolved_package_dir = package_constitutions_dir.resolve()

        # Check if the constitution is in the package directory
        try:
            resolved_path.relative_to(resolved_package_dir)
            return True
        except ValueError:
            return False
    except Exception:
        return False


def get_current_constitution() -> Optional[str]:
    """Get the currently active constitution file path from config.

    Returns:
        Constitution file path as string, or None if not configured
    """
    config_path = get_user_config_path()
    if not config_path.exists():
        # Fallback to project config
        config_path = Path("config.yaml")
        if not config_path.exists():
            return None

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config_data = yaml.safe_load(f) or {}

        return config_data.get("agent", {}).get("constitution_file")
    except Exception as e:
        console.print(f"[yellow]Warning: Failed to read config: {e}[/yellow]")
        return None


@click.group(name="constitution")
def constitution_group():
    """Manage agent constitutions (personalities)."""


@constitution_group.command()
def list():
    """List all available constitutions."""
    constitutions = list_available_constitutions()
    current = get_current_constitution()

    # Default to builtin-default if not specified
    if not current or current == "":
        current = "builtin-default"

    table = Table(title="Available Constitutions", box=box.ROUNDED)
    table.add_column("Name", style="cyan")
    table.add_column("Type", style="magenta")
    table.add_column("Path", style="dim")
    table.add_column("Active", justify="center")

    # Add package built-in constitutions (highest priority in display)
    for path in constitutions["package"]:
        name = path.stem
        # Check if current matches: exact name, name with .md, or resolved path
        is_active = ""
        if current:
            if current == name or current == f"{name}.md":
                is_active = "✓"
            # Check resolved path for absolute paths
            elif Path(current).is_absolute() and Path(current).resolve() == path.resolve():
                is_active = "✓"

        table.add_row(name, "builtin", "builtin", is_active)

    # Add project constitutions
    for path in constitutions["builtin"]:
        name = "default" if path.name == "CONSTITUTION.md" else path.stem
        is_active = "✓" if current and Path(current).resolve() == path.resolve() else ""
        table.add_row(name, "project", str(path), is_active)

    # Add project-level constitutions
    for path in constitutions["project-level"]:
        name = path.stem
        is_active = "✓" if current and Path(current).resolve() == path.resolve() else ""
        table.add_row(name, "project-level", str(path), is_active)

    # Add user global constitutions
    for path in constitutions["user"]:
        name = path.stem
        is_active = "✓" if current and Path(current).resolve() == path.resolve() else ""
        table.add_row(name, "user", str(path), is_active)

    console.print()
    console.print(table)
    console.print()

    if current:
        console.print(f"[green]Current constitution:[/green] {current}")
    elif current is None:
        console.print("[yellow]Constitution is deactivated[/yellow]")
        console.print("[dim]Use 'exobrain constitution use <name>' to activate one[/dim]")
    else:
        console.print("[yellow]No constitution configured[/yellow]")
    console.print()


@constitution_group.command()
@click.argument("name", required=False)
def show(name: Optional[str]):
    """Show the content of a constitution.

    If no name is provided, shows the currently active constitution.
    """
    if name:
        constitution_path = find_constitution_file(name)
        if not constitution_path:
            console.print(f"\n[red]✗[/red] Constitution '{name}' not found\n")
            console.print(
                "Run [cyan]exobrain constitution list[/cyan] to see available constitutions.\n"
            )
            return
    else:
        # Show current constitution
        current = get_current_constitution()
        if not current:
            console.print("\n[yellow]No constitution is currently configured[/yellow]\n")
            return

        constitution_path = Path(current)
        if not constitution_path.exists():
            console.print(f"\n[red]✗[/red] Configured constitution not found: {current}\n")
            return

    # Read and display
    try:
        with open(constitution_path, "r", encoding="utf-8") as f:
            content = f.read()

        syntax = Syntax(content, "markdown", theme="monokai", line_numbers=False)

        title = f"Constitution: {constitution_path.stem}"
        panel = Panel(syntax, title=title, border_style="cyan", expand=False)

        console.print()
        console.print(panel)
        console.print(f"\n[dim]Path: {constitution_path}[/dim]\n")

    except Exception as e:
        console.print(f"\n[red]✗[/red] Failed to read constitution: {e}\n")


@constitution_group.command()
@click.argument("name")
def use(name: str):
    """Switch to a different constitution (personality).

    This updates the agent.constitution_file in your user configuration.
    """
    # Find the constitution file
    constitution_path = find_constitution_file(name)

    if not constitution_path:
        console.print(f"\n[red]✗[/red] Constitution '{name}' not found\n")
        console.print(
            "Run [cyan]exobrain constitution list[/cyan] to see available constitutions.\n"
        )
        return

    # Update user config
    config_path = get_user_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Load existing config or create empty
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config_data = yaml.safe_load(f) or {}
    else:
        config_data = {}

    # Update agent.constitution_file
    if "agent" not in config_data:
        config_data["agent"] = {}

    # For built-in constitutions, save just the name (without .md extension)
    # This makes the config portable and cleaner
    if is_builtin_constitution(constitution_path):
        config_data["agent"]["constitution_file"] = constitution_path.stem
    else:
        config_data["agent"]["constitution_file"] = str(constitution_path)

    # Save config
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(
            config_data,
            f,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )

    console.print(f"\n[green]✓[/green] Switched to constitution: [cyan]{name}[/cyan]")
    console.print(f"[dim]Path: {constitution_path}[/dim]\n")


@constitution_group.command()
@click.argument("name")
@click.option(
    "--template",
    "-t",
    help="Template to use (default, current, or path to a file)",
)
def create(name: str, template: Optional[str]):
    """Create a new constitution file.

    Creates a new constitution in the user constitutions directory.
    """
    # Normalize name
    if not name.endswith(".md"):
        filename = f"{name}.md"
    else:
        filename = name

    # Target path
    constitutions_dir = get_constitutions_directory()
    constitutions_dir.mkdir(parents=True, exist_ok=True)

    target_path = constitutions_dir / filename

    if target_path.exists():
        console.print(
            f"\n[yellow]⚠[/yellow] Constitution '{name}' already exists at: {target_path}"
        )
        if not click.confirm("Overwrite?", default=False):
            console.print("[dim]Cancelled[/dim]\n")
            return

    # Determine template source
    template_content = None

    if template:
        if template == "default":
            # Use project CONSTITUTION.md
            default_path = Path("CONSTITUTION.md")
            if default_path.exists():
                with open(default_path, "r", encoding="utf-8") as f:
                    template_content = f.read()
        elif template == "current":
            # Use currently active constitution
            current = get_current_constitution()
            if current and Path(current).exists():
                with open(current, "r", encoding="utf-8") as f:
                    template_content = f.read()
        else:
            # Use specified file
            template_path = Path(template)
            if template_path.exists():
                with open(template_path, "r", encoding="utf-8") as f:
                    template_content = f.read()
            else:
                console.print(f"[yellow]Warning: Template file not found: {template}[/yellow]")

    # Fallback to default template
    if template_content is None:
        template_content = f"""# {name.replace('-', ' ').replace('_', ' ').title()} Constitution

This constitution defines the personality and behavior of ExoBrain for this profile.

---

## Core Identity

Define who the AI assistant is in this personality mode.

## Values

What principles guide this personality?

## Communication Style

How should the AI communicate?

## Behavior Guidelines

Specific guidelines for this personality.

---

*Created: {Path(__file__).parent.parent.parent}*
*Customize this constitution to match your needs*
"""

    # Write the file
    with open(target_path, "w", encoding="utf-8") as f:
        f.write(template_content)

    console.print(f"\n[green]✓[/green] Created new constitution: [cyan]{name}[/cyan]")
    console.print(f"[dim]Path: {target_path}[/dim]\n")

    # Ask if user wants to edit
    if click.confirm("Edit now?", default=True):
        edit_constitution(target_path)


def edit_constitution(path: Path):
    """Open constitution file in editor."""
    editor = os.environ.get("EDITOR", "vim")

    try:
        subprocess.run([editor, str(path)], check=True)
        console.print(f"\n[green]✓[/green] Constitution edited\n")
    except subprocess.CalledProcessError:
        console.print(f"\n[yellow]⚠[/yellow] Editor exited with error\n")
    except FileNotFoundError:
        console.print(f"\n[red]✗[/red] Editor not found: {editor}\n")
        console.print(f"Set the EDITOR environment variable to your preferred editor.\n")


@constitution_group.command()
@click.argument("name", required=False)
def edit(name: Optional[str]):
    """Edit a constitution file.

    If no name is provided, edits the currently active constitution.
    Built-in constitutions cannot be edited directly - create a copy instead.
    """
    if name:
        constitution_path = find_constitution_file(name)
        if not constitution_path:
            console.print(f"\n[red]✗[/red] Constitution '{name}' not found\n")
            console.print(
                "Run [cyan]exobrain constitution list[/cyan] to see available constitutions.\n"
            )
            return
    else:
        # Edit current constitution
        current = get_current_constitution()
        if not current:
            console.print("\n[yellow]No constitution is currently configured[/yellow]\n")
            return

        constitution_path = Path(current)
        if not constitution_path.exists():
            console.print(f"\n[red]✗[/red] Configured constitution not found: {current}\n")
            return

    # Check if it's a built-in constitution
    if is_builtin_constitution(constitution_path):
        console.print(
            f"\n[yellow]⚠[/yellow] Cannot edit built-in constitution: {constitution_path.stem}\n"
        )
        console.print("Built-in constitutions are read-only. To customize, create a copy:\n")
        console.print(
            f"  [cyan]exobrain constitution create my-{constitution_path.stem} --template {constitution_path}[/cyan]\n"
        )
        return

    edit_constitution(constitution_path)


@constitution_group.command()
def deactivate():
    """Deactivate constitution (no personality will be sent to the model).

    This removes the constitution_file setting, so the agent will use only
    the basic system_prompt without any personality/behavior guidelines.
    """
    config_path = get_user_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Load existing config or create empty
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config_data = yaml.safe_load(f) or {}
    else:
        config_data = {}

    # Remove or set to None
    if "agent" not in config_data:
        config_data["agent"] = {}

    # Set to None/null to deactivate
    config_data["agent"]["constitution_file"] = None

    # Save config
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(
            config_data,
            f,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )

    console.print("\n[green]✓[/green] Constitution deactivated")
    console.print(
        "[dim]The agent will use only the basic system_prompt without personality guidelines.[/dim]\n"
    )


@constitution_group.command()
def path():
    """Show the path to the constitutions directory."""
    constitutions_dir = get_constitutions_directory()
    exists = constitutions_dir.exists()
    status = "[green]exists[/green]" if exists else "[yellow]not created yet[/yellow]"

    console.print(f"\n[bold]Constitutions directory:[/bold] {constitutions_dir}")
    console.print(f"[bold]Status:[/bold] {status}\n")

    if not exists:
        if click.confirm("Create directory now?", default=True):
            constitutions_dir.mkdir(parents=True, exist_ok=True)
            console.print(f"[green]✓[/green] Created directory: {constitutions_dir}\n")
