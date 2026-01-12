"""Task management commands for ExoBrain CLI."""

import asyncio
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from exobrain.tasks import (
    DaemonConnectionError,
    DaemonNotRunningError,
    TaskClient,
    TaskStatus,
    TaskType,
)

console = Console()


async def resolve_task_id(client: TaskClient, partial_id: str) -> str:
    """
    Resolve a partial task ID to a full task ID.

    Args:
        client: TaskClient instance
        partial_id: Partial or full task ID

    Returns:
        Full task ID

    Raises:
        RuntimeError: If no matching task found or multiple matches
    """
    # If it looks like a full ID, try it directly first
    if len(partial_id) > 20:
        try:
            task = await client.get_task(partial_id)
            return task.task_id
        except:
            pass

    # Search for matching tasks
    all_tasks = await client.list_tasks()
    matches = [t for t in all_tasks if t.task_id.startswith(partial_id)]

    if len(matches) == 0:
        raise RuntimeError(f"No task found matching: {partial_id}")
    elif len(matches) > 1:
        task_ids = [t.task_id for t in matches]
        raise RuntimeError(f"Multiple tasks match '{partial_id}': {', '.join(task_ids)}")

    return matches[0].task_id


@click.group()
def task() -> None:
    """Manage background tasks."""


@task.group()
def daemon() -> None:
    """Manage task daemon."""


@daemon.command("start")
@click.option(
    "--transport",
    type=click.Choice(["auto", "unix", "pipe", "http"]),
    default="auto",
    help="Transport type",
)
@click.option("--socket-path", help="Unix socket path")
@click.option("--pipe-name", help="Named pipe name")
@click.option("--host", help="HTTP host")
@click.option("--port", type=int, help="HTTP port")
def daemon_start(
    transport: str,
    socket_path: Optional[str],
    pipe_name: Optional[str],
    host: Optional[str],
    port: Optional[int],
) -> None:
    """Start the task daemon."""

    async def _start():
        # Build transport config
        transport_config = {}
        if socket_path:
            transport_config["socket_path"] = socket_path
        if pipe_name:
            transport_config["pipe_name"] = pipe_name
        if host:
            transport_config["host"] = host
        if port:
            transport_config["port"] = port

        client = TaskClient(
            transport_type=transport,
            transport_config=transport_config,
            auto_start=False,
        )

        # Check if already running
        if client.is_daemon_running():
            pid = client.get_daemon_pid()
            console.print(f"[yellow]Task daemon is already running (PID: {pid})[/yellow]")
            return

        try:
            with console.status("[cyan]Starting task daemon...[/cyan]"):
                pid = await client.start_daemon()

            console.print(f"[green]✓[/green] Task daemon started (PID: {pid})")
            console.print(f"[dim]Transport: {transport}[/dim]")

        except Exception as e:
            console.print(f"[red]✗[/red] Failed to start daemon: {e}")
            raise click.Abort()

    asyncio.run(_start())


@daemon.command("stop")
@click.option("--timeout", type=float, default=5.0, help="Timeout in seconds")
def daemon_stop(timeout: float) -> None:
    """Stop the task daemon."""

    async def _stop():
        client = TaskClient(auto_start=False)

        # Check if running
        if not client.is_daemon_running():
            console.print("[yellow]Task daemon is not running[/yellow]")
            return

        pid = client.get_daemon_pid()

        try:
            with console.status(f"[cyan]Stopping task daemon (PID: {pid})...[/cyan]"):
                stopped = await client.stop_daemon(timeout)

            if stopped:
                console.print(f"[green]✓[/green] Task daemon stopped (PID: {pid})")
            else:
                console.print("[yellow]Task daemon was not running[/yellow]")

        except Exception as e:
            console.print(f"[red]✗[/red] Failed to stop daemon: {e}")
            raise click.Abort()

    asyncio.run(_stop())


@daemon.command("restart")
@click.option("--timeout", type=float, default=5.0, help="Timeout in seconds")
def daemon_restart(timeout: float) -> None:
    """Restart the task daemon."""

    async def _restart():
        client = TaskClient(auto_start=False)

        old_pid = client.get_daemon_pid()

        try:
            with console.status("[cyan]Restarting task daemon...[/cyan]"):
                new_pid = await client.restart_daemon(timeout)

            console.print(f"[green]✓[/green] Task daemon restarted")
            if old_pid:
                console.print(f"[dim]Old PID: {old_pid}[/dim]")
            console.print(f"[dim]New PID: {new_pid}[/dim]")

        except Exception as e:
            console.print(f"[red]✗[/red] Failed to restart daemon: {e}")
            raise click.Abort()

    asyncio.run(_restart())


@daemon.command("status")
def daemon_status() -> None:
    """Show daemon status."""

    async def _status():
        client = TaskClient(auto_start=False)

        try:
            status = await client.get_daemon_status()

            if status["running"]:
                panel_content = f"[green]Running[/green]\n"
                panel_content += f"PID: {status['pid']}\n"
                panel_content += f"Transport: {status['transport_type']}\n"
                panel_content += f"PID File: {status['pid_file']}\n"

                if "responsive" in status:
                    if status["responsive"]:
                        panel_content += f"Status: [green]Responsive[/green]"
                    else:
                        panel_content += f"Status: [red]Not Responsive[/red]"
                        if "error" in status:
                            panel_content += f"\nError: {status['error']}"

                console.print(
                    Panel(
                        panel_content,
                        title="Task Daemon Status",
                        border_style="green",
                    )
                )
            else:
                console.print(
                    Panel(
                        "[yellow]Not Running[/yellow]",
                        title="Task Daemon Status",
                        border_style="yellow",
                    )
                )

        except Exception as e:
            console.print(f"[red]✗[/red] Failed to get daemon status: {e}")
            raise click.Abort()

    asyncio.run(_status())


@task.command("submit")
@click.argument("name")
@click.option("--description", "-d", help="Task description")
@click.option(
    "--type",
    "task_type",
    type=click.Choice(["agent", "process"]),
    default="agent",
    help="Task type",
)
def task_submit(name: str, description: Optional[str], task_type: str) -> None:
    """Submit a new task."""

    async def _submit():
        try:
            async with TaskClient() as client:
                with console.status("[cyan]Creating task...[/cyan]"):
                    task = await client.create_task(
                        name=name,
                        description=description or "",
                        task_type=TaskType(task_type),
                    )

                console.print(f"[green]✓[/green] Task created: [cyan]{task.task_id}[/cyan]")
                console.print(f"[dim]Name: {task.name}[/dim]")
                console.print(f"[dim]Type: {task.task_type.value}[/dim]")
                console.print(f"[dim]Status: {task.status.value}[/dim]")

        except DaemonNotRunningError as e:
            console.print(f"[red]✗[/red] {e}")
            raise click.Abort()
        except DaemonConnectionError as e:
            console.print(f"[red]✗[/red] {e}")
            raise click.Abort()
        except Exception as e:
            console.print(f"[red]✗[/red] Failed to create task: {e}")
            raise click.Abort()

    asyncio.run(_submit())


@task.command("list")
@click.option(
    "--status",
    type=click.Choice(
        [
            "pending",
            "running",
            "completed",
            "failed",
            "cancelled",
            "interrupted",
        ]
    ),
    help="Filter by status",
)
@click.option(
    "--type",
    "task_type",
    type=click.Choice(["agent", "process"]),
    help="Filter by type",
)
@click.option("--limit", type=int, help="Maximum number of tasks to show")
def task_list(status: Optional[str], task_type: Optional[str], limit: Optional[int]) -> None:
    """List tasks."""

    async def _list():
        try:
            async with TaskClient() as client:
                with console.status("[cyan]Fetching tasks...[/cyan]"):
                    tasks = await client.list_tasks(
                        status=TaskStatus(status) if status else None,
                        task_type=TaskType(task_type) if task_type else None,
                        limit=limit,
                    )

                if not tasks:
                    console.print("[yellow]No tasks found[/yellow]")
                    return

                # Create table
                table = Table(title="Tasks")
                table.add_column("ID", style="cyan")
                table.add_column("Name")
                table.add_column("Type")
                table.add_column("Status")
                table.add_column("Duration")
                table.add_column("Created At", style="dim")

                for t in tasks:
                    # Format status with color
                    status_text = t.status.value
                    if t.status == TaskStatus.RUNNING:
                        status_text = f"[green]{status_text}[/green]"
                    elif t.status == TaskStatus.COMPLETED:
                        status_text = f"[blue]{status_text}[/blue]"
                    elif t.status == TaskStatus.FAILED:
                        status_text = f"[red]{status_text}[/red]"
                    elif t.status == TaskStatus.CANCELLED:
                        status_text = f"[yellow]{status_text}[/yellow]"

                    # Format duration
                    duration = t.duration or 0
                    if duration < 60:
                        duration_str = f"{duration:.0f}s"
                    elif duration < 3600:
                        duration_str = f"{duration / 60:.1f}m"
                    else:
                        duration_str = f"{duration / 3600:.1f}h"

                    table.add_row(
                        t.task_id[:8],
                        t.name,
                        t.task_type.value,
                        status_text,
                        duration_str,
                        str(t.created_at),
                    )

                console.print(table)
                console.print(f"\n[dim]Total: {len(tasks)} task(s)[/dim]")

        except DaemonNotRunningError as e:
            console.print(f"[red]✗[/red] {e}")
            raise click.Abort()
        except DaemonConnectionError as e:
            console.print(f"[red]✗[/red] {e}")
            raise click.Abort()
        except Exception as e:
            console.print(f"[red]✗[/red] Failed to list tasks: {e}")
            raise click.Abort()

    asyncio.run(_list())


@task.command("show")
@click.argument("task_id")
def task_show(task_id: str) -> None:
    """Show task details."""

    async def _show():
        try:
            async with TaskClient() as client:
                with console.status("[cyan]Fetching task...[/cyan]"):
                    # Resolve partial task ID
                    full_task_id = await resolve_task_id(client, task_id)
                    t = await client.get_task(full_task_id)

                # Build panel content
                content = f"ID: [cyan]{t.task_id}[/cyan]\n"
                content += f"Name: {t.name}\n"
                if t.description:
                    content += f"Description: {t.description}\n"
                content += f"Type: {t.task_type.value}\n"
                content += f"Status: {t.status.value}\n"
                content += f"Created: {t.created_at}\n"
                if t.started_at:
                    content += f"Started: {t.started_at}\n"
                if t.completed_at:
                    content += f"Completed: {t.completed_at}\n"
                if t.duration:
                    content += f"Duration: {t.duration:.1f}s\n"

                # Task-specific fields
                if t.task_type == TaskType.AGENT:
                    if t.iterations is not None:
                        content += f"Iterations: {t.iterations}/{t.max_iterations}\n"
                elif t.task_type == TaskType.PROCESS:
                    if t.command:
                        content += f"Command: {t.command}\n"
                    if t.working_directory:
                        content += f"Working Directory: {t.working_directory}\n"
                    if t.exit_code is not None:
                        content += f"Exit Code: {t.exit_code}\n"
                    if t.pid:
                        content += f"PID: {t.pid}\n"

                console.print(Panel(content, title="Task Details", border_style="cyan"))

        except DaemonNotRunningError as e:
            console.print(f"[red]✗[/red] {e}")
            raise click.Abort()
        except DaemonConnectionError as e:
            console.print(f"[red]✗[/red] {e}")
            raise click.Abort()
        except Exception as e:
            console.print(f"[red]✗[/red] Failed to get task: {e}")
            raise click.Abort()

    asyncio.run(_show())


@task.command("follow")
@click.argument("task_id")
@click.option(
    "--poll-interval",
    type=float,
    default=0.5,
    help="Polling interval in seconds",
)
def task_follow(task_id: str, poll_interval: float) -> None:
    """Follow task output in real-time."""

    async def _follow():
        try:
            async with TaskClient() as client:
                # Resolve partial task ID
                full_task_id = await resolve_task_id(client, task_id)

                console.print(f"[cyan]Following task {full_task_id[:8]}...[/cyan]")
                console.print("[dim]Press Ctrl+C to exit (task will continue running)[/dim]\n")

                await client.follow_output(full_task_id, poll_interval)

                console.print(f"\n[green]✓[/green] Task completed")

        except KeyboardInterrupt:
            console.print(f"\n[yellow]Stopped following task (task is still running)[/yellow]")
        except DaemonNotRunningError as e:
            console.print(f"[red]✗[/red] {e}")
            raise click.Abort()
        except DaemonConnectionError as e:
            console.print(f"[red]✗[/red] {e}")
            raise click.Abort()
        except Exception as e:
            console.print(f"[red]✗[/red] Failed to follow task: {e}")
            raise click.Abort()

    asyncio.run(_follow())


@task.command("cancel")
@click.argument("task_id")
def task_cancel(task_id: str) -> None:
    """Cancel a running task."""

    async def _cancel():
        try:
            async with TaskClient() as client:
                # Resolve partial task ID
                full_task_id = await resolve_task_id(client, task_id)

                with console.status(f"[cyan]Cancelling task {full_task_id[:8]}...[/cyan]"):
                    t = await client.cancel_task(full_task_id)

                console.print(f"[green]✓[/green] Task cancelled: [cyan]{t.task_id[:8]}[/cyan]")
                console.print(f"[dim]Status: {t.status.value}[/dim]")

        except DaemonNotRunningError as e:
            console.print(f"[red]✗[/red] {e}")
            raise click.Abort()
        except DaemonConnectionError as e:
            console.print(f"[red]✗[/red] {e}")
            raise click.Abort()
        except Exception as e:
            console.print(f"[red]✗[/red] Failed to cancel task: {e}")
            raise click.Abort()

    asyncio.run(_cancel())


@task.command("delete")
@click.argument("task_id", required=False)
@click.option("--force", "-f", is_flag=True, help="Force delete without confirmation")
@click.option("--all", is_flag=True, help="Delete all tasks (requires double confirmation)")
def task_delete(task_id: str, force: bool, all: bool) -> None:
    """Delete a task or all tasks."""

    async def _delete():
        try:
            async with TaskClient() as client:
                # Handle --all flag
                if all:
                    # Get all tasks
                    all_tasks = await client.list_tasks()

                    if not all_tasks:
                        console.print("[yellow]No tasks to delete[/yellow]")
                        return

                    task_count = len(all_tasks)

                    # Double confirmation for --all
                    if not force:
                        console.print(
                            f"[yellow]⚠[/yellow]  This will delete [red]{task_count}[/red] task(s)"
                        )

                        # First confirmation
                        if not click.confirm("Are you sure you want to delete ALL tasks?"):
                            console.print("[yellow]Cancelled[/yellow]")
                            return

                        # Second confirmation
                        console.print("[red]⚠ WARNING: This action cannot be undone![/red]")
                        if not click.confirm(
                            "Type 'yes' to confirm deletion of all tasks", default=False
                        ):
                            console.print("[yellow]Cancelled[/yellow]")
                            return

                    # Delete all tasks
                    deleted_count = 0
                    failed_count = 0

                    with console.status(f"[cyan]Deleting {task_count} task(s)...[/cyan]"):
                        for task in all_tasks:
                            try:
                                await client.delete_task(task.task_id)
                                deleted_count += 1
                            except Exception as e:
                                console.print(
                                    f"[red]✗[/red] Failed to delete task {task.task_id[:8]}: {e}"
                                )
                                failed_count += 1

                    console.print(f"[green]✓[/green] Deleted {deleted_count} task(s)")
                    if failed_count > 0:
                        console.print(
                            f"[yellow]⚠[/yellow]  Failed to delete {failed_count} task(s)"
                        )

                    return

                # Handle single task deletion
                if not task_id:
                    console.print("[red]✗[/red] Either provide a task_id or use --all flag")
                    raise click.Abort()

                # Resolve partial task ID first
                full_task_id = await resolve_task_id(client, task_id)

                # Confirm deletion
                if not force:
                    if not click.confirm(f"Delete task {full_task_id[:8]}?"):
                        console.print("[yellow]Cancelled[/yellow]")
                        return

                with console.status(f"[cyan]Deleting task {full_task_id[:8]}...[/cyan]"):
                    deleted_id = await client.delete_task(full_task_id)

                console.print(f"[green]✓[/green] Task deleted: [cyan]{deleted_id[:8]}[/cyan]")

        except DaemonNotRunningError as e:
            console.print(f"[red]✗[/red] {e}")
            raise click.Abort()
        except DaemonConnectionError as e:
            console.print(f"[red]✗[/red] {e}")
            raise click.Abort()
        except Exception as e:
            console.print(f"[red]✗[/red] Failed to delete task: {e}")
            raise click.Abort()

    asyncio.run(_delete())


@task.command("metrics")
def task_metrics() -> None:
    """Show task system metrics."""

    async def _metrics():
        try:
            async with TaskClient() as client:
                with console.status("[cyan]Collecting metrics...[/cyan]"):
                    metrics = await client.get_metrics()

                # Create metrics panel
                metrics_text = f"""[bold]Task Counts[/bold]
Total: {metrics['total_tasks']}
Pending: {metrics['pending_tasks']}
Running: {metrics['running_tasks']}
Completed: {metrics['completed_tasks']}
Failed: {metrics['failed_tasks']}
Cancelled: {metrics['cancelled_tasks']}
Interrupted: {metrics['interrupted_tasks']}

[bold]By Type[/bold]
Agent: {metrics['agent_tasks']}
Process: {metrics['process_tasks']}

[bold]Performance[/bold]
Avg Duration: {metrics['avg_duration_seconds']:.1f}s
Min Duration: {metrics['min_duration_seconds']:.1f}s
Max Duration: {metrics['max_duration_seconds']:.1f}s
Success Rate: {metrics['success_rate']:.1%}
Failure Rate: {metrics['failure_rate']:.1%}

[bold]Recent Activity (Last Hour)[/bold]
Created: {metrics['tasks_created_last_hour']}
Completed: {metrics['tasks_completed_last_hour']}
Failed: {metrics['tasks_failed_last_hour']}

[bold]Capacity[/bold]
Active: {metrics['active_task_count']}/{metrics['max_concurrent_tasks']}
Queue: {metrics['task_queue_size']}"""

                panel = Panel(
                    metrics_text,
                    title="[bold cyan]Task System Metrics[/bold cyan]",
                    border_style="cyan",
                )
                console.print(panel)

        except DaemonNotRunningError as e:
            console.print(f"[red]✗[/red] {e}")
            raise click.Abort()
        except DaemonConnectionError as e:
            console.print(f"[red]✗[/red] {e}")
            raise click.Abort()
        except Exception as e:
            console.print(f"[red]✗[/red] Failed to get metrics: {e}")
            raise click.Abort()

    asyncio.run(_metrics())


@task.command("health")
def task_health() -> None:
    """Check task system health."""

    async def _health():
        try:
            async with TaskClient() as client:
                with console.status("[cyan]Checking health...[/cyan]"):
                    health = await client.get_health()

                # Determine health status
                if health["is_healthy"]:
                    status_icon = "[green]✓[/green]"
                    status_text = "[green]Healthy[/green]"
                else:
                    status_icon = "[red]✗[/red]"
                    status_text = "[red]Unhealthy[/red]"

                # Build health text
                health_text = f"{status_icon} Status: {status_text}\n"

                if health["issues"]:
                    health_text += "\n[bold red]Issues:[/bold red]\n"
                    for issue in health["issues"]:
                        health_text += f"  • {issue}\n"

                if health["warnings"]:
                    health_text += "\n[bold yellow]Warnings:[/bold yellow]\n"
                    for warning in health["warnings"]:
                        health_text += f"  • {warning}\n"

                if not health["issues"] and not health["warnings"]:
                    health_text += "\n[green]No issues or warnings[/green]"

                panel = Panel(
                    health_text,
                    title="[bold cyan]Task System Health[/bold cyan]",
                    border_style="cyan" if health["is_healthy"] else "red",
                )
                console.print(panel)

        except DaemonNotRunningError as e:
            console.print(f"[red]✗[/red] {e}")
            raise click.Abort()
        except DaemonConnectionError as e:
            console.print(f"[red]✗[/red] {e}")
            raise click.Abort()
        except Exception as e:
            console.print(f"[red]✗[/red] Failed to check health: {e}")
            raise click.Abort()

    asyncio.run(_health())


@task.command("stats")
def task_stats() -> None:
    """Show detailed task statistics."""

    async def _stats():
        try:
            async with TaskClient() as client:
                with console.status("[cyan]Collecting statistics...[/cyan]"):
                    stats = await client.get_statistics()

                # Create statistics tables
                console.print("\n[bold cyan]Task Statistics[/bold cyan]\n")

                # Overview table
                overview_table = Table(title="Overview", show_header=True)
                overview_table.add_column("Metric", style="cyan")
                overview_table.add_column("Value", style="white")

                for key, value in stats["overview"].items():
                    overview_table.add_row(key.replace("_", " ").title(), str(value))

                console.print(overview_table)
                console.print()

                # By status table
                status_table = Table(title="By Status", show_header=True)
                status_table.add_column("Status", style="cyan")
                status_table.add_column("Count", style="white")

                for status, count in stats["by_status"].items():
                    status_table.add_row(status.title(), str(count))

                console.print(status_table)
                console.print()

                # Performance table
                perf_table = Table(title="Performance", show_header=True)
                perf_table.add_column("Metric", style="cyan")
                perf_table.add_column("Value", style="white")

                for key, value in stats["performance"].items():
                    if "rate" in key:
                        formatted_value = f"{value:.1%}"
                    elif "seconds" in key:
                        formatted_value = f"{value:.1f}s"
                    else:
                        formatted_value = str(value)
                    perf_table.add_row(key.replace("_", " ").title(), formatted_value)

                console.print(perf_table)
                console.print()

                # Capacity table
                capacity_table = Table(title="Capacity", show_header=True)
                capacity_table.add_column("Metric", style="cyan")
                capacity_table.add_column("Value", style="white")

                for key, value in stats["capacity"].items():
                    if key == "utilization":
                        formatted_value = f"{value:.1%}"
                    else:
                        formatted_value = str(value)
                    capacity_table.add_row(key.replace("_", " ").title(), formatted_value)

                console.print(capacity_table)

        except DaemonNotRunningError as e:
            console.print(f"[red]✗[/red] {e}")
            raise click.Abort()
        except DaemonConnectionError as e:
            console.print(f"[red]✗[/red] {e}")
            raise click.Abort()
        except Exception as e:
            console.print(f"[red]✗[/red] Failed to get statistics: {e}")
            raise click.Abort()

    asyncio.run(_stats())


@task.command("cleanup")
@click.option("--retention-days", type=int, help="Delete tasks older than this many days")
@click.option("--max-tasks", type=int, help="Keep at most this many tasks")
@click.option("--force", is_flag=True, help="Skip confirmation prompt")
def task_cleanup(retention_days: Optional[int], max_tasks: Optional[int], force: bool) -> None:
    """Clean up old completed tasks."""

    async def _cleanup():
        try:
            async with TaskClient() as client:
                # Show what will be cleaned up
                if not force:
                    msg = "Clean up old tasks"
                    if retention_days:
                        msg += f" (older than {retention_days} days)"
                    if max_tasks:
                        msg += f" (keep max {max_tasks} tasks)"
                    msg += "?"

                    if not click.confirm(msg):
                        console.print("[yellow]Cancelled[/yellow]")
                        return

                with console.status("[cyan]Cleaning up tasks...[/cyan]"):
                    deleted_count = await client.cleanup_tasks(
                        retention_days=retention_days, max_tasks=max_tasks
                    )

                console.print(f"[green]✓[/green] Cleaned up {deleted_count} task(s)")

        except DaemonNotRunningError as e:
            console.print(f"[red]✗[/red] {e}")
            raise click.Abort()
        except DaemonConnectionError as e:
            console.print(f"[red]✗[/red] {e}")
            raise click.Abort()
        except Exception as e:
            console.print(f"[red]✗[/red] Failed to cleanup tasks: {e}")
            raise click.Abort()

    asyncio.run(_cleanup())
