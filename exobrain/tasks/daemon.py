"""Task daemon process."""

import asyncio
import logging
import os
import platform
import signal
from pathlib import Path
from typing import Any, Dict, Optional

from .manager import TaskManager
from .models import TaskStatus, TaskType
from .monitor import TaskMonitor
from .storage import TaskStorage
from .transport import TransportFactory, TransportServer, TransportType

logger = logging.getLogger(__name__)


def _is_process_running(pid: int) -> bool:
    """
    Check if a process with the given PID is running.

    Cross-platform implementation that works on Unix, Linux, macOS, and Windows.

    Args:
        pid: Process ID to check

    Returns:
        True if process is running, False otherwise
    """
    if platform.system() == "Windows":
        # On Windows, use tasklist command or psutil-like approach
        try:
            import ctypes
            import subprocess

            # Try to open the process handle
            PROCESS_QUERY_INFORMATION = 0x0400
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_INFORMATION, False, pid)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            return False
        except (AttributeError, OSError):
            # Fallback: try using tasklist
            try:
                result = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                return str(pid) in result.stdout
            except (subprocess.TimeoutExpired, FileNotFoundError):
                return False
    else:
        # On Unix/Linux/macOS, use os.kill with signal 0
        try:
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, PermissionError):
            return False


class TaskDaemon:
    """Task daemon process that manages background tasks."""

    def __init__(
        self,
        storage_path: str = "~/.exobrain/data/tasks",
        transport_type: TransportType = TransportType.AUTO,
        transport_config: Optional[Dict[str, Any]] = None,
        pid_file: str = "~/.exobrain/task-daemon.pid",
        max_concurrent_tasks: int = 10,
        auto_cleanup: bool = True,
        cleanup_retention_days: int = 30,
        cleanup_max_tasks: int = 1000,
        cleanup_interval_hours: int = 24,
    ):
        """
        Initialize task daemon.

        Args:
            storage_path: Path to task storage directory
            transport_type: Type of transport to use
            transport_config: Transport-specific configuration
            pid_file: Path to PID file
            max_concurrent_tasks: Maximum number of concurrent tasks
            auto_cleanup: Enable automatic cleanup of old tasks
            cleanup_retention_days: Delete tasks older than this many days
            cleanup_max_tasks: Keep at most this many tasks
            cleanup_interval_hours: Run cleanup every N hours
        """
        self.storage = TaskStorage(storage_path)
        self.transport_type = transport_type
        self.transport_config = transport_config or {}
        self.pid_file = Path(pid_file).expanduser()
        self.max_concurrent_tasks = max_concurrent_tasks
        self.auto_cleanup = auto_cleanup
        self.cleanup_retention_days = cleanup_retention_days
        self.cleanup_max_tasks = cleanup_max_tasks
        self.cleanup_interval_hours = cleanup_interval_hours

        self._server: Optional[TransportServer] = None
        self._running = False
        self._manager: Optional[TaskManager] = None
        self._monitor: Optional[TaskMonitor] = None
        self._cleanup_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start the daemon."""
        logger.info("Starting task daemon")

        # Initialize storage
        logger.info("Initializing storage")
        await self.storage.initialize()

        # Initialize task manager
        logger.info("Initializing task manager")
        self._manager = TaskManager(self.storage, self.max_concurrent_tasks)
        await self._manager.initialize()

        # Initialize task monitor
        logger.info("Initializing task monitor")
        self._monitor = TaskMonitor(self.storage, self.max_concurrent_tasks)

        # Create transport server
        logger.info(f"Creating transport server: type={self.transport_type.value}")
        self._server = TransportFactory.create_server(self.transport_type, self.transport_config)

        # Set request handler
        self._server.set_request_handler(self._handle_request)

        # Start server
        logger.info("Starting transport server")
        await self._server.start()

        # Write PID file
        self._write_pid_file()

        # Set up signal handlers
        self._setup_signal_handlers()

        # Start auto-cleanup task if enabled
        if self.auto_cleanup:
            logger.info("Starting auto-cleanup task")
            self._cleanup_task = asyncio.create_task(self._run_cleanup_loop())

        self._running = True

        logger.info(f"Task daemon started (PID: {os.getpid()})")
        print(f"Task daemon started (PID: {os.getpid()})")
        print(f"Transport: {self.transport_type.value}")
        if self.auto_cleanup:
            print(f"Auto-cleanup: enabled (every {self.cleanup_interval_hours}h)")

    async def stop(self) -> None:
        """Stop the daemon."""
        self._running = False

        # Cancel cleanup task
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

        # Shutdown task manager
        if self._manager:
            await self._manager.shutdown()
            self._manager = None

        # Stop server
        if self._server:
            await self._server.stop()
            self._server = None

        # Remove PID file
        self._remove_pid_file()

        print("Task daemon stopped")

    async def run(self) -> None:
        """Run the daemon main loop."""
        try:
            # Keep daemon running
            while self._running:
                await asyncio.sleep(1)

        except KeyboardInterrupt:
            print("\nReceived interrupt signal")
        finally:
            await self.stop()

    async def _handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle incoming request.

        Args:
            request: Request dictionary with 'action' and 'params' keys

        Returns:
            Response dictionary
        """
        action = request.get("action")
        params = request.get("params", {})

        # Validate request
        if not action:
            return {"status": "error", "error": "Missing 'action' field in request"}

        try:
            if action == "create_task":
                return await self._handle_create_task(params)
            elif action == "get_task":
                return await self._handle_get_task(params)
            elif action == "list_tasks":
                return await self._handle_list_tasks(params)
            elif action == "cancel_task":
                return await self._handle_cancel_task(params)
            elif action == "delete_task":
                return await self._handle_delete_task(params)
            elif action == "get_output":
                return await self._handle_get_output(params)
            elif action == "get_metrics":
                return await self._handle_get_metrics(params)
            elif action == "get_health":
                return await self._handle_get_health(params)
            elif action == "get_statistics":
                return await self._handle_get_statistics(params)
            elif action == "cleanup_tasks":
                return await self._handle_cleanup_tasks(params)
            elif action == "ping":
                return {"status": "ok", "data": {"message": "pong"}}
            else:
                return {"status": "error", "error": f"Unknown action: {action}"}

        except KeyError as e:
            return {"status": "error", "error": f"Missing required parameter: {str(e)}"}
        except ValueError as e:
            return {"status": "error", "error": f"Invalid parameter value: {str(e)}"}
        except Exception as e:
            return {"status": "error", "error": f"Internal error: {str(e)}"}

    async def _handle_create_task(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle create_task request.

        Args:
            params: Request parameters

        Returns:
            Response dictionary
        """
        logger.info(f"Handling create_task request: params={params}")

        # Create task using manager
        task = await self._manager.create_task(
            name=params.get("name", ""),
            description=params.get("description", ""),
            task_type=TaskType(params.get("task_type", TaskType.AGENT.value)),
            config=params.get("config", {}),
        )

        logger.info(f"Task created: task_id={task.task_id}, status={task.status.value}")

        return {"status": "ok", "data": {"task": task.to_dict()}}

    async def _handle_get_task(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle get_task request.

        Args:
            params: Request parameters

        Returns:
            Response dictionary
        """
        task_id = params.get("task_id")
        if not task_id:
            return {"status": "error", "error": "Missing task_id"}

        # Get task from manager
        task = await self._manager.get_task(task_id)

        if not task:
            return {"status": "error", "error": f"Task not found: {task_id}"}

        return {"status": "ok", "data": {"task": task.to_dict()}}

    async def _handle_list_tasks(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle list_tasks request.

        Args:
            params: Request parameters

        Returns:
            Response dictionary
        """
        status = params.get("status")
        if status:
            status = TaskStatus(status)

        task_type = params.get("task_type")
        limit = params.get("limit")

        tasks = await self._manager.list_tasks(status, task_type, limit)

        return {
            "status": "ok",
            "data": {"tasks": [task.to_dict() for task in tasks], "count": len(tasks)},
        }

    async def _handle_cancel_task(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle cancel_task request.

        Args:
            params: Request parameters

        Returns:
            Response dictionary
        """
        task_id = params.get("task_id")
        if not task_id:
            return {"status": "error", "error": "Missing task_id"}

        # Cancel task using manager
        cancelled = await self._manager.cancel_task(task_id)

        if not cancelled:
            return {"status": "error", "error": f"Task not found or not active: {task_id}"}

        # Get updated task
        task = await self._manager.get_task(task_id)

        return {"status": "ok", "data": {"task": task.to_dict()}}

    async def _handle_delete_task(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle delete_task request.

        Args:
            params: Request parameters

        Returns:
            Response dictionary
        """
        task_id = params.get("task_id")
        if not task_id:
            return {"status": "error", "error": "Missing task_id"}

        # Delete task using manager
        deleted = await self._manager.delete_task(task_id)

        if not deleted:
            return {"status": "error", "error": f"Task not found: {task_id}"}

        return {"status": "ok", "data": {"task_id": task_id}}

    async def _handle_get_output(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle get_output request.

        Args:
            params: Request parameters

        Returns:
            Response dictionary
        """
        task_id = params.get("task_id")
        if not task_id:
            return {"status": "error", "error": "Missing task_id"}

        offset = params.get("offset", 0)
        limit = params.get("limit")

        output = await self.storage.read_output(task_id, offset, limit)

        return {"status": "ok", "data": {"output": output, "offset": offset, "length": len(output)}}

    async def _handle_get_metrics(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle get_metrics request.

        Args:
            params: Request parameters

        Returns:
            Response dictionary
        """
        active_count = self._manager.active_task_count if self._manager else 0
        queue_size = 0  # TODO: Implement queue size tracking

        metrics = await self._monitor.collect_metrics(
            active_task_count=active_count,
            task_queue_size=queue_size,
        )

        return {"status": "ok", "data": {"metrics": metrics.to_dict()}}

    async def _handle_get_health(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle get_health request.

        Args:
            params: Request parameters

        Returns:
            Response dictionary
        """
        active_count = self._manager.active_task_count if self._manager else 0

        health = await self._monitor.check_health(active_task_count=active_count)

        return {"status": "ok", "data": {"health": health.to_dict()}}

    async def _handle_get_statistics(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle get_statistics request.

        Args:
            params: Request parameters

        Returns:
            Response dictionary
        """
        statistics = await self._monitor.get_task_statistics()

        return {"status": "ok", "data": {"statistics": statistics}}

    async def _handle_cleanup_tasks(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle cleanup_tasks request.

        Args:
            params: Request parameters

        Returns:
            Response dictionary
        """
        retention_days = params.get("retention_days", self.cleanup_retention_days)
        max_tasks = params.get("max_tasks", self.cleanup_max_tasks)

        deleted_count = await self.storage.cleanup_old_tasks(
            retention_days=retention_days,
            max_tasks=max_tasks,
        )

        return {
            "status": "ok",
            "data": {
                "deleted_count": deleted_count,
                "retention_days": retention_days,
                "max_tasks": max_tasks,
            },
        }

    async def _run_cleanup_loop(self) -> None:
        """Run periodic cleanup of old tasks."""
        logger.info("Starting cleanup loop")

        while self._running:
            try:
                # Wait for cleanup interval
                await asyncio.sleep(self.cleanup_interval_hours * 3600)

                if not self._running:
                    break

                logger.info("Running automatic cleanup")
                deleted_count = await self.storage.cleanup_old_tasks(
                    retention_days=self.cleanup_retention_days,
                    max_tasks=self.cleanup_max_tasks,
                )
                logger.info(f"Cleanup complete: deleted {deleted_count} tasks")

            except asyncio.CancelledError:
                logger.info("Cleanup loop cancelled")
                break
            except Exception as e:
                logger.error(f"Error in cleanup loop: {e}")
                # Continue running despite errors

    def _write_pid_file(self) -> None:
        """Write PID file."""
        self.pid_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.pid_file, "w") as f:
            f.write(str(os.getpid()))

    def _remove_pid_file(self) -> None:
        """Remove PID file."""
        if self.pid_file.exists():
            self.pid_file.unlink()

    def _setup_signal_handlers(self) -> None:
        """Set up signal handlers for graceful shutdown."""

        def signal_handler(signum, frame):
            print(f"\nReceived signal {signum}")
            self._running = False

        # Set up platform-appropriate signal handlers
        signal.signal(signal.SIGINT, signal_handler)

        # SIGTERM is not available on Windows
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, signal_handler)

        # On Windows, also handle SIGBREAK if available
        if platform.system() == "Windows" and hasattr(signal, "SIGBREAK"):
            signal.signal(signal.SIGBREAK, signal_handler)

    @staticmethod
    def is_running(pid_file: str = "~/.exobrain/task-daemon.pid") -> bool:
        """
        Check if daemon is running.

        Args:
            pid_file: Path to PID file

        Returns:
            True if daemon is running, False otherwise
        """
        pid_file_path = Path(pid_file).expanduser()

        if not pid_file_path.exists():
            return False

        try:
            with open(pid_file_path, "r") as f:
                pid = int(f.read().strip())

            # Check if process exists (cross-platform)
            return _is_process_running(pid)

        except (ValueError, IOError):
            return False

    @staticmethod
    def get_pid(pid_file: str = "~/.exobrain/task-daemon.pid") -> Optional[int]:
        """
        Get daemon PID.

        Args:
            pid_file: Path to PID file

        Returns:
            PID if daemon is running, None otherwise
        """
        pid_file_path = Path(pid_file).expanduser()

        if not pid_file_path.exists():
            return None

        try:
            with open(pid_file_path, "r") as f:
                return int(f.read().strip())
        except (ValueError, IOError):
            return None
