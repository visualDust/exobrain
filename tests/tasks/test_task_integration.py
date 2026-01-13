"""Integration tests for TaskClient and TaskDaemon."""

import asyncio

import pytest

from exobrain.tasks import TaskClient, TaskDaemon, TaskStatus, TaskType, TransportType

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
async def running_daemon(test_paths):
    """Create and start a daemon for testing."""
    daemon = TaskDaemon(
        storage_path=test_paths["storage_path"],
        transport_type=TransportType.UNIX,
        transport_config={"socket_path": test_paths["socket_path"]},
        pid_file=test_paths["pid_file"],
    )

    await daemon.start()

    # Run daemon in background
    daemon_task = asyncio.create_task(daemon.run())

    yield daemon

    # Stop daemon
    await daemon.stop()
    daemon_task.cancel()
    try:
        await daemon_task
    except asyncio.CancelledError:
        pass


@pytest.fixture
def client(test_paths):
    """Create a test client."""
    return TaskClient(
        transport_type=TransportType.UNIX,
        transport_config={"socket_path": test_paths["socket_path"]},
        pid_file=test_paths["pid_file"],
        auto_start=False,
    )


pytestmark = pytest.mark.anyio


@pytest.mark.anyio
async def test_client_connect_disconnect(running_daemon, client):
    """Test client can connect and disconnect."""
    await client.connect()
    assert client._transport is not None
    assert client._transport.is_connected()

    await client.disconnect()
    assert client._transport is None


pytestmark = pytest.mark.anyio


@pytest.mark.anyio
async def test_client_context_manager(running_daemon, client):
    """Test client as context manager."""
    async with client:
        assert client._transport is not None
        assert client._transport.is_connected()

    assert client._transport is None


pytestmark = pytest.mark.anyio


@pytest.mark.anyio
async def test_client_ping(running_daemon, client):
    """Test client can ping daemon."""
    async with client:
        response = await client.ping()
        assert response["status"] == "ok"
        assert response["data"]["message"] == "pong"


pytestmark = pytest.mark.anyio


@pytest.mark.anyio
async def test_create_and_get_task(running_daemon, client):
    """Test creating and retrieving a task."""
    async with client:
        # Create task
        task = await client.create_task(
            name="Test Task",
            description="Test description",
            task_type=TaskType.AGENT,
        )

        assert task.task_id is not None
        assert task.name == "Test Task"
        assert task.description == "Test description"
        assert task.task_type == TaskType.AGENT
        assert task.status == TaskStatus.PENDING

        # Get task
        retrieved_task = await client.get_task(task.task_id)
        assert retrieved_task.task_id == task.task_id
        assert retrieved_task.name == task.name


pytestmark = pytest.mark.anyio


@pytest.mark.anyio
async def test_list_tasks(running_daemon, client):
    """Test listing tasks."""
    async with client:
        # Create multiple tasks
        task1 = await client.create_task(name="Task 1", task_type=TaskType.AGENT)
        task2 = await client.create_task(name="Task 2", task_type=TaskType.AGENT)

        # List all tasks
        tasks = await client.list_tasks()
        assert len(tasks) >= 2

        # Verify our tasks are in the list
        task_ids = [t.task_id for t in tasks]
        assert task1.task_id in task_ids
        assert task2.task_id in task_ids


pytestmark = pytest.mark.anyio


@pytest.mark.anyio
async def test_list_tasks_with_filters(running_daemon, client):
    """Test listing tasks with filters."""
    async with client:
        # Create tasks
        await client.create_task(name="Task 1", task_type=TaskType.AGENT)
        await client.create_task(name="Task 2", task_type=TaskType.AGENT)

        # List with status filter (tasks start immediately, so they should be RUNNING)
        tasks = await client.list_tasks(status=TaskStatus.RUNNING)
        assert len(tasks) >= 2
        assert all(t.status == TaskStatus.RUNNING for t in tasks)

        # List with limit
        tasks = await client.list_tasks(limit=1)
        assert len(tasks) == 1


pytestmark = pytest.mark.anyio


@pytest.mark.anyio
async def test_cancel_task(running_daemon, client):
    """Test cancelling a task."""
    async with client:
        # Create task
        task = await client.create_task(name="Test Task", task_type=TaskType.AGENT)

        # Cancel task
        cancelled_task = await client.cancel_task(task.task_id)

        assert cancelled_task.task_id == task.task_id
        assert cancelled_task.status == TaskStatus.CANCELLED


pytestmark = pytest.mark.anyio


@pytest.mark.anyio
async def test_delete_task(running_daemon, client):
    """Test deleting a task."""
    async with client:
        # Create task
        task = await client.create_task(name="Test Task", task_type=TaskType.AGENT)

        # Cancel task first (tasks that are running can't be deleted immediately)
        await client.cancel_task(task.task_id)

        # Delete task
        deleted_id = await client.delete_task(task.task_id)
        assert deleted_id == task.task_id

        # Task should not exist
        with pytest.raises(RuntimeError, match="Task not found"):
            await client.get_task(task.task_id)


pytestmark = pytest.mark.anyio


@pytest.mark.anyio
async def test_get_output(running_daemon, client):
    """Test getting task output."""
    async with client:
        # Create task
        task = await client.create_task(name="Test Task", task_type=TaskType.AGENT)

        # Get output (should be empty initially)
        output = await client.get_output(task.task_id)
        assert output == ""


pytestmark = pytest.mark.anyio


@pytest.mark.anyio
async def test_daemon_status(running_daemon, client):
    """Test getting daemon status."""
    status = await client.get_daemon_status()

    assert status["running"] is True
    assert status["pid"] is not None
    assert status["transport_type"] == "unix"
    assert status["responsive"] is True


pytestmark = pytest.mark.anyio


@pytest.mark.anyio
async def test_multiple_clients(running_daemon, test_paths):
    """Test multiple clients can connect simultaneously."""
    client1 = TaskClient(
        transport_type=TransportType.UNIX,
        transport_config={"socket_path": test_paths["socket_path"]},
        pid_file=test_paths["pid_file"],
        auto_start=False,
    )

    client2 = TaskClient(
        transport_type=TransportType.UNIX,
        transport_config={"socket_path": test_paths["socket_path"]},
        pid_file=test_paths["pid_file"],
        auto_start=False,
    )

    async with client1:
        async with client2:
            # Both clients should be able to ping
            response1 = await client1.ping()
            response2 = await client2.ping()

            assert response1["status"] == "ok"
            assert response2["status"] == "ok"

            # Create task with client1
            task = await client1.create_task(name="Test", task_type=TaskType.AGENT)

            # Retrieve with client2
            retrieved = await client2.get_task(task.task_id)
            assert retrieved.task_id == task.task_id
