"""Tests for task storage."""

import shutil
import tempfile

import pytest

from exobrain.tasks.models import Task, TaskType
from exobrain.tasks.storage import TaskStorage


@pytest.mark.anyio
async def test_storage_initialization():
    """Test storage initialization."""
    temp_dir = tempfile.mkdtemp()
    try:
        storage = TaskStorage(temp_dir)
        await storage.initialize()

        assert storage.storage_path.exists()
        assert storage.index_file.exists()
    finally:
        shutil.rmtree(temp_dir)


@pytest.mark.anyio
async def test_save_and_load_task():
    """Test saving and loading a task."""
    temp_dir = tempfile.mkdtemp()
    try:
        storage = TaskStorage(temp_dir)
        await storage.initialize()

        task = Task(name="Test Task", task_type=TaskType.AGENT)
        await storage.save_task(task)

        loaded_task = await storage.load_task(task.task_id)
        assert loaded_task is not None
        assert loaded_task.task_id == task.task_id
        assert loaded_task.name == task.name
    finally:
        shutil.rmtree(temp_dir)


@pytest.mark.anyio
async def test_list_tasks():
    """Test listing tasks."""
    temp_dir = tempfile.mkdtemp()
    try:
        storage = TaskStorage(temp_dir)
        await storage.initialize()

        task1 = Task(name="Task 1", task_type=TaskType.AGENT)
        task2 = Task(name="Task 2", task_type=TaskType.PROCESS)

        await storage.save_task(task1)
        await storage.save_task(task2)

        tasks = await storage.list_tasks()
        assert len(tasks) == 2
    finally:
        shutil.rmtree(temp_dir)


@pytest.mark.anyio
async def test_delete_task():
    """Test deleting a task."""
    temp_dir = tempfile.mkdtemp()
    try:
        storage = TaskStorage(temp_dir)
        await storage.initialize()

        task = Task(name="Test Task", task_type=TaskType.AGENT)
        await storage.save_task(task)

        deleted = await storage.delete_task(task.task_id)
        assert deleted is True

        loaded_task = await storage.load_task(task.task_id)
        assert loaded_task is None
    finally:
        shutil.rmtree(temp_dir)


@pytest.mark.anyio
async def test_output_operations():
    """Test output append and read."""
    temp_dir = tempfile.mkdtemp()
    try:
        storage = TaskStorage(temp_dir)
        await storage.initialize()

        task = Task(name="Test Task", task_type=TaskType.AGENT)
        await storage.save_task(task)

        await storage.append_output(task.task_id, "Line 1\n")
        await storage.append_output(task.task_id, "Line 2\n")

        output = await storage.read_output(task.task_id)
        assert "Line 1" in output
        assert "Line 2" in output
    finally:
        shutil.rmtree(temp_dir)
