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

        # Build model list with checkmark for current default and descriptions
        model_lines = []
        for model in available_models:
            # Get description if available
            provider_name, model_name = model.split("/", 1)
            provider_config = config.models.providers.get(provider_name)
            description = ""
            if provider_config:
                description = provider_config.get_model_description(model_name)

            # Format model display
            model_display = model
            if description:
                model_display = f"{model} ({description})"

            # Add checkmark if current default
            if model == config.models.default:
                model_lines.append(f"[green]✓[/green] {model_display}")
            else:
                model_lines.append(f"  {model_display}")

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
    add_to_existing = False
    existing_provider_config = None
    if provider_name in config.models.providers:
        console.print(f"[yellow]Provider '{provider_name}' already exists.[/yellow]")

        # Show existing provider info
        existing_provider_config = config.models.providers[provider_name]
        existing_models = existing_provider_config.get_model_list()
        console.print(f"[dim]Existing models: {', '.join(existing_models)}[/dim]")

        # Ask if user wants to add models or overwrite
        console.print("\nWhat would you like to do?")
        console.print("  1. Add new models to this provider")
        console.print("  2. Overwrite the entire provider configuration")
        console.print("  3. Cancel")

        choice = Prompt.ask("Choose an option", choices=["1", "2", "3"], default="1")

        if choice == "3":
            console.print("[yellow]Cancelled.[/yellow]")
            ctx.exit(0)
        elif choice == "1":
            add_to_existing = True
            console.print("[cyan]Will add new models to existing provider.[/cyan]")
        else:  # choice == "2"
            console.print("[yellow]Will overwrite existing provider configuration.[/yellow]")
            add_to_existing = False

    # Step 2: Base URL (skip if adding to existing)
    if add_to_existing and existing_provider_config:
        base_url = existing_provider_config.base_url or ""
        console.print(f"\n[dim]Using existing base URL: {base_url}[/dim]")
    else:
        base_url = Prompt.ask(
            "Base URL (e.g., https://api.example.com/v1)", default="https://api.openai.com/v1"
        ).strip()

        # Ensure base URL ends properly
        if not base_url.startswith("http"):
            console.print(
                "[yellow]Warning: Base URL should start with http:// or https://[/yellow]"
            )
            base_url = "https://" + base_url

    # Step 3: API Key (skip if adding to existing)
    if add_to_existing and existing_provider_config:
        api_key = existing_provider_config.api_key or ""
        console.print(f"[dim]Using existing API key configuration[/dim]")
    else:
        console.print("\n[bold]Step 2: Authentication[/bold]")
        console.print("[dim]Tip: Use ${ENV_VAR_NAME} to reference environment variables[/dim]")

        api_key = Prompt.ask(
            f"API key (e.g., ${{CUSTOM_API_KEY}})",
            default=f"${{{provider_name.upper().replace('-', '_')}_API_KEY}}",
            password=False,  # Don't hide, as it's often an env var placeholder
        ).strip()

    # Step 4: Models
    step_label = "Step 3" if add_to_existing else "Step 3"
    console.print(f"\n[bold]{step_label}: Model Names[/bold]")
    console.print(
        "[dim]Enter model names one by one. You can optionally add a description and default parameters.[/dim]"
    )
    console.print("[dim]Press Enter on an empty model name to finish.[/dim]")

    models_list = []
    model_num = 1
    while True:
        model_name_input = Prompt.ask(
            f"Model #{model_num} name (or press Enter to finish)", default=""
        ).strip()

        if not model_name_input:
            if len(models_list) == 0:
                console.print("[yellow]You must add at least one model.[/yellow]")
                continue
            break

        # Ask for description (optional)
        model_description = Prompt.ask(
            f"  Description for '{model_name_input}' (optional, press Enter to skip)", default=""
        ).strip()

        # Ask for default parameters (optional)
        set_model_params = Confirm.ask(
            f"  Set default parameters for '{model_name_input}'?", default=False
        )

        model_default_params = {}
        if set_model_params:
            temp_input = Prompt.ask("    Temperature (0.0-2.0, or press Enter to skip)", default="")
            if temp_input.strip():
                try:
                    model_default_params["temperature"] = float(temp_input)
                except ValueError:
                    console.print("    [yellow]Invalid temperature value, skipping[/yellow]")

            max_tok_input = Prompt.ask("    Max tokens (or press Enter to skip)", default="")
            if max_tok_input.strip():
                try:
                    model_default_params["max_tokens"] = int(max_tok_input)
                except ValueError:
                    console.print("    [yellow]Invalid max_tokens value, skipping[/yellow]")

        # Build model entry
        if model_description or model_default_params:
            model_entry = {"name": model_name_input}
            if model_description:
                model_entry["description"] = model_description
            if model_default_params:
                model_entry["default_params"] = model_default_params
            models_list.append(model_entry)

            # Display confirmation
            parts = [f"Added: {model_name_input}"]
            if model_description:
                parts.append(f"({model_description})")
            if model_default_params:
                params_str = ", ".join(f"{k}={v}" for k, v in model_default_params.items())
                parts.append(f"[{params_str}]")
            console.print(f"  [green]✓[/green] {' '.join(parts)}")
        else:
            models_list.append(model_name_input)
            console.print(f"  [green]✓[/green] Added: {model_name_input}")

        model_num += 1

    # Summary
    console.print("\n[bold]Summary:[/bold]")
    console.print(f"  Provider: [cyan]{provider_name}[/cyan]")
    if not add_to_existing:
        console.print(f"  Base URL: [cyan]{base_url}[/cyan]")
        console.print(f"  API Key: [cyan]{api_key}[/cyan]")

    # Format models list for display
    models_display = []
    for m in models_list:
        if isinstance(m, str):
            models_display.append(m)
        elif isinstance(m, dict):
            name = m.get("name", "")
            desc = m.get("description", "")
            params = m.get("default_params", {})

            parts = [name]
            if desc:
                parts.append(f"({desc})")
            if params:
                params_str = ", ".join(f"{k}={v}" for k, v in params.items())
                parts.append(f"[{params_str}]")

            models_display.append(" ".join(parts))
    console.print(f"  Models: [cyan]{', '.join(models_display)}[/cyan]")

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

    # Build the provider configuration
    if add_to_existing and provider_name in config_data["models"]["providers"]:
        # Merge with existing provider configuration
        existing_config = config_data["models"]["providers"][provider_name]

        # Merge models lists (avoid duplicates by name)
        existing_models_raw = existing_config.get("models", [])
        merged_models = list(existing_models_raw)  # Copy existing models

        # Get existing model names for duplicate check
        existing_model_names = set()
        for m in existing_models_raw:
            if isinstance(m, str):
                existing_model_names.add(m)
            elif isinstance(m, dict) and "name" in m:
                existing_model_names.add(m["name"])

        # Add new models (skip duplicates)
        for new_model in models_list:
            model_name = new_model if isinstance(new_model, str) else new_model.get("name")
            if model_name not in existing_model_names:
                merged_models.append(new_model)
            else:
                console.print(f"[yellow]Skipping duplicate model: {model_name}[/yellow]")

        existing_config["models"] = merged_models
        console.print(
            f"[green]Merged {len(models_list)} new model(s) into existing provider.[/green]"
        )
    else:
        # Create new provider configuration
        provider_config = {
            "api_key": api_key,
            "base_url": base_url,
            "models": models_list,
        }

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

    # Format model names for display
    model_names = []
    for m in models_list:
        if isinstance(m, str):
            model_names.append(m)
        elif isinstance(m, dict):
            model_names.append(m.get("name", ""))

    action_text = "merged successfully" if add_to_existing else "added successfully"
    console.print(
        Panel.fit(
            f"[green]✓ Provider '{provider_name}' {action_text}![/green]\n\n"
            f"Config file: [cyan]{config_path}[/cyan]\n\n"
            f"Available models:\n"
            + "\n".join(f"  • {provider_name}/{model}" for model in model_names),
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
