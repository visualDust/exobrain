"""Commands for managing conversation sessions."""

import logging
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table

from exobrain.config import Config
from exobrain.memory.conversations import ConversationManager

console = Console()
logger = logging.getLogger(__name__)


def _get_conversation_manager_for_session(
    session_id: str, config: Any, model_provider: Any
) -> tuple[Any, str] | None:
    """Find the conversation manager that contains the given session.

    Args:
        session_id: Session ID to find
        config: Config object
        model_provider: Model provider instance

    Returns:
        Tuple of (ConversationManager, source_label) or None if not found
    """
    # Try project-level first
    project_conversations_path = Path.cwd() / ".exobrain" / "conversations"
    if project_conversations_path.parent.exists():
        project_manager = ConversationManager(
            storage_path=project_conversations_path,
            model_provider=model_provider,
            save_tool_history=config.memory.save_tool_history,
            tool_content_max_length=config.memory.tool_content_max_length,
        )
        if project_manager.get_session_metadata(session_id):
            return project_manager, "project"

    # Try global
    user_data_dir = Path.home() / ".exobrain" / "data"
    global_conversations_path = user_data_dir / "conversations"
    if global_conversations_path.exists():
        global_manager = ConversationManager(
            storage_path=global_conversations_path,
            model_provider=model_provider,
            save_tool_history=config.memory.save_tool_history,
            tool_content_max_length=config.memory.tool_content_max_length,
        )
        if global_manager.get_session_metadata(session_id):
            return global_manager, "global"

    return None


@click.group()
@click.pass_context
def sessions(ctx: click.Context) -> None:
    """Manage conversation sessions.

    Examples:
        exobrain sessions list              # List recent sessions
        exobrain sessions show <ID>         # Show session details
        exobrain sessions delete <ID>       # Delete a session
    """


@sessions.command("list")
@click.option(
    "--limit",
    default=None,
    type=int,
    help="Maximum number of sessions to show (default: show all with pagination)",
)
@click.option(
    "--page-size",
    default=10,
    type=int,
    help="Number of sessions to show per page (default: 10)",
)
@click.option(
    "--no-pagination",
    is_flag=True,
    help="Disable pagination and show all sessions at once",
)
@click.pass_context
def sessions_list(
    ctx: click.Context, limit: int | None, page_size: int, no_pagination: bool
) -> None:
    """List recent conversation sessions from both project and global storage."""
    config: Config = ctx.obj["config"]

    # Initialize model provider for token counting
    from exobrain.providers.factory import ModelFactory

    try:
        model_factory = ModelFactory(config)
        model_provider = model_factory.get_provider()
    except Exception as e:
        console.print(f"[red]Error initializing model provider: {e}[/red]")
        ctx.exit(1)

    # Collect sessions from both locations
    all_sessions = []

    # 1. Project-level sessions (priority)
    project_conversations_path = Path.cwd() / ".exobrain" / "conversations"
    if project_conversations_path.parent.exists():
        project_manager = ConversationManager(
            storage_path=project_conversations_path,
            model_provider=model_provider,
            save_tool_history=config.memory.save_tool_history,
            tool_content_max_length=config.memory.tool_content_max_length,
        )
        project_sessions = project_manager.list_sessions(limit=limit or 10000)
        for session in project_sessions:
            session["_source"] = "project"
            session["_source_path"] = str(project_conversations_path)
        all_sessions.extend(project_sessions)

    # 2. Global sessions
    user_data_dir = Path.home() / ".exobrain" / "data"
    global_conversations_path = user_data_dir / "conversations"
    if global_conversations_path.exists():
        global_manager = ConversationManager(
            storage_path=global_conversations_path,
            model_provider=model_provider,
            save_tool_history=config.memory.save_tool_history,
            tool_content_max_length=config.memory.tool_content_max_length,
        )
        global_sessions = global_manager.list_sessions(limit=limit or 10000)
        for session in global_sessions:
            session["_source"] = "global"
            session["_source_path"] = str(global_conversations_path)
        all_sessions.extend(global_sessions)

    if not all_sessions:
        console.print("[yellow]No conversation sessions found.[/yellow]")
        return

    # Apply limit if specified
    if limit:
        all_sessions = all_sessions[:limit]

    total_sessions = len(all_sessions)

    # Show storage paths info
    def show_storage_info():
        if any(s["_source"] == "project" for s in all_sessions):
            console.print(f"[dim]📁Project: {project_conversations_path}[/dim]")
        if any(s["_source"] == "global" for s in all_sessions):
            console.print(f"[dim]🏠User:  {global_conversations_path}[/dim]")
        console.print()

    # Show a page of sessions
    def show_page(sessions_page: list, page_num: int, total_pages: int):
        table = Table(
            title=f"Recent Sessions (Page {page_num}/{total_pages}, Total: {total_sessions})"
        )
        table.add_column("Scope", style="magenta", width=8)
        table.add_column("ID", style="cyan")
        table.add_column("Title", style="white")
        table.add_column("Messages", justify="right", style="blue")
        table.add_column("Last Activity", style="dim")

        for session in sessions_page:
            scope_label = "📁Proj" if session["_source"] == "project" else "🏠User"
            table.add_row(
                scope_label,
                session["id"],
                session.get("title", "Untitled"),
                str(session.get("message_count", 0)),
                session.get("last_activity", "Unknown")[:19],  # Truncate timestamp
            )

        console.print(table)

    # If no pagination or sessions fit in one page, show all at once
    if no_pagination or total_sessions <= page_size:
        show_storage_info()
        show_page(all_sessions, 1, 1)
        return

    # Pagination mode
    show_storage_info()

    current_page = 0
    total_pages = (total_sessions + page_size - 1) // page_size

    while True:
        # Calculate page range
        start_idx = current_page * page_size
        end_idx = min(start_idx + page_size, total_sessions)
        page_sessions = all_sessions[start_idx:end_idx]

        # Show current page
        show_page(page_sessions, current_page + 1, total_pages)

        # Show navigation prompt
        if current_page < total_pages - 1:
            console.print("\n[dim]Options: [n]ext page, [p]revious page, [g]oto page, [q]uit[/dim]")
            choice = Prompt.ask("Your choice", choices=["n", "p", "g", "q"], default="n").lower()

            if choice == "n":
                current_page += 1
            elif choice == "p":
                if current_page > 0:
                    current_page -= 1
                else:
                    console.print("[yellow]Already at first page[/yellow]")
                    continue
            elif choice == "g":
                page_input = Prompt.ask(
                    f"Go to page (1-{total_pages})", default=str(current_page + 1)
                )
                try:
                    target_page = int(page_input)
                    if 1 <= target_page <= total_pages:
                        current_page = target_page - 1
                    else:
                        console.print(
                            f"[yellow]Invalid page number. Must be between 1 and {total_pages}[/yellow]"
                        )
                        continue
                except ValueError:
                    console.print("[yellow]Invalid input. Please enter a number.[/yellow]")
                    continue
            elif choice == "q":
                break

            console.print()  # Add spacing between pages
        else:
            # Last page
            console.print("\n[dim]End of sessions. Press Enter to exit or [p]revious page.[/dim]")
            choice = Prompt.ask("Your choice", choices=["p", "q", ""], default="").lower()
            if choice == "p":
                if current_page > 0:
                    current_page -= 1
                    console.print()
                else:
                    console.print("[yellow]Already at first page[/yellow]")
            else:
                break


@sessions.command("show")
@click.argument("session_id")
@click.pass_context
def sessions_show(ctx: click.Context, session_id: str) -> None:
    """Show details of a specific session."""
    config: Config = ctx.obj["config"]

    # Initialize model provider
    from exobrain.providers.factory import ModelFactory

    try:
        model_factory = ModelFactory(config)
        model_provider = model_factory.get_provider()
    except Exception as e:
        console.print(f"[red]Error initializing model provider: {e}[/red]")
        ctx.exit(1)

    # Find the session
    result = _get_conversation_manager_for_session(session_id, config, model_provider)
    if not result:
        console.print(f"[red]Session not found: {session_id}[/red]")
        ctx.exit(1)

    conversation_manager, source = result
    scope_label = "📁Project" if source == "project" else "🏠User"

    # Get session metadata
    try:
        metadata = conversation_manager.get_session_metadata(session_id)
        if not metadata:
            console.print(f"[red]Session not found: {session_id}[/red]")
            ctx.exit(1)

        # Display metadata
        info_lines = [
            f"[bold]Scope:[/bold] {scope_label}",
            f"[bold]Session ID:[/bold] {metadata['id']}",
            f"[bold]Title:[/bold] {metadata.get('title', 'Untitled')}",
            f"[bold]Model:[/bold] {metadata.get('model', 'Unknown')}",
            f"[bold]Created:[/bold] {metadata.get('created_at', 'Unknown')[:19]}",
            f"[bold]Updated:[/bold] {metadata.get('updated_at', 'Unknown')[:19]}",
            f"[bold]Message Count:[/bold] {metadata.get('message_count', 0)}",
            f"[bold]Total Tokens:[/bold] {metadata.get('total_tokens', 0):,}",
        ]

        console.print(
            Panel(
                "\n".join(info_lines),
                title="Session Details",
                border_style="cyan",
            )
        )

        # Load and display messages preview
        session_data = conversation_manager.load_session(session_id, token_budget=None)
        messages = session_data["messages"]

        if messages:
            console.print(f"\n[bold cyan]Messages ({len(messages)}):[/bold cyan]")
            for i, msg in enumerate(messages[-5:], start=max(0, len(messages) - 5)):
                role_color = "green" if msg["role"] == "user" else "cyan"
                content_preview = msg.get("content", "")[:100]
                if len(msg.get("content", "")) > 100:
                    content_preview += "..."
                console.print(
                    f"  [{role_color}]{msg['role'].upper()}[/{role_color}]: {content_preview}"
                )

            if len(messages) > 5:
                console.print(f"  [dim]... and {len(messages) - 5} more messages[/dim]")

    except Exception as e:
        console.print(f"[red]Error loading session: {e}[/red]")
        logger.exception("Error loading session")
        ctx.exit(1)


@sessions.command("delete")
@click.argument("session_ids", nargs=-1, required=False)
@click.option("--all", is_flag=True, help="Delete all sessions")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
@click.pass_context
def sessions_delete(ctx: click.Context, session_ids: tuple[str, ...], all: bool, yes: bool) -> None:
    """Delete one or more conversation sessions.

    Examples:
        exobrain sessions delete abc123              # Delete single session
        exobrain sessions delete abc123 def456       # Delete multiple sessions
        exobrain sessions delete --all               # Delete all sessions
        exobrain sessions delete --all --yes         # Delete all without confirmation
    """
    config: Config = ctx.obj["config"]

    # Validate arguments
    if not all and not session_ids:
        console.print("[red]Error: Provide session IDs to delete or use --all flag[/red]")
        console.print("[dim]Usage: exobrain sessions delete <session_id> [<session_id> ...]")
        console.print("[dim]   or: exobrain sessions delete --all[/dim]")
        ctx.exit(1)

    if all and session_ids:
        console.print("[yellow]Warning: --all flag ignores specific session IDs[/yellow]")

    # Initialize model provider
    from exobrain.providers.factory import ModelFactory

    try:
        model_factory = ModelFactory(config)
        model_provider = model_factory.get_provider()
    except Exception as e:
        console.print(f"[red]Error initializing model provider: {e}[/red]")
        ctx.exit(1)

    # Collect all managers
    managers = []
    project_conversations_path = Path.cwd() / ".exobrain" / "conversations"
    user_data_dir = Path.home() / ".exobrain" / "data"
    global_conversations_path = user_data_dir / "conversations"

    if project_conversations_path.parent.exists():
        project_manager = ConversationManager(
            storage_path=project_conversations_path,
            model_provider=model_provider,
            save_tool_history=config.memory.save_tool_history,
            tool_content_max_length=config.memory.tool_content_max_length,
        )
        managers.append(("project", project_manager))

    if global_conversations_path.exists():
        global_manager = ConversationManager(
            storage_path=global_conversations_path,
            model_provider=model_provider,
            save_tool_history=config.memory.save_tool_history,
            tool_content_max_length=config.memory.tool_content_max_length,
        )
        managers.append(("global", global_manager))

    if not managers:
        console.print("[yellow]No conversation storage found.[/yellow]")
        return

    # Get sessions to delete
    if all:
        # Get all sessions from all managers
        sessions_to_delete = []
        for source, manager in managers:
            source_sessions = manager.list_sessions(limit=10000)
            for s in source_sessions:
                sessions_to_delete.append((s["id"], source))
        if not sessions_to_delete:
            console.print("[yellow]No sessions to delete.[/yellow]")
            return
    else:
        # Find each session in managers
        sessions_to_delete = []
        for session_id in session_ids:
            found = False
            for source, manager in managers:
                if manager.get_session_metadata(session_id):
                    sessions_to_delete.append((session_id, source))
                    found = True
                    break
            if not found:
                sessions_to_delete.append((session_id, None))

    # Verify sessions exist and get metadata
    valid_sessions = []
    invalid_sessions = []
    for item in sessions_to_delete:
        if len(item) == 2 and item[1] is not None:
            session_id, source = item
            # Find the manager
            manager = next(m for s, m in managers if s == source)
            metadata = manager.get_session_metadata(session_id)
            if metadata:
                valid_sessions.append((session_id, source, manager, metadata))
            else:
                invalid_sessions.append(session_id)
        else:
            invalid_sessions.append(item[0])

    if invalid_sessions:
        console.print(f"[yellow]Warning: {len(invalid_sessions)} session(s) not found:[/yellow]")
        for sid in invalid_sessions:
            console.print(f"  • {sid}")
        console.print()

    if not valid_sessions:
        console.print("[red]No valid sessions to delete.[/red]")
        ctx.exit(1)

    # Show what will be deleted
    console.print(f"[yellow]About to delete {len(valid_sessions)} session(s):[/yellow]")
    for session_id, source, manager, metadata in valid_sessions:
        title = metadata.get("title", "Untitled")
        scope_label = "📁" if source == "project" else "🌍"
        console.print(f"  {scope_label} {session_id[:8]} - {title}")
    console.print()

    # Confirm deletion
    if not yes:
        if all:
            confirm_msg = f"[bold red]Delete ALL {len(valid_sessions)} sessions? This cannot be undone![/bold red]"
        elif len(valid_sessions) > 1:
            confirm_msg = f"Delete these {len(valid_sessions)} sessions?"
        else:
            confirm_msg = (
                f"Delete session '{valid_sessions[0][3].get('title', valid_sessions[0][0])}'?"
            )

        confirmed = Confirm.ask(confirm_msg, default=False)
        if not confirmed:
            console.print("[yellow]Cancelled.[/yellow]")
            return

    # Delete sessions
    success_count = 0
    failed_count = 0
    try:
        for session_id, source, manager, metadata in valid_sessions:
            try:
                if manager.delete_session(session_id):
                    success_count += 1
                    scope_label = "📁" if source == "project" else "🌍"
                    # fix session id length to 8 to display date only
                    console.print(
                        f"[green]✓[/green] {scope_label} Deleted: {session_id[:8]} - {metadata.get('title', 'Untitled')}"
                    )
                else:
                    failed_count += 1
                    console.print(f"[red]✗[/red] Failed to delete: {session_id[:8]}")
            except Exception as e:
                failed_count += 1
                console.print(f"[red]✗[/red] Error deleting {session_id[:8]}: {e}")

        # Summary
        console.print()
        console.print(f"[green]Successfully deleted {success_count} session(s)[/green]")
        if failed_count > 0:
            console.print(f"[red]Failed to delete {failed_count} session(s)[/red]")

    except Exception as e:
        console.print(f"[red]Error during deletion: {e}[/red]")
        logger.exception("Error deleting sessions")
        ctx.exit(1)
