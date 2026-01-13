"""Tests for Phase 4: CLI & Tools.

These tests verify that the task management tools work correctly.
Since the tools use TaskClient which requires a daemon, we test them
by mocking the client or testing the tool logic directly.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from exobrain.tasks import Task, TaskStatus, TaskType
from exobrain.tools.task_tools import (
    CancelTaskTool,
    CreateTaskTool,
    GetTaskOutputTool,
    GetTaskStatusTool,
    ListTasksTool,
)


# Mock Task for testing
def create_mock_task(
    task_id="task-abc123",
    name="Test Task",
    task_type=TaskType.PROCESS,
    status=TaskStatus.RUNNING,
):
    """Create a mock task for testing."""
    task = MagicMock(spec=Task)
    task.task_id = task_id
    task.name = name
    task.task_type = task_type
    task.status = status
    task.description = "Test description"
    task.created_at = "2026-01-12 10:00:00"
    task.started_at = "2026-01-12 10:00:05"
    task.completed_at = None
    task.duration = 10.5
    task.iterations = 5
    task.max_iterations = 100
    task.exit_code = None
    task.error = None
    return task


# CreateTaskTool Tests


@pytest.mark.anyio
async def test_create_task_tool_success():
    """Test CreateTaskTool with successful task creation."""
    tool = CreateTaskTool(enabled=True)

    mock_task = create_mock_task()

    with patch("exobrain.tools.task_tools.TaskClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.create_task.return_value = mock_task
        mock_client_class.return_value = mock_client

        result = await tool.execute(
            name="Test Task",
            description="Test description",
            task_type="process",
            config={"command": "echo 'Hello'"},
        )

        assert "Task created successfully" in result
        assert "task-abc123" in result
        assert "Test Task" in result
        assert "process" in result


@pytest.mark.anyio
async def test_create_task_tool_missing_name():
    """Test CreateTaskTool with missing name."""
    tool = CreateTaskTool(enabled=True)

    result = await tool.execute(
        task_type="process",
        config={"command": "echo 'Hello'"},
    )

    assert "Error" in result
    assert "name parameter is required" in result


@pytest.mark.anyio
async def test_create_task_tool_missing_type():
    """Test CreateTaskTool with missing task_type."""
    tool = CreateTaskTool(enabled=True)

    result = await tool.execute(
        name="Test Task",
        config={"command": "echo 'Hello'"},
    )

    assert "Error" in result
    assert "task_type parameter is required" in result


@pytest.mark.anyio
async def test_create_task_tool_invalid_type():
    """Test CreateTaskTool with invalid task_type."""
    tool = CreateTaskTool(enabled=True)

    result = await tool.execute(
        name="Test Task",
        task_type="invalid",
        config={},
    )

    assert "Error" in result
    assert "invalid task_type" in result


@pytest.mark.anyio
async def test_create_task_tool_disabled():
    """Test CreateTaskTool when disabled."""
    tool = CreateTaskTool(enabled=False)

    result = await tool.execute(
        name="Test Task",
        task_type="process",
        config={"command": "echo 'Hello'"},
    )

    assert "Error" in result
    assert "not enabled" in result


# GetTaskStatusTool Tests


@pytest.mark.anyio
async def test_get_task_status_tool_success():
    """Test GetTaskStatusTool with successful status retrieval."""
    tool = GetTaskStatusTool(enabled=True)

    mock_task = create_mock_task()

    with patch("exobrain.tools.task_tools.TaskClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get_task.return_value = mock_task
        mock_client_class.return_value = mock_client

        result = await tool.execute(task_id="task-abc123")

        assert "Task Status" in result
        assert "task-abc123" in result
        assert "Test Task" in result
        assert "process" in result
        assert "running" in result


@pytest.mark.anyio
async def test_get_task_status_tool_missing_id():
    """Test GetTaskStatusTool with missing task_id."""
    tool = GetTaskStatusTool(enabled=True)

    result = await tool.execute()

    assert "Error" in result
    assert "task_id parameter is required" in result


@pytest.mark.anyio
async def test_get_task_status_tool_disabled():
    """Test GetTaskStatusTool when disabled."""
    tool = GetTaskStatusTool(enabled=False)

    result = await tool.execute(task_id="task-abc123")

    assert "Error" in result
    assert "not enabled" in result


# ListTasksTool Tests


@pytest.mark.anyio
async def test_list_tasks_tool_success():
    """Test ListTasksTool with successful task listing."""
    tool = ListTasksTool(enabled=True)

    mock_tasks = [
        create_mock_task(task_id="task-1", name="Task 1"),
        create_mock_task(task_id="task-2", name="Task 2"),
    ]

    with patch("exobrain.tools.task_tools.TaskClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.list_tasks.return_value = mock_tasks
        mock_client_class.return_value = mock_client

        result = await tool.execute()

        assert "Found 2 task(s)" in result
        assert "Task 1" in result
        assert "Task 2" in result


@pytest.mark.anyio
async def test_list_tasks_tool_empty():
    """Test ListTasksTool with no tasks."""
    tool = ListTasksTool(enabled=True)

    with patch("exobrain.tools.task_tools.TaskClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.list_tasks.return_value = []
        mock_client_class.return_value = mock_client

        result = await tool.execute()

        assert "No tasks found" in result


@pytest.mark.anyio
async def test_list_tasks_tool_with_filter():
    """Test ListTasksTool with status filter."""
    tool = ListTasksTool(enabled=True)

    mock_tasks = [create_mock_task(status=TaskStatus.RUNNING)]

    with patch("exobrain.tools.task_tools.TaskClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.list_tasks.return_value = mock_tasks
        mock_client_class.return_value = mock_client

        result = await tool.execute(status="running")

        assert "Found 1 task(s)" in result


@pytest.mark.anyio
async def test_list_tasks_tool_invalid_status():
    """Test ListTasksTool with invalid status."""
    tool = ListTasksTool(enabled=True)

    result = await tool.execute(status="invalid")

    assert "Error" in result
    assert "invalid status" in result


@pytest.mark.anyio
async def test_list_tasks_tool_disabled():
    """Test ListTasksTool when disabled."""
    tool = ListTasksTool(enabled=False)

    result = await tool.execute()

    assert "Error" in result
    assert "not enabled" in result


# GetTaskOutputTool Tests


@pytest.mark.anyio
async def test_get_task_output_tool_success():
    """Test GetTaskOutputTool with successful output retrieval."""
    tool = GetTaskOutputTool(enabled=True)

    with patch("exobrain.tools.task_tools.TaskClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get_output.return_value = "Hello World\n"
        mock_client_class.return_value = mock_client

        result = await tool.execute(task_id="task-abc123")

        assert "Hello World" in result


@pytest.mark.anyio
async def test_get_task_output_tool_no_output():
    """Test GetTaskOutputTool with no output."""
    tool = GetTaskOutputTool(enabled=True)

    with patch("exobrain.tools.task_tools.TaskClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.get_output.return_value = ""
        mock_client_class.return_value = mock_client

        result = await tool.execute(task_id="task-abc123")

        assert "No output available yet" in result


@pytest.mark.anyio
async def test_get_task_output_tool_missing_id():
    """Test GetTaskOutputTool with missing task_id."""
    tool = GetTaskOutputTool(enabled=True)

    result = await tool.execute()

    assert "Error" in result
    assert "task_id parameter is required" in result


@pytest.mark.anyio
async def test_get_task_output_tool_disabled():
    """Test GetTaskOutputTool when disabled."""
    tool = GetTaskOutputTool(enabled=False)

    result = await tool.execute(task_id="task-abc123")

    assert "Error" in result
    assert "not enabled" in result


# CancelTaskTool Tests


@pytest.mark.anyio
async def test_cancel_task_tool_success():
    """Test CancelTaskTool with successful cancellation."""
    tool = CancelTaskTool(enabled=True)

    mock_task = create_mock_task(status=TaskStatus.CANCELLED)

    with patch("exobrain.tools.task_tools.TaskClient") as mock_client_class:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None
        mock_client.cancel_task.return_value = mock_task
        mock_client_class.return_value = mock_client

        result = await tool.execute(task_id="task-abc123")

        assert "Task cancelled successfully" in result
        assert "task-abc123" in result
        assert "cancelled" in result


@pytest.mark.anyio
async def test_cancel_task_tool_missing_id():
    """Test CancelTaskTool with missing task_id."""
    tool = CancelTaskTool(enabled=True)

    result = await tool.execute()

    assert "Error" in result
    assert "task_id parameter is required" in result


@pytest.mark.anyio
async def test_cancel_task_tool_disabled():
    """Test CancelTaskTool when disabled."""
    tool = CancelTaskTool(enabled=False)

    result = await tool.execute(task_id="task-abc123")

    assert "Error" in result
    assert "not enabled" in result


# Tool Configuration Tests


def test_create_task_tool_from_config():
    """Test CreateTaskTool.from_config()."""
    # Mock config with tasks enabled
    config = MagicMock()
    config.tasks = MagicMock()
    config.tasks.enabled = True

    tool = CreateTaskTool.from_config(config)

    assert tool is not None
    assert tool._enabled is True


def test_create_task_tool_from_config_disabled():
    """Test CreateTaskTool.from_config() with tasks disabled."""
    # Mock config with tasks disabled
    config = MagicMock()
    config.tasks = MagicMock()
    config.tasks.enabled = False

    tool = CreateTaskTool.from_config(config)

    assert tool is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
