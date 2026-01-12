"""Tests for TaskClient."""

import pytest

from exobrain.tasks import DaemonConnectionError, DaemonNotRunningError, TaskClient, TransportType

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
def client(test_paths):
    """Create a test client."""
    return TaskClient(
        transport_type=TransportType.UNIX,
        transport_config={"socket_path": test_paths["socket_path"]},
        pid_file=test_paths["pid_file"],
        auto_start=False,
    )


def test_client_creation(test_paths):
    """Test client can be created."""
    client = TaskClient(
        transport_type=TransportType.AUTO,
        transport_config={},
        pid_file=test_paths["pid_file"],
        auto_start=False,
    )

    assert client.transport_type == TransportType.AUTO
    assert client.auto_start is False
    assert client.max_retries == 3
    assert client.retry_delay == 0.5


def test_daemon_not_running(client):
    """Test checking daemon status when not running."""
    assert not client.is_daemon_running()
    assert client.get_daemon_pid() is None


def test_stale_pid_file_cleanup(test_paths, client):
    """Test that stale PID files are cleaned up."""
    # Create a stale PID file with a non-existent PID
    client.pid_file.parent.mkdir(parents=True, exist_ok=True)
    with open(client.pid_file, "w") as f:
        f.write("999999")

    # Check daemon status - should clean up stale PID file
    assert not client.is_daemon_running()
    assert not client.pid_file.exists()


@pytest.mark.anyio
async def test_connect_without_daemon(client):
    """Test connecting when daemon is not running."""
    with pytest.raises(DaemonNotRunningError):
        await client.connect()


async def test_send_request_not_connected(client):
    """Test sending request when not connected."""
    with pytest.raises(DaemonConnectionError):
        await client.ping()


def test_client_config():
    """Test client configuration."""
    client = TaskClient(
        transport_type=TransportType.UNIX,
        transport_config={"socket_path": "/tmp/test.sock"},
        pid_file="/tmp/test.pid",
        auto_start=True,
        max_retries=5,
        retry_delay=1.0,
    )

    assert client.transport_type == TransportType.UNIX
    assert client.transport_config["socket_path"] == "/tmp/test.sock"
    assert str(client.pid_file) == "/tmp/test.pid"
    assert client.auto_start is True
    assert client.max_retries == 5
    assert client.retry_delay == 1.0
