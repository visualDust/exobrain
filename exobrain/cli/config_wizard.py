"""Interactive configuration wizard for ExoBrain."""

import sys
from pathlib import Path

import click
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from exobrain import __version__
from exobrain.config import get_user_config_path

console = Console()


def get_example_config_path() -> Path:
    """Get path to example config file bundled with the package.

    Returns:
        Path to config.example.yaml
    """
    # The example config is now in the exobrain package directory
    package_dir = Path(__file__).parent.parent
    return package_dir / "config.example.yaml"


def load_example_config() -> dict:
    """Load example configuration.

    Returns:
        Example configuration dictionary

    Raises:
        FileNotFoundError: If example config file is not found
    """
    example_config_path = get_example_config_path()

    if not example_config_path.exists():
        raise FileNotFoundError(
            f"Example configuration file not found at: {example_config_path}\n"
            "This is likely a packaging issue. Please report this bug."
        )

    with open(example_config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    return config


def run_config_wizard() -> dict:
    """Run interactive configuration wizard.

    Returns:
        Configuration dictionary
    """
    console.print(
        Panel.fit(
            "[bold cyan]ExoBrain Configuration Wizard[/bold cyan]\n\n"
            "Welcome! Let's set up your AI assistant.\n"
            "I'll ask you a few questions to get started.",
            border_style="cyan",
        )
    )

    # Start with example config as base
    try:
        config = load_example_config()
        console.print("[dim]Loaded base configuration from example[/dim]\n")
    except FileNotFoundError as e:
        console.print(f"[yellow]Warning: {e}[/yellow]")
        console.print("[yellow]Creating minimal configuration instead[/yellow]\n")
        config = {}

    # Update version to current package version
    config["version"] = __version__

    # 1. Model provider selection
    console.print("\n[bold]Step 1: Model Provider[/bold]")
    console.print("Which AI model provider would you like to use?")
    console.print("  [cyan]1[/cyan]) OpenAI (GPT-5, GPT-4o, etc.)")
    console.print("  [cyan]2[/cyan]) Google Gemini (Gemini Pro, Gemini 2.5, etc.)")
    console.print("  [cyan]3[/cyan]) Local models (vLLM, Ollama, etc.)")
    console.print("  [cyan]4[/cyan]) Multiple providers")

    provider_choice = Prompt.ask("\nYour choice", choices=["1", "2", "3", "4"], default="1")

    provider_map = {
        "1": "openai",
        "2": "gemini",
        "3": "local",
        "4": "multiple",
    }
    primary_provider = provider_map[provider_choice]

    # Ensure models config exists
    if "models" not in config:
        config["models"] = {}
    if "providers" not in config["models"]:
        config["models"]["providers"] = {}

    # 2. Configure selected provider(s)
    if primary_provider == "openai" or primary_provider == "multiple":
        console.print("\n[bold]Step 2: OpenAI Configuration[/bold]")

        # Get or create openai provider config
        if "openai" not in config["models"]["providers"]:
            config["models"]["providers"]["openai"] = {}
        openai_config = config["models"]["providers"]["openai"]

        api_key = Prompt.ask(
            "OpenAI API Key (sk-..., or press Enter to use ${OPENAI_API_KEY})",
            default="",
            password=True,
        )
        if api_key:
            openai_config["api_key"] = api_key
        elif "api_key" not in openai_config:
            openai_config["api_key"] = "${OPENAI_API_KEY}"

        base_url = Prompt.ask(
            "OpenAI Base URL", default=openai_config.get("base_url", "https://api.openai.com/v1")
        )
        openai_config["base_url"] = base_url

        if primary_provider == "openai":
            config["models"]["default"] = "openai/gpt-4o"

    if primary_provider == "gemini" or primary_provider == "multiple":
        console.print("\n[bold]Step 2: Google Gemini Configuration[/bold]")

        # Get or create gemini provider config
        if "gemini" not in config["models"]["providers"]:
            config["models"]["providers"]["gemini"] = {}
        gemini_config = config["models"]["providers"]["gemini"]

        api_key = Prompt.ask(
            "Gemini API Key (or press Enter to use ${GOOGLE_API_KEY})", default="", password=True
        )
        if api_key:
            gemini_config["api_key"] = api_key
        elif "api_key" not in gemini_config:
            gemini_config["api_key"] = "${GOOGLE_API_KEY}"

        if primary_provider == "gemini":
            config["models"]["default"] = "gemini/gemini-2.0-flash"

    if primary_provider == "local" or primary_provider == "multiple":
        console.print("\n[bold]Step 2: Local Models Configuration[/bold]")
        console.print("[dim]Make sure Ollama or LM Studio is running[/dim]")

        # Get or create local provider config
        if "local" not in config["models"]["providers"]:
            config["models"]["providers"]["local"] = {}
        local_config = config["models"]["providers"]["local"]

        base_url = Prompt.ask(
            "Local model server URL",
            default=local_config.get("base_url", "http://localhost:8000/v1"),
        )
        local_config["base_url"] = base_url

        model_name = Prompt.ask("Model name", default="llama2")

        if primary_provider == "local":
            config["models"]["default"] = f"local/{model_name}"

    # If multiple, ask for default
    if primary_provider == "multiple":
        console.print("\n[bold]Which provider should be the default?[/bold]")
        providers_configured = list(config["models"]["providers"].keys())
        for i, p in enumerate(providers_configured, 1):
            console.print(f"  [cyan]{i}[/cyan]) {p}")

        default_choice = Prompt.ask(
            "\nDefault provider",
            choices=[str(i) for i in range(1, len(providers_configured) + 1)],
            default="1",
        )

        default_provider = providers_configured[int(default_choice) - 1]

        if default_provider == "openai":
            config["models"]["default"] = "openai/gpt-4o"
        elif default_provider == "gemini":
            config["models"]["default"] = "gemini/gemini-pro"
        elif default_provider == "local":
            config["models"]["default"] = "local/llama2"

    # Agent settings and features are already in example config
    # We can skip asking about them unless user wants advanced configuration
    console.print("\n[bold]Step 3: Additional Settings[/bold]")
    console.print(
        "[dim]Agent, tools, and other settings are pre-configured with sensible defaults[/dim]"
    )
    console.print("[dim]You can modify them later with: exobrain config edit[/dim]")

    # Ensure all required sections exist (in case example config is missing)
    if "agent" not in config:
        config["agent"] = {
            "system_prompt": "You are ExoBrain, a personal AI assistant focused on productivity.",
            "max_iterations": 500,
            "stream": True,
        }
    if "tools" not in config:
        config["tools"] = {
            "file_system": True,
            "web_access": True,
            "shell_execution": True,
            "time_management": True,
        }
    if "skills" not in config:
        config["skills"] = {"enabled": True}
    if "permissions" not in config:
        config["permissions"] = {}
    if "mcp" not in config:
        config["mcp"] = {"servers": []}
    if "memory" not in config:
        config["memory"] = {}
    if "cli" not in config:
        config["cli"] = {}
    if "logging" not in config:
        config["logging"] = {}
    if "performance" not in config:
        config["performance"] = {}

    return config


@click.command(name="init")
def init_config():
    """Initialize ExoBrain configuration with interactive wizard."""
    config_path = get_user_config_path()

    # Check if config already exists
    if config_path.exists():
        overwrite = Confirm.ask(
            f"\n[yellow]Configuration file already exists at:[/yellow]\n{config_path}\n\n"
            "Do you want to overwrite it?",
            default=False,
        )

        if not overwrite:
            console.print("\n[yellow]Configuration unchanged[/yellow]")
            console.print(
                f"[dim]Use 'exobrain config edit' to modify existing configuration[/dim]\n"
            )
            sys.exit(0)

    # Run wizard
    config = run_config_wizard()

    # Ensure directory exists
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Save configuration
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(
            config,
            f,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )

    console.print(
        Panel.fit(
            f"[green]✓ Configuration created successfully![/green]\n\n"
            f"Location: [cyan]{config_path}[/cyan]\n\n"
            f"You can now start using ExoBrain:\n"
            f"  [bold]exobrain chat[/bold]\n\n"
            f"To modify your configuration:\n"
            f"  [bold]exobrain config edit[/bold]\n"
            f"  [bold]exobrain config set <key> <value>[/bold]",
            title="[bold green]Setup Complete[/bold green]",
            border_style="green",
        )
    )
