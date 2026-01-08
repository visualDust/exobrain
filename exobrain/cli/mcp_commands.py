"""Commands for managing MCP servers."""

import logging
from pathlib import Path
from typing import Any

import click
import yaml
from rich.console import Console
from rich.table import Table

from exobrain.cli.config_commands import detect_config_files, show_config_context
from exobrain.config import Config, get_user_config_path

console = Console()
logger = logging.getLogger(__name__)


def _get_mcp_config_target_path() -> Path:
    """Choose a config file to modify for MCP operations."""
    configs = detect_config_files()
    return configs.get("project_level") or configs.get("user") or get_user_config_path()


def _load_yaml_config(path: Path) -> dict[str, Any]:
    """Load YAML config from path or return empty dict."""
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def _save_yaml_config(path: Path, data: dict[str, Any]) -> None:
    """Persist YAML config to path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


def _toggle_mcp_server(name: str, enabled: bool) -> bool:
    """Enable/disable a server in the writable config file."""
    target_path = _get_mcp_config_target_path()
    console.print()
    show_config_context("Modifying", target_path)
    console.print()

    data = _load_yaml_config(target_path)
    mcp_cfg = data.setdefault("mcp", {})
    # Ensure global switch follows any enabled server
    if enabled:
        mcp_cfg["enabled"] = True

    if name == "context7":
        ctx7_cfg = mcp_cfg.setdefault("context7", {})
        ctx7_cfg["enabled"] = enabled
        if not enabled:
            # If everything is disabled, flip global switch off
            all_disabled = not any(
                s.get("enabled", False) for s in mcp_cfg.get("servers", [])
            ) and not ctx7_cfg.get("enabled", False)
            if all_disabled:
                mcp_cfg["enabled"] = False
        _save_yaml_config(target_path, data)
        return True

    servers = mcp_cfg.setdefault("servers", [])
    for server in servers:
        if server.get("name") == name:
            server["enabled"] = enabled
            if not enabled:
                ctx7_enabled = mcp_cfg.get("context7", {}).get("enabled", False)
                any_server_enabled = any(s.get("enabled", False) for s in servers)
                if not ctx7_enabled and not any_server_enabled:
                    mcp_cfg["enabled"] = False
            _save_yaml_config(target_path, data)
            return True

    console.print(f"[red]Server '{name}' not found in mcp.servers. Please add it first.[/red]")
    return False


@click.group()
@click.pass_context
def mcp(ctx: click.Context) -> None:
    """Manage MCP servers (including Context7)."""


@mcp.command("list")
@click.pass_context
def mcp_list(ctx: click.Context) -> None:
    """List configured MCP servers."""
    config: Config = ctx.obj["config"]
    cfg_metadata = ctx.obj.get("config_metadata", {})
    servers = getattr(config.mcp, "servers", []) if getattr(config, "mcp", None) else []

    table = Table(title="MCP Servers", show_header=True, header_style="bold cyan")
    table.add_column("Name")
    table.add_column("Enabled", justify="center")
    table.add_column("Transport/Type")
    table.add_column("Source")

    primary_source = cfg_metadata.get("primary_source", ("default", ""))
    source_label = primary_source[1] or primary_source[0]

    for server in servers:
        name = server.get("name", "<unnamed>")
        enabled = server.get("enabled", True)
        transport = (
            server.get("transport")
            or ("stdio" if server.get("command") else None)
            or ("http" if server.get("url") else "custom")
        )
        table.add_row(name, "✅" if enabled else "❌", transport, source_label)

    # Context7 as a built-in MCP-style service
    ctx7_cfg = getattr(config.mcp, "context7", {}) if getattr(config, "mcp", None) else {}
    if ctx7_cfg:
        table.add_row(
            "context7",
            "✅" if ctx7_cfg.get("enabled") else "❌",
            "http",
            source_label,
        )

    console.print(table)


@mcp.command("enable")
@click.argument("name")
def mcp_enable(name: str) -> None:
    """Enable an MCP server by name (or 'context7')."""
    if _toggle_mcp_server(name, True):
        console.print(f"[green]✓ Enabled MCP server '{name}'[/green]")


@mcp.command("disable")
@click.argument("name")
def mcp_disable(name: str) -> None:
    """Disable an MCP server by name (or 'context7')."""
    if _toggle_mcp_server(name, False):
        console.print(f"[yellow]Disabled MCP server '{name}'[/yellow]")
