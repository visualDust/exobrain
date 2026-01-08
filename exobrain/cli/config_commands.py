"""Configuration management commands for ExoBrain CLI."""

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import click
import yaml
from rich.console import Console

from exobrain.config import get_user_config_path

console = Console()


def detect_config_files() -> dict[str, Path | None]:
    """Detect all possible configuration file locations.

    Returns:
        Dictionary with keys: 'user', 'project_level'
    """
    return {
        "user": get_user_config_path() if get_user_config_path().exists() else None,
        "project_level": Path.cwd() / ".exobrain" / "config.yaml"
        if (Path.cwd() / ".exobrain" / "config.yaml").exists()
        else None,
    }


def show_config_context(operation: str, target_path: Path) -> None:
    """Show which configuration file is being operated on.

    Args:
        operation: The operation being performed (e.g., "Modifying", "Reading")
        target_path: Path to the configuration file being operated on
    """
    configs = detect_config_files()

    # Determine the type of target config
    if target_path == configs.get("project_level"):
        console.print(
            f"[cyan]ℹ[/cyan] {operation} [bold]project-level[/bold] configuration: [dim]{target_path}[/dim]"
        )
    elif target_path == configs.get("user"):
        console.print(
            f"[cyan]ℹ[/cyan] {operation} [bold]user global[/bold] configuration: [dim]{target_path}[/dim]"
        )

        # Warn if project-level config exists
        if configs["project_level"]:
            console.print(
                f"[yellow]⚠[/yellow] Note: Project-level config exists at [dim]{configs['project_level']}[/dim] "
                f"and will override this setting when running in this directory."
            )


def get_nested_value(data: dict[str, Any], path: list[str]) -> Any:
    """Get a nested value from a dictionary using a path.

    Args:
        data: Dictionary to search
        path: List of keys representing the path (e.g., ['models', 'openai', 'api_key'])

    Returns:
        The value at the path, or None if not found
    """
    current = data
    for key in path:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return None
    return current


def set_nested_value(data: dict[str, Any], path: list[str], value: Any) -> None:
    """Set a nested value in a dictionary using a path.

    Args:
        data: Dictionary to modify
        path: List of keys representing the path
        value: Value to set
    """
    current = data
    for key in path[:-1]:
        if key not in current:
            current[key] = {}
        current = current[key]

    # Convert string values to appropriate types
    if isinstance(value, str):
        if value.lower() in ["true", "false"]:
            value = value.lower() == "true"
        elif value.isdigit():
            value = int(value)
        elif value.replace(".", "", 1).isdigit():
            value = float(value)

    current[path[-1]] = value


def mask_sensitive_value(key: str, value: Any) -> str:
    """Mask sensitive configuration values.

    Args:
        key: Configuration key
        value: Configuration value

    Returns:
        Masked value string
    """
    sensitive_keys = ["api_key", "password", "secret", "token"]

    if any(k in key.lower() for k in sensitive_keys) and isinstance(value, str) and len(value) > 8:
        # Show first 3 and last 3 characters, mask the rest
        return f"{value[:3]}{'*' * (len(value) - 6)}{value[-3:]}"

    return str(value)


@click.group(name="config")
def config_group():
    """Manage ExoBrain configuration."""


@config_group.command()
def path():
    """Show the path to the user configuration file."""
    config_path = get_user_config_path()

    exists = config_path.exists()
    status = "[green]exists[/green]" if exists else "[yellow]not created yet[/yellow]"

    console.print(f"\n[bold]Configuration file path:[/bold] {config_path}")
    console.print(f"[bold]Status:[/bold] {status}\n")

    if exists:
        console.print(f"[dim]Use 'exobrain config edit' to modify the configuration[/dim]")
    else:
        console.print(f"[dim]Use 'exobrain config init' to create the configuration[/dim]")


@config_group.command()
@click.argument("key")
@click.argument("value")
def set(key: str, value: str):
    """Set a configuration value.

    Example:
        exobrain config set openai.api_key "sk-..."
        exobrain config set agent.temperature 0.8
    """
    config_path = get_user_config_path()

    # Show context
    console.print()
    show_config_context("Modifying", config_path)
    console.print()

    # Ensure directory exists
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Load existing config or create empty
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config_data = yaml.safe_load(f) or {}
    else:
        config_data = {}

    # Parse key path
    key_path = key.split(".")

    # Set the value
    set_nested_value(config_data, key_path, value)

    # Save config
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(
            config_data,
            f,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )

    masked_value = mask_sensitive_value(key, value)
    console.print(f"[green]✓[/green] Set [cyan]{key}[/cyan] = [yellow]{masked_value}[/yellow]\n")


@config_group.command()
@click.argument("key")
def get(key: str):
    """Get a configuration value.

    Example:
        exobrain config get openai.api_key
        exobrain config get agent.temperature
    """
    config_path = get_user_config_path()

    if not config_path.exists():
        console.print(f"\n[yellow]Configuration file not found: {config_path}[/yellow]")
        console.print(f"[dim]Use 'exobrain config init' to create it[/dim]\n")
        sys.exit(1)

    # Show context
    console.print()
    show_config_context("Reading from", config_path)
    console.print()

    # Load config
    with open(config_path, "r", encoding="utf-8") as f:
        config_data = yaml.safe_load(f)

    # Parse key path
    key_path = key.split(".")

    # Get the value
    value = get_nested_value(config_data, key_path)

    if value is None:
        console.print(f"[yellow]Key not found: {key}[/yellow]\n")
        sys.exit(1)

    masked_value = mask_sensitive_value(key, value)
    console.print(f"[cyan]{key}[/cyan] = [yellow]{masked_value}[/yellow]\n")


@config_group.command()
def list():
    """List all configuration values."""
    config_path = get_user_config_path()

    if not config_path.exists():
        console.print(f"\n[yellow]Configuration file not found: {config_path}[/yellow]")
        console.print(f"[dim]Use 'exobrain config init' to create it[/dim]\n")
        sys.exit(1)

    # Show context
    console.print()
    show_config_context("Listing", config_path)

    # Load config
    with open(config_path, "r", encoding="utf-8") as f:
        config_data = yaml.safe_load(f)

    def print_dict(data: dict, prefix: str = ""):
        """Recursively print dictionary."""
        for key, value in data.items():
            full_key = f"{prefix}.{key}" if prefix else key

            if isinstance(value, dict):
                console.print(f"\n[bold cyan]{full_key}:[/bold cyan]")
                print_dict(value, full_key)
            else:
                masked_value = mask_sensitive_value(key, value)
                console.print(f"  {full_key}: [yellow]{masked_value}[/yellow]")

    console.print()
    print_dict(config_data)
    console.print()


@config_group.command()
def edit():
    """Open configuration file in default editor."""
    config_path = get_user_config_path()

    if not config_path.exists():
        console.print(f"\n[yellow]Configuration file not found: {config_path}[/yellow]")
        console.print(f"[dim]Use 'exobrain config init' to create it first[/dim]\n")
        sys.exit(1)

    # Show context
    console.print()
    show_config_context("Editing", config_path)

    # Get editor from environment or use default
    editor = os.environ.get("EDITOR", "nano" if sys.platform != "win32" else "notepad")

    console.print(f"\n[cyan]Opening in {editor}...[/cyan]\n")

    try:
        subprocess.run([editor, str(config_path)], check=True)
        console.print(f"\n[green]✓ Configuration file closed[/green]\n")
    except subprocess.CalledProcessError:
        console.print(f"\n[red]Failed to open editor[/red]\n")
        sys.exit(1)
    except FileNotFoundError:
        console.print(f"\n[red]Editor '{editor}' not found[/red]")
        console.print(f"[dim]Set the EDITOR environment variable to your preferred editor[/dim]\n")
        sys.exit(1)


@config_group.command()
@click.confirmation_option(prompt="Are you sure you want to reset the configuration?")
def reset():
    """Reset configuration to defaults."""
    config_path = get_user_config_path()

    if config_path.exists():
        config_path.unlink()
        console.print(f"\n[green]✓ Configuration reset[/green]")
        console.print(f"[dim]Use 'exobrain config init' to create a new configuration[/dim]\n")
    else:
        console.print(f"\n[yellow]Configuration file doesn't exist[/yellow]\n")
