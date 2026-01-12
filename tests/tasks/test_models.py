"""Tests for task models."""

from datetime import datetime

from exobrain.tasks.models import Task, TaskStatus, TaskType


def test_task_creation():
    """Test basic task creation."""
    task = Task(name="Test Task", description="A test task", task_type=TaskType.AGENT)

    assert task.name == "Test Task"
    assert task.description == "A test task"
    assert task.task_type == TaskType.AGENT
    assert task.status == TaskStatus.PENDING
    assert task.task_id.startswith("task-")


def test_task_serialization():
    """Test task to_dict and from_dict."""
    task = Task(name="Test Task", task_type=TaskType.AGENT)

    # Convert to dict
    task_dict = task.to_dict()
    assert isinstance(task_dict, dict)
    assert task_dict["name"] == "Test Task"
    assert task_dict["task_type"] == "agent"

    # Convert back from dict
    task2 = Task.from_dict(task_dict)
    assert task2.task_id == task.task_id
    assert task2.name == task.name
    assert task2.task_type == task.task_type


def test_task_properties():
    """Test task helper properties."""
    task = Task(name="Test", task_type=TaskType.AGENT)

    # Test is_active
    assert task.is_active is True
    assert task.is_terminal is False

    # Change status
    task.status = TaskStatus.COMPLETED
    assert task.is_active is False
    assert task.is_terminal is True


def test_task_duration():
    """Test task duration calculation."""
    task = Task(name="Test", task_type=TaskType.AGENT)

    # No duration before started
    assert task.duration is None

    # Set started time
    task.started_at = datetime.now()
    assert task.duration is not None
    assert task.duration >= 0
