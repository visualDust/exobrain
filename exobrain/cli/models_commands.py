"""Commands for managing models and providers."""

import logging

import click
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from exobrain.config import Config
from exobrain.providers.factory import ModelFactory

console = Console()
logger = logging.getLogger(__name__)


@click.group()
def models() -> None:
    """Manage models."""


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
    from exobrain.cli.config_commands import detect_config_files

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


@models.command("add")
@click.pass_context
def models_add(ctx: click.Context) -> None:
    """Add a new model provider with interactive wizard.

    Example:
        exobrain models add  # Interactive wizard
    """
    from exobrain.cli.config_commands import detect_config_files

    config: Config = ctx.obj["config"]

    console.print(
        Panel.fit(
            "[bold cyan]Add Model Provider[/bold cyan]\n\n"
            "This wizard will help you add a third-party API provider.\n"
            "You can use any OpenAI-compatible API endpoint.",
            border_style="cyan",
        )
    )

    # Step 1: Provider name
    console.print("\n[bold]Step 1: Provider Information[/bold]")
    provider_name = (
        Prompt.ask("How would you call it? (e.g., custom-openai)", default="custom-provider")
        .strip()
        .lower()
        .replace(" ", "-")
    )

    # Check if provider already exists
    if provider_name in config.models.providers:
        console.print(f"[yellow]Warning: Provider '{provider_name}' already exists.[/yellow]")
        overwrite = Confirm.ask("Do you want to overwrite it?", default=False)
        if not overwrite:
            console.print("[yellow]Cancelled.[/yellow]")
            ctx.exit(0)

    # Step 2: Base URL
    base_url = Prompt.ask(
        "Base URL (e.g., https://api.example.com/v1)", default="https://api.openai.com/v1"
    ).strip()

    # Ensure base URL ends properly
    if not base_url.startswith("http"):
        console.print("[yellow]Warning: Base URL should start with http:// or https://[/yellow]")
        base_url = "https://" + base_url

    # Step 3: API Key
    console.print("\n[bold]Step 2: Authentication[/bold]")
    console.print("[dim]Tip: Use ${ENV_VAR_NAME} to reference environment variables[/dim]")

    api_key = Prompt.ask(
        f"API key (e.g., ${{CUSTOM_API_KEY}})",
        default=f"${{{provider_name.upper().replace('-', '_')}_API_KEY}}",
        password=False,  # Don't hide, as it's often an env var placeholder
    ).strip()

    # Step 4: Models
    console.print("\n[bold]Step 3: Model Names[/bold]")
    console.print("[dim]Enter model names one by one. (e.g. GPT-5)[/dim]")
    console.print("[dim]Press Enter on an empty line to finish.[/dim]")

    models_list = []
    model_num = 1
    while True:
        model_name_input = Prompt.ask(
            f"Model #{model_num} (or press Enter to finish)", default=""
        ).strip()

        if not model_name_input:
            if len(models_list) == 0:
                console.print("[yellow]You must add at least one model.[/yellow]")
                continue
            break

        models_list.append(model_name_input)
        console.print(f"  [green]✓[/green] Added: {model_name_input}")
        model_num += 1

    # Step 5: Default parameters (optional)
    console.print("\n[bold]Step 4: Default Parameters (Optional)[/bold]")
    console.print("[dim]Leave empty to not set a parameter[/dim]")
    set_defaults = Confirm.ask(
        "Would you like to set default temperature and/or max_tokens?", default=False
    )

    default_params = {}
    if set_defaults:
        temp_input = Prompt.ask("Temperature (0.0-2.0, or press Enter to skip)", default="")
        if temp_input.strip():
            try:
                default_params["temperature"] = float(temp_input)
            except ValueError:
                console.print("[yellow]Invalid temperature value, skipping[/yellow]")

        max_tok_input = Prompt.ask("Max tokens (or press Enter to skip)", default="")
        if max_tok_input.strip():
            try:
                default_params["max_tokens"] = int(max_tok_input)
            except ValueError:
                console.print("[yellow]Invalid max_tokens value, skipping[/yellow]")

    # Summary
    console.print("\n[bold]Summary:[/bold]")
    console.print(f"  Provider: [cyan]{provider_name}[/cyan]")
    console.print(f"  Base URL: [cyan]{base_url}[/cyan]")
    console.print(f"  API Key: [cyan]{api_key}[/cyan]")
    console.print(f"  Models: [cyan]{', '.join(models_list)}[/cyan]")

    if default_params:
        if "temperature" in default_params:
            console.print(f"  Temperature: [cyan]{default_params['temperature']}[/cyan]")
        if "max_tokens" in default_params:
            console.print(f"  Max Tokens: [cyan]{default_params['max_tokens']}[/cyan]")
    else:
        console.print(f"  Default Params: [dim]None (will use API defaults)[/dim]")

    # Confirm
    console.print()
    if not Confirm.ask("Add this provider to your configuration?", default=True):
        console.print("[yellow]Cancelled.[/yellow]")
        ctx.exit(0)

    # Detect and select config file
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

    # Load config
    with open(config_path, "r", encoding="utf-8") as f:
        config_data = yaml.safe_load(f) or {}

    # Ensure models.providers section exists
    if "models" not in config_data:
        config_data["models"] = {}
    if "providers" not in config_data["models"]:
        config_data["models"]["providers"] = {}

    # Add the new provider
    provider_config = {
        "api_key": api_key,
        "base_url": base_url,
        "models": models_list,
    }

    # Only add default_params if it's not empty
    if default_params:
        provider_config["default_params"] = default_params

    config_data["models"]["providers"][provider_name] = provider_config

    # Save config
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(
            config_data,
            f,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        )

    # Show success message
    console.print()
    console.print(
        Panel.fit(
            f"[green]✓ Provider '{provider_name}' added successfully![/green]\n\n"
            f"Config file: [cyan]{config_path}[/cyan]\n\n"
            f"Available models:\n"
            + "\n".join(f"  • {provider_name}/{model}" for model in models_list),
            title="[bold green]Success[/bold green]",
            border_style="green",
        )
    )

    # Offer to test the connection
    console.print()
    test_connection = Confirm.ask(
        "Would you like to test the connection to this provider?", default=True
    )

    if test_connection:
        console.print(f"\n[cyan]Testing connection to {provider_name}...[/cyan]")

        # Try to initialize the provider and make a simple request
        try:
            # Reload config to get the new provider
            from exobrain.config import load_config

            new_config, _ = load_config()
            factory = ModelFactory(new_config)

            # Try to get the provider
            test_model = f"{provider_name}/{models_list[0]}"
            console.print(f"[dim]Testing with model: {test_model}[/dim]")

            # This will validate the provider configuration
            factory.get_provider(test_model)

            console.print(f"[green]✓ Provider initialized successfully![/green]")
            console.print(f"\n[dim]To use this provider, run:[/dim]")
            console.print(f"[bold]  exobrain models use {test_model}[/bold]")
            console.print(f"[dim]Or:[/dim]")
            console.print(f"[bold]  exobrain chat --model {test_model}[/bold]")

        except Exception as e:
            console.print(f"[red]✗ Connection test failed: {e}[/red]")
            console.print("[yellow]Please check your configuration and API key.[/yellow]")
    else:
        console.print(f"\n[dim]To use this provider, run:[/dim]")
        console.print(f"[bold]  exobrain models use {provider_name}/{models_list[0]}[/bold]")
