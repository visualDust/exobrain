"""Tests for TaskDaemon."""

import os
from pathlib import Path

import pytest

from exobrain.tasks import TaskDaemon, TransportType

# Configure pytest-anyio
pytestmark = pytest.mark.anyio


@pytest.fixture
def test_paths(tmp_path):
    """Create test paths."""
    storage_path = tmp_path / "tasks"
    pid_file = tmp_path / "daemon.pid"
    socket_path = tmp_path / "daemon.sock"

    return {
        "storage_path": str(storage_path),
        "pid_file": str(pid_file),
        "socket_path": str(socket_path),
    }


@pytest.fixture
def daemon(test_paths):
    """Create a test daemon."""
    return TaskDaemon(
        storage_path=test_paths["storage_path"],
        transport_type=TransportType.UNIX,
        transport_config={"socket_path": test_paths["socket_path"]},
        pid_file=test_paths["pid_file"],
    )


def test_daemon_creation(daemon, test_paths):
    """Test daemon can be created."""
    assert daemon.storage is not None
    assert daemon.transport_type == TransportType.UNIX
    assert str(daemon.pid_file) == test_paths["pid_file"]


def test_daemon_is_running_static(test_paths):
    """Test static is_running method."""
    # Daemon not running
    assert not TaskDaemon.is_running(test_paths["pid_file"])

    # Create PID file with current process
    pid_file = Path(test_paths["pid_file"])
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    with open(pid_file, "w") as f:
        f.write(str(os.getpid()))

    # Should detect running process
    assert TaskDaemon.is_running(test_paths["pid_file"])

    # Clean up
    pid_file.unlink()


def test_daemon_get_pid_static(test_paths):
    """Test static get_pid method."""
    # No PID file
    assert TaskDaemon.get_pid(test_paths["pid_file"]) is None

    # Create PID file
    pid_file = Path(test_paths["pid_file"])
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    test_pid = 12345
    with open(pid_file, "w") as f:
        f.write(str(test_pid))

    # Should read PID
    assert TaskDaemon.get_pid(test_paths["pid_file"]) == test_pid

    # Clean up
    pid_file.unlink()


pytestmark = pytest.mark.anyio


@pytest.mark.anyio
async def test_daemon_start_stop(daemon, test_paths):
    """Test daemon start and stop."""
    # Start daemon
    await daemon.start()

    # Check PID file was created
    assert Path(test_paths["pid_file"]).exists()

    # Check socket was created
    assert Path(test_paths["socket_path"]).exists()

    # Check daemon is running
    assert daemon._running is True
    assert daemon._server is not None

    # Stop daemon
    await daemon.stop()

    # Check daemon stopped
    assert daemon._running is False
    assert daemon._server is None

    # Check PID file was removed
    assert not Path(test_paths["pid_file"]).exists()


pytestmark = pytest.mark.anyio


@pytest.mark.anyio
async def test_daemon_request_handling(daemon):
    """Test daemon request handling."""
    await daemon.start()

    try:
        # Test ping request
        response = await daemon._handle_request({"action": "ping", "params": {}})
        assert response["status"] == "ok"
        assert response["data"]["message"] == "pong"

        # Test unknown action
        response = await daemon._handle_request({"action": "unknown", "params": {}})
        assert response["status"] == "error"
        assert "Unknown action" in response["error"]

        # Test missing action
        response = await daemon._handle_request({"params": {}})
        assert response["status"] == "error"
        assert "Missing 'action' field" in response["error"]

    finally:
        await daemon.stop()


pytestmark = pytest.mark.anyio


@pytest.mark.anyio
async def test_daemon_create_task(daemon):
    """Test creating a task through daemon."""
    await daemon.start()

    try:
        # Create task
        response = await daemon._handle_create_task(
            {
                "name": "Test Task",
                "description": "Test description",
                "task_type": "agent",
                "config": {},
            }
        )

        assert response["status"] == "ok"
        assert "task" in response["data"]

        task_data = response["data"]["task"]
        assert task_data["name"] == "Test Task"
        assert task_data["description"] == "Test description"
        assert task_data["task_type"] == "agent"

    finally:
        await daemon.stop()


pytestmark = pytest.mark.anyio


@pytest.mark.anyio
async def test_daemon_list_tasks(daemon):
    """Test listing tasks through daemon."""
    await daemon.start()

    try:
        # Create a task first
        await daemon._handle_create_task({"name": "Test Task", "task_type": "agent", "config": {}})

        # List tasks
        response = await daemon._handle_list_tasks({})

        assert response["status"] == "ok"
        assert "tasks" in response["data"]
        assert "count" in response["data"]
        assert response["data"]["count"] >= 1

    finally:
        await daemon.stop()
