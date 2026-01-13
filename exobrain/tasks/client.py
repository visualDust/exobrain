"""Task client for communicating with the task daemon."""

import asyncio
import json
import os
import platform
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from exobrain import __version__

from .models import Task, TaskStatus, TaskType
from .transport import Transport, TransportFactory, TransportType


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


def _terminate_process(pid: int, force: bool = False) -> None:
    """
    Terminate a process with the given PID.

    Cross-platform implementation that works on Unix, Linux, macOS, and Windows.

    Args:
        pid: Process ID to terminate
        force: If True, force kill the process (SIGKILL on Unix, TerminateProcess on Windows)

    Raises:
        ProcessLookupError: If process doesn't exist
        PermissionError: If insufficient permissions
    """
    if platform.system() == "Windows":
        try:
            import ctypes

            PROCESS_TERMINATE = 0x0001
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
            if not handle:
                raise ProcessLookupError(f"Process {pid} not found")

            # TerminateProcess with exit code 1
            success = ctypes.windll.kernel32.TerminateProcess(handle, 1)
            ctypes.windll.kernel32.CloseHandle(handle)

            if not success:
                raise OSError(f"Failed to terminate process {pid}")
        except (AttributeError, OSError) as e:
            # Fallback: try using taskkill
            try:
                cmd = ["taskkill", "/F" if force else "/T", "/PID", str(pid)]
                subprocess.run(cmd, check=True, capture_output=True, timeout=5)
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
                raise ProcessLookupError(f"Failed to terminate process {pid}") from e
    else:
        # On Unix/Linux/macOS, use os.kill with appropriate signal
        sig = signal.SIGKILL if force else signal.SIGTERM
        os.kill(pid, sig)


class DaemonNotRunningError(Exception):
    """Raised when daemon is not running."""


class DaemonConnectionError(Exception):
    """Raised when connection to daemon fails."""


class DaemonVersionMismatchError(Exception):
    """Raised when daemon version doesn't match client version."""


class TaskClient:
    """High-level client for task management."""

    def __init__(
        self,
        transport_type: TransportType = TransportType.AUTO,
        transport_config: Optional[Dict[str, Any]] = None,
        pid_file: str = "~/.exobrain/task-daemon.pid",
        auto_start: bool = True,
        max_retries: int = 3,
        retry_delay: float = 0.5,
    ):
        """
        Initialize task client.

        Args:
            transport_type: Type of transport to use
            transport_config: Transport-specific configuration
            pid_file: Path to daemon PID file
            auto_start: Auto-start daemon if not running
            max_retries: Maximum number of connection retries
            retry_delay: Delay between retries in seconds
        """
        self.transport_type = transport_type
        self.transport_config = transport_config or {}
        self.pid_file = Path(pid_file).expanduser()
        self.auto_start = auto_start
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        self._transport: Optional[Transport] = None

    async def connect(self) -> None:
        """
        Connect to the daemon.

        Raises:
            DaemonNotRunningError: If daemon is not running and auto_start is False
            DaemonConnectionError: If connection fails after retries
            DaemonVersionMismatchError: If daemon version doesn't match and has running tasks
        """
        # Check if daemon is running
        if not self.is_daemon_running():
            if self.auto_start:
                await self.start_daemon()
            else:
                raise DaemonNotRunningError(
                    "Task daemon is not running. Start it with: exobrain task daemon start"
                )

        # Check version compatibility
        await self._check_version_compatibility()

        # Create transport
        self._transport = TransportFactory.create_transport(
            self.transport_type, self.transport_config
        )

        # Try to connect with retries
        last_error = None
        for attempt in range(self.max_retries):
            try:
                await self._transport.connect()
                return
            except Exception as e:
                last_error = e
                if attempt < self.max_retries - 1:
                    await asyncio.sleep(self.retry_delay)

        raise DaemonConnectionError(
            f"Failed to connect to daemon after {self.max_retries} attempts: {last_error}"
        )

    async def _check_version_compatibility(self) -> None:
        """
        Check if daemon version matches client version.

        If versions don't match:
        - If no running tasks: automatically restart daemon
        - If running tasks exist: raise DaemonVersionMismatchError

        Raises:
            DaemonVersionMismatchError: If version mismatch and running tasks exist
        """
        daemon_version = self.get_daemon_version()

        # If daemon version is None (old format PID file), skip check
        if daemon_version is None:
            return

        # Check if versions match
        if daemon_version == __version__:
            return

        # Versions don't match - check for running tasks
        try:
            # Create temporary transport to check tasks
            temp_transport = TransportFactory.create_transport(
                self.transport_type, self.transport_config
            )
            await temp_transport.connect()

            try:
                # Check for running tasks
                request = {"action": "list_tasks", "params": {"status": "running"}}
                response = await temp_transport.send_request(request)

                if response.get("status") == "ok":
                    running_tasks = response.get("data", {}).get("tasks", [])

                    if running_tasks:
                        # Has running tasks - cannot auto-restart
                        raise DaemonVersionMismatchError(
                            f"Daemon version mismatch: daemon={daemon_version}, client={__version__}. "
                            f"There are {len(running_tasks)} running task(s). "
                            f"Please wait for tasks to complete or cancel them, then restart the daemon manually with: "
                            f"exobrain task daemon restart"
                        )

                # No running tasks - safe to restart
                await temp_transport.disconnect()

                # Restart daemon
                print(
                    f"Daemon version mismatch detected (daemon={daemon_version}, client={__version__}). "
                    f"No running tasks found. Restarting daemon..."
                )
                await self.restart_daemon(timeout=10.0)
                print("Daemon restarted successfully.")

            finally:
                await temp_transport.disconnect()

        except DaemonVersionMismatchError:
            # Re-raise version mismatch errors
            raise
        except Exception as e:
            # If we can't check, log warning and continue
            print(
                f"Warning: Could not verify daemon version compatibility: {e}. Continuing anyway..."
            )

    async def disconnect(self) -> None:
        """Disconnect from the daemon."""
        if self._transport:
            await self._transport.disconnect()
            self._transport = None

    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect()

    def is_daemon_running(self) -> bool:
        """
        Check if daemon is running.

        Returns:
            True if daemon is running, False otherwise
        """
        pid_data = self._read_pid_file()
        if not pid_data:
            return False

        pid = pid_data.get("pid")
        if not pid:
            return False

        # Check if process exists (cross-platform)
        if _is_process_running(pid):
            return True
        else:
            # Process is dead - clean up stale PID file
            if self.pid_file.exists():
                try:
                    self.pid_file.unlink()
                except Exception:
                    pass
            return False

    def get_daemon_pid(self) -> Optional[int]:
        """
        Get daemon PID.

        Returns:
            PID if daemon is running, None otherwise
        """
        pid_data = self._read_pid_file()
        return pid_data.get("pid") if pid_data else None

    def get_daemon_version(self) -> Optional[str]:
        """
        Get daemon version.

        Returns:
            Version string if daemon is running, None otherwise
        """
        pid_data = self._read_pid_file()
        return pid_data.get("version") if pid_data else None

    def _read_pid_file(self) -> Optional[Dict[str, Any]]:
        """
        Read PID file and return data.

        Returns:
            Dictionary with 'pid' and 'version' keys, or None if file doesn't exist or is invalid
        """
        if not self.pid_file.exists():
            return None

        try:
            with open(self.pid_file, "r") as f:
                content = f.read().strip()

                # Try to parse as JSON (new format)
                try:
                    data = json.loads(content)
                    if isinstance(data, dict) and "pid" in data:
                        return data
                except json.JSONDecodeError:
                    pass

                # Fall back to old format (just PID number)
                try:
                    pid = int(content)
                    return {"pid": pid, "version": None}
                except ValueError:
                    return None

        except (IOError, OSError):
            return None

    async def start_daemon(self, wait: bool = True, timeout: float = 5.0) -> int:
        """
        Start the daemon process.

        Args:
            wait: Wait for daemon to be ready
            timeout: Maximum time to wait for daemon to start

        Returns:
            Daemon PID

        Raises:
            RuntimeError: If daemon fails to start
        """
        # Check if already running
        if self.is_daemon_running():
            pid = self.get_daemon_pid()
            return pid

        # Build command to run daemon as module
        cmd = [sys.executable, "-m", "exobrain.tasks.daemon_runner"]

        # Add transport type
        if self.transport_type != TransportType.AUTO:
            cmd.extend(["--transport", self.transport_type.value])

        # Add transport config
        if self.transport_config:
            if "socket_path" in self.transport_config:
                cmd.extend(["--socket-path", self.transport_config["socket_path"]])
            if "pipe_name" in self.transport_config:
                cmd.extend(["--pipe-name", self.transport_config["pipe_name"]])
            if "host" in self.transport_config:
                cmd.extend(["--host", self.transport_config["host"]])
            if "port" in self.transport_config:
                cmd.extend(["--port", str(self.transport_config["port"])])

        # Add PID file
        cmd.extend(["--pid-file", str(self.pid_file)])

        # Start daemon as background process
        subprocess.Popen(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True
        )

        # Wait for daemon to be ready
        if wait:
            start_time = time.time()
            while time.time() - start_time < timeout:
                if self.is_daemon_running():
                    # Give it a moment to fully initialize
                    await asyncio.sleep(0.2)
                    return self.get_daemon_pid()
                await asyncio.sleep(0.1)

            raise RuntimeError(f"Daemon failed to start within {timeout} seconds")

        return None

    async def stop_daemon(self, timeout: float = 5.0) -> bool:
        """
        Stop the daemon process.

        Args:
            timeout: Maximum time to wait for daemon to stop

        Returns:
            True if daemon was stopped, False if it wasn't running

        Raises:
            RuntimeError: If daemon fails to stop
        """
        pid = self.get_daemon_pid()
        if not pid:
            return False

        try:
            # Send termination signal (cross-platform)
            _terminate_process(pid, force=False)

            # Wait for daemon to stop
            start_time = time.time()
            while time.time() - start_time < timeout:
                if not self.is_daemon_running():
                    return True
                await asyncio.sleep(0.1)

            # Force kill if still running
            _terminate_process(pid, force=True)
            await asyncio.sleep(0.1)

            if self.is_daemon_running():
                raise RuntimeError(f"Failed to stop daemon (PID: {pid})")

            return True

        except ProcessLookupError:
            # Process already dead
            return True

    async def restart_daemon(self, timeout: float = 5.0) -> int:
        """
        Restart the daemon process.

        Args:
            timeout: Maximum time to wait for daemon to restart

        Returns:
            New daemon PID

        Raises:
            RuntimeError: If daemon fails to restart
        """
        await self.stop_daemon(timeout)
        return await self.start_daemon(wait=True, timeout=timeout)

    async def get_daemon_status(self) -> Dict[str, Any]:
        """
        Get daemon status information.

        Returns:
            Status dictionary with daemon information
        """
        pid = self.get_daemon_pid()
        running = self.is_daemon_running()

        status = {
            "running": running,
            "pid": pid,
            "transport_type": self.transport_type.value,
            "pid_file": str(self.pid_file),
        }

        if running:
            try:
                # Try to ping daemon
                async with self:
                    response = await self.ping()
                    status["responsive"] = response.get("status") == "ok"
            except Exception as e:
                status["responsive"] = False
                status["error"] = str(e)

        return status

    async def _send_request(
        self, action: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Send a request to the daemon.

        Args:
            action: Action to perform
            params: Request parameters

        Returns:
            Response dictionary

        Raises:
            DaemonConnectionError: If not connected
            RuntimeError: If request fails
        """
        if not self._transport or not self._transport.is_connected():
            raise DaemonConnectionError("Not connected to daemon")

        request = {"action": action, "params": params or {}}

        response = await self._transport.send_request(request)

        if response.get("status") == "error":
            raise RuntimeError(response.get("error", "Unknown error"))

        return response

    async def ping(self) -> Dict[str, Any]:
        """
        Ping the daemon.

        Returns:
            Response dictionary
        """
        return await self._send_request("ping")

    async def create_task(
        self,
        name: str,
        description: str = "",
        task_type: TaskType = TaskType.AGENT,
        config: Optional[Dict[str, Any]] = None,
    ) -> Task:
        """
        Create a new task.

        Args:
            name: Task name
            description: Task description
            task_type: Type of task
            config: Task configuration

        Returns:
            Created task
        """
        params = {
            "name": name,
            "description": description,
            "task_type": task_type.value,
            "config": config or {},
        }

        response = await self._send_request("create_task", params)
        return Task.from_dict(response["data"]["task"])

    async def get_task(self, task_id: str) -> Task:
        """
        Get a task by ID.

        Args:
            task_id: Task ID

        Returns:
            Task object
        """
        params = {"task_id": task_id}
        response = await self._send_request("get_task", params)
        return Task.from_dict(response["data"]["task"])

    async def list_tasks(
        self,
        status: Optional[TaskStatus] = None,
        task_type: Optional[TaskType] = None,
        limit: Optional[int] = None,
    ) -> List[Task]:
        """
        List tasks.

        Args:
            status: Filter by status
            task_type: Filter by type
            limit: Maximum number of tasks to return

        Returns:
            List of tasks
        """
        params = {}
        if status:
            params["status"] = status.value
        if task_type:
            params["task_type"] = task_type.value
        if limit:
            params["limit"] = limit

        response = await self._send_request("list_tasks", params)
        return [Task.from_dict(task_dict) for task_dict in response["data"]["tasks"]]

    async def cancel_task(self, task_id: str) -> Task:
        """
        Cancel a task.

        Args:
            task_id: Task ID

        Returns:
            Updated task
        """
        params = {"task_id": task_id}
        response = await self._send_request("cancel_task", params)
        return Task.from_dict(response["data"]["task"])

    async def delete_task(self, task_id: str) -> str:
        """
        Delete a task.

        Args:
            task_id: Task ID

        Returns:
            Deleted task ID
        """
        params = {"task_id": task_id}
        response = await self._send_request("delete_task", params)
        return response["data"]["task_id"]

    async def get_output(self, task_id: str, offset: int = 0, limit: Optional[int] = None) -> str:
        """
        Get task output.

        Args:
            task_id: Task ID
            offset: Offset in output
            limit: Maximum number of bytes to read

        Returns:
            Task output
        """
        params = {"task_id": task_id, "offset": offset}
        if limit:
            params["limit"] = limit

        response = await self._send_request("get_output", params)
        return response["data"]["output"]

    async def follow_output(
        self, task_id: str, poll_interval: float = 0.5, callback: Optional[callable] = None
    ) -> None:
        """
        Follow task output in real-time.

        Args:
            task_id: Task ID
            poll_interval: Polling interval in seconds
            callback: Optional callback for each output chunk
        """
        offset = 0

        while True:
            # Get task status
            task = await self.get_task(task_id)

            # Get new output
            output = await self.get_output(task_id, offset)

            if output:
                if callback:
                    callback(output)
                else:
                    print(output, end="", flush=True)

                offset += len(output)

            # Check if task is done
            if task.is_terminal:
                break

            # Wait before next poll
            await asyncio.sleep(poll_interval)

    async def get_metrics(self) -> Dict[str, Any]:
        """
        Get task system metrics.

        Returns:
            Metrics dictionary
        """
        response = await self._send_request("get_metrics", {})
        return response["data"]["metrics"]

    async def get_health(self) -> Dict[str, Any]:
        """
        Get task system health status.

        Returns:
            Health status dictionary
        """
        response = await self._send_request("get_health", {})
        return response["data"]["health"]

    async def get_statistics(self) -> Dict[str, Any]:
        """
        Get detailed task statistics.

        Returns:
            Statistics dictionary
        """
        response = await self._send_request("get_statistics", {})
        return response["data"]["statistics"]

    async def cleanup_tasks(
        self, retention_days: Optional[int] = None, max_tasks: Optional[int] = None
    ) -> int:
        """
        Manually trigger task cleanup.

        Args:
            retention_days: Delete tasks older than this many days
            max_tasks: Keep at most this many tasks

        Returns:
            Number of tasks deleted
        """
        params = {}
        if retention_days is not None:
            params["retention_days"] = retention_days
        if max_tasks is not None:
            params["max_tasks"] = max_tasks

        response = await self._send_request("cleanup_tasks", params)
        return response["data"]["deleted_count"]
