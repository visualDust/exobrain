"""Tests for Phase 5: Advanced Features (Monitoring, Cleanup, Recovery)."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from exobrain.tasks import (
    HealthStatus,
    Task,
    TaskClient,
    TaskDaemon,
    TaskManager,
    TaskMetrics,
    TaskMonitor,
    TaskStatus,
    TaskStorage,
    TaskType,
)


@pytest.fixture
def temp_storage_path(tmp_path):
    """Create temporary storage path."""
    return str(tmp_path / "tasks")


@pytest.fixture
async def storage(temp_storage_path):
    """Create and initialize storage."""
    storage = TaskStorage(temp_storage_path)
    await storage.initialize()
    return storage


@pytest.fixture
async def manager(storage):
    """Create and initialize task manager."""
    manager = TaskManager(storage, max_concurrent_tasks=5)
    await manager.initialize()
    yield manager
    await manager.shutdown()


@pytest.fixture
def monitor(storage):
    """Create task monitor."""
    return TaskMonitor(storage, max_concurrent_tasks=5)


# ============================================================================
# TaskMonitor Tests
# ============================================================================


@pytest.mark.anyio
async def test_monitor_collect_metrics_empty(monitor):
    """Test collecting metrics with no tasks."""
    metrics = await monitor.collect_metrics()

    assert isinstance(metrics, TaskMetrics)
    assert metrics.total_tasks == 0
    assert metrics.pending_tasks == 0
    assert metrics.running_tasks == 0
    assert metrics.completed_tasks == 0
    assert metrics.failed_tasks == 0


@pytest.mark.anyio
async def test_monitor_collect_metrics_with_tasks(storage, monitor):
    """Test collecting metrics with various tasks."""
    # Create some tasks
    tasks = []

    # Completed task
    task1 = Task(
        name="Task 1",
        task_type=TaskType.AGENT,
        status=TaskStatus.COMPLETED,
        created_at=datetime.now() - timedelta(hours=2),
        started_at=datetime.now() - timedelta(hours=2),
        completed_at=datetime.now() - timedelta(hours=1),
    )
    await storage.save_task(task1)
    tasks.append(task1)

    # Failed task
    task2 = Task(
        name="Task 2",
        task_type=TaskType.PROCESS,
        status=TaskStatus.FAILED,
        created_at=datetime.now() - timedelta(hours=1),
        started_at=datetime.now() - timedelta(hours=1),
        completed_at=datetime.now() - timedelta(minutes=30),
    )
    await storage.save_task(task2)
    tasks.append(task2)

    # Running task
    task3 = Task(
        name="Task 3",
        task_type=TaskType.AGENT,
        status=TaskStatus.RUNNING,
        created_at=datetime.now() - timedelta(minutes=10),
        started_at=datetime.now() - timedelta(minutes=10),
    )
    await storage.save_task(task3)
    tasks.append(task3)

    # Collect metrics
    metrics = await monitor.collect_metrics(active_task_count=1)

    assert metrics.total_tasks == 3
    assert metrics.pending_tasks == 0
    assert metrics.running_tasks == 1
    assert metrics.completed_tasks == 1
    assert metrics.failed_tasks == 1
    assert metrics.agent_tasks == 2
    assert metrics.process_tasks == 1
    assert metrics.active_task_count == 1
    assert metrics.max_concurrent_tasks == 5


@pytest.mark.anyio
async def test_monitor_collect_metrics_calculates_durations(storage, monitor):
    """Test that metrics correctly calculate task durations."""
    # Create completed task with known duration
    task = Task(
        name="Task",
        task_type=TaskType.AGENT,
        status=TaskStatus.COMPLETED,
        created_at=datetime.now() - timedelta(hours=1),
        started_at=datetime.now() - timedelta(hours=1),
        completed_at=datetime.now() - timedelta(minutes=30),
    )
    await storage.save_task(task)

    metrics = await monitor.collect_metrics()

    # Duration should be approximately 30 minutes (1800 seconds)
    assert metrics.avg_duration_seconds > 1700
    assert metrics.avg_duration_seconds < 1900
    assert metrics.min_duration_seconds > 1700
    assert metrics.max_duration_seconds < 1900


@pytest.mark.anyio
async def test_monitor_collect_metrics_calculates_rates(storage, monitor):
    """Test that metrics correctly calculate success/failure rates."""
    # Create 3 completed, 1 failed
    for i in range(3):
        task = Task(
            name=f"Task {i}",
            task_type=TaskType.AGENT,
            status=TaskStatus.COMPLETED,
            created_at=datetime.now() - timedelta(hours=1),
            started_at=datetime.now() - timedelta(hours=1),
            completed_at=datetime.now() - timedelta(minutes=30),
        )
        await storage.save_task(task)

    task = Task(
        name="Failed Task",
        task_type=TaskType.AGENT,
        status=TaskStatus.FAILED,
        created_at=datetime.now() - timedelta(hours=1),
        started_at=datetime.now() - timedelta(hours=1),
        completed_at=datetime.now() - timedelta(minutes=30),
    )
    await storage.save_task(task)

    metrics = await monitor.collect_metrics()

    assert metrics.success_rate == 0.75  # 3/4
    assert metrics.failure_rate == 0.25  # 1/4


@pytest.mark.anyio
async def test_monitor_check_health_healthy(monitor):
    """Test health check with healthy system."""
    health = await monitor.check_health(active_task_count=2)

    assert isinstance(health, HealthStatus)
    assert health.is_healthy is True
    assert len(health.issues) == 0


@pytest.mark.anyio
async def test_monitor_check_health_at_capacity(monitor):
    """Test health check when at max capacity."""
    health = await monitor.check_health(active_task_count=5)

    assert health.is_healthy is True
    assert len(health.warnings) > 0
    assert any("maximum concurrent task capacity" in w for w in health.warnings)


@pytest.mark.anyio
async def test_monitor_check_health_stuck_tasks(storage, monitor):
    """Test health check detects stuck tasks."""
    # Create task running for more than 24 hours
    task = Task(
        name="Stuck Task",
        task_type=TaskType.AGENT,
        status=TaskStatus.RUNNING,
        created_at=datetime.now() - timedelta(hours=30),
        started_at=datetime.now() - timedelta(hours=30),
    )
    await storage.save_task(task)

    health = await monitor.check_health()

    assert len(health.warnings) > 0
    assert any("running for more than 24 hours" in w for w in health.warnings)


@pytest.mark.anyio
async def test_monitor_check_health_high_failure_rate(storage, monitor):
    """Test health check detects high failure rate."""
    # Create many failed tasks
    for i in range(15):
        task = Task(
            name=f"Failed Task {i}",
            task_type=TaskType.AGENT,
            status=TaskStatus.FAILED,
            created_at=datetime.now() - timedelta(hours=1),
            started_at=datetime.now() - timedelta(hours=1),
            completed_at=datetime.now() - timedelta(minutes=30),
        )
        await storage.save_task(task)

    # Create a few completed tasks
    for i in range(5):
        task = Task(
            name=f"Completed Task {i}",
            task_type=TaskType.AGENT,
            status=TaskStatus.COMPLETED,
            created_at=datetime.now() - timedelta(hours=1),
            started_at=datetime.now() - timedelta(hours=1),
            completed_at=datetime.now() - timedelta(minutes=30),
        )
        await storage.save_task(task)

    health = await monitor.check_health()

    assert len(health.warnings) > 0
    assert any("High failure rate" in w for w in health.warnings)


@pytest.mark.anyio
async def test_monitor_get_task_statistics(storage, monitor):
    """Test getting detailed task statistics."""
    # Create some tasks
    task1 = Task(
        name="Task 1",
        task_type=TaskType.AGENT,
        status=TaskStatus.COMPLETED,
        created_at=datetime.now() - timedelta(hours=1),
        started_at=datetime.now() - timedelta(hours=1),
        completed_at=datetime.now() - timedelta(minutes=30),
    )
    await storage.save_task(task1)

    task2 = Task(
        name="Task 2",
        task_type=TaskType.PROCESS,
        status=TaskStatus.RUNNING,
        created_at=datetime.now() - timedelta(minutes=10),
        started_at=datetime.now() - timedelta(minutes=10),
    )
    await storage.save_task(task2)

    stats = await monitor.get_task_statistics()

    assert "overview" in stats
    assert "by_status" in stats
    assert "by_type" in stats
    assert "performance" in stats
    assert "recent_activity" in stats
    assert "capacity" in stats

    assert stats["overview"]["total_tasks"] == 2
    assert stats["by_status"]["completed"] == 1
    assert stats["by_status"]["running"] == 1
    assert stats["by_type"]["agent"] == 1
    assert stats["by_type"]["process"] == 1


@pytest.mark.anyio
async def test_monitor_get_slow_tasks(storage, monitor):
    """Test getting slow-running tasks."""
    # Create a slow task (running for 2 hours)
    slow_task = Task(
        name="Slow Task",
        task_type=TaskType.AGENT,
        status=TaskStatus.RUNNING,
        created_at=datetime.now() - timedelta(hours=2),
        started_at=datetime.now() - timedelta(hours=2),
    )
    await storage.save_task(slow_task)

    # Create a fast task (running for 5 minutes)
    fast_task = Task(
        name="Fast Task",
        task_type=TaskType.AGENT,
        status=TaskStatus.RUNNING,
        created_at=datetime.now() - timedelta(minutes=5),
        started_at=datetime.now() - timedelta(minutes=5),
    )
    await storage.save_task(fast_task)

    # Get tasks running longer than 1 hour
    slow_tasks = await monitor.get_slow_tasks(threshold_seconds=3600)

    assert len(slow_tasks) == 1
    assert slow_tasks[0].task_id == slow_task.task_id


@pytest.mark.anyio
async def test_monitor_get_failed_tasks(storage, monitor):
    """Test getting failed tasks."""
    # Create failed tasks
    for i in range(3):
        task = Task(
            name=f"Failed Task {i}",
            task_type=TaskType.AGENT,
            status=TaskStatus.FAILED,
            created_at=datetime.now() - timedelta(hours=i),
        )
        await storage.save_task(task)

    # Create completed task
    task = Task(
        name="Completed Task",
        task_type=TaskType.AGENT,
        status=TaskStatus.COMPLETED,
        created_at=datetime.now(),
    )
    await storage.save_task(task)

    failed_tasks = await monitor.get_failed_tasks()

    assert len(failed_tasks) == 3
    assert all(t.status == TaskStatus.FAILED for t in failed_tasks)


@pytest.mark.anyio
async def test_monitor_metrics_history(monitor):
    """Test metrics history tracking."""
    # Collect metrics multiple times
    for i in range(5):
        await monitor.collect_metrics()

    history = monitor.get_metrics_history()

    assert len(history) == 5
    assert all(isinstance(m, TaskMetrics) for m in history)


@pytest.mark.anyio
async def test_monitor_metrics_history_limit(monitor):
    """Test metrics history with limit."""
    # Collect metrics multiple times
    for i in range(10):
        await monitor.collect_metrics()

    history = monitor.get_metrics_history(limit=3)

    assert len(history) == 3


# ============================================================================
# Auto-Cleanup Tests
# ============================================================================


@pytest.mark.anyio
async def test_storage_cleanup_old_tasks_by_age(storage):
    """Test cleanup of tasks older than retention period."""
    # Create old completed task (40 days old)
    old_task = Task(
        name="Old Task",
        task_type=TaskType.AGENT,
        status=TaskStatus.COMPLETED,
        created_at=datetime.now() - timedelta(days=40),
    )
    await storage.save_task(old_task)

    # Create recent completed task (10 days old)
    recent_task = Task(
        name="Recent Task",
        task_type=TaskType.AGENT,
        status=TaskStatus.COMPLETED,
        created_at=datetime.now() - timedelta(days=10),
    )
    await storage.save_task(recent_task)

    # Cleanup tasks older than 30 days
    deleted_count = await storage.cleanup_old_tasks(retention_days=30)

    assert deleted_count == 1

    # Verify old task is deleted
    loaded_old = await storage.load_task(old_task.task_id)
    assert loaded_old is None

    # Verify recent task still exists
    loaded_recent = await storage.load_task(recent_task.task_id)
    assert loaded_recent is not None


@pytest.mark.anyio
async def test_storage_cleanup_old_tasks_by_count(storage):
    """Test cleanup when exceeding max tasks."""
    # Create 15 completed tasks
    tasks = []
    for i in range(15):
        task = Task(
            name=f"Task {i}",
            task_type=TaskType.AGENT,
            status=TaskStatus.COMPLETED,
            created_at=datetime.now() - timedelta(days=i),
        )
        await storage.save_task(task)
        tasks.append(task)

    # Cleanup to keep max 10 tasks
    deleted_count = await storage.cleanup_old_tasks(
        retention_days=365, max_tasks=10  # Don't delete by age
    )

    assert deleted_count == 5

    # Verify total tasks is now 10
    all_tasks = await storage.list_tasks()
    assert len(all_tasks) == 10


@pytest.mark.anyio
async def test_storage_cleanup_preserves_running_tasks(storage):
    """Test that cleanup doesn't delete running tasks."""
    # Create old running task
    running_task = Task(
        name="Running Task",
        task_type=TaskType.AGENT,
        status=TaskStatus.RUNNING,
        created_at=datetime.now() - timedelta(days=40),
    )
    await storage.save_task(running_task)

    # Create old completed task
    completed_task = Task(
        name="Completed Task",
        task_type=TaskType.AGENT,
        status=TaskStatus.COMPLETED,
        created_at=datetime.now() - timedelta(days=40),
    )
    await storage.save_task(completed_task)

    # Cleanup tasks older than 30 days
    deleted_count = await storage.cleanup_old_tasks(retention_days=30)

    # Only completed task should be deleted
    assert deleted_count == 1

    # Verify running task still exists
    loaded_running = await storage.load_task(running_task.task_id)
    assert loaded_running is not None


# ============================================================================
# Task Recovery Tests
# ============================================================================


# @pytest.mark.anyio
# async def test_manager_marks_interrupted_tasks_on_init(storage):
#     """Test that manager marks running tasks as interrupted on initialization."""
#     # Create running task
#     running_task = Task(
#         name="Running Task",
#         task_type=TaskType.AGENT,
#         status=TaskStatus.RUNNING,
#         created_at=datetime.now() - timedelta(minutes=10),
#         started_at=datetime.now() - timedelta(minutes=10),
#     )
#     await storage.save_task(running_task)

#     # Create new manager (simulates daemon restart)
#     manager = TaskManager(storage, max_concurrent_tasks=5)
#     await manager.initialize()

#     # Verify task is marked as interrupted
#     loaded_task = await storage.load_task(running_task.task_id)
#     assert loaded_task.status == TaskStatus.INTERRUPTED
#     assert "Daemon restarted" in loaded_task.error

#     await manager.shutdown()


@pytest.mark.anyio
async def test_manager_recovery_preserves_completed_tasks(storage):
    """Test that recovery doesn't affect completed tasks."""
    # Create completed task
    completed_task = Task(
        name="Completed Task",
        task_type=TaskType.AGENT,
        status=TaskStatus.COMPLETED,
        created_at=datetime.now() - timedelta(minutes=10),
        started_at=datetime.now() - timedelta(minutes=10),
        completed_at=datetime.now() - timedelta(minutes=5),
    )
    await storage.save_task(completed_task)

    # Create new manager
    manager = TaskManager(storage, max_concurrent_tasks=5)
    await manager.initialize()

    # Verify task is still completed
    loaded_task = await storage.load_task(completed_task.task_id)
    assert loaded_task.status == TaskStatus.COMPLETED

    await manager.shutdown()


# ============================================================================
# Daemon Integration Tests
# ============================================================================


@pytest.mark.anyio
async def test_daemon_initializes_monitor(temp_storage_path, tmp_path):
    """Test that daemon initializes monitor on start."""
    pid_file = str(tmp_path / "daemon.pid")

    daemon = TaskDaemon(
        storage_path=temp_storage_path,
        pid_file=pid_file,
        auto_cleanup=False,  # Disable for test
    )

    # Mock the transport server
    with patch("exobrain.tasks.daemon.TransportFactory.create_server") as mock_factory:
        mock_server = AsyncMock()
        mock_factory.return_value = mock_server

        await daemon.start()

        # Verify monitor is initialized
        assert daemon._monitor is not None
        assert isinstance(daemon._monitor, TaskMonitor)

        await daemon.stop()


@pytest.mark.anyio
async def test_daemon_auto_cleanup_enabled(temp_storage_path, tmp_path):
    """Test that daemon starts cleanup task when auto_cleanup is enabled."""
    pid_file = str(tmp_path / "daemon.pid")

    daemon = TaskDaemon(
        storage_path=temp_storage_path,
        pid_file=pid_file,
        auto_cleanup=True,
        cleanup_interval_hours=1,
    )

    # Mock the transport server
    with patch("exobrain.tasks.daemon.TransportFactory.create_server") as mock_factory:
        mock_server = AsyncMock()
        mock_factory.return_value = mock_server

        await daemon.start()

        # Verify cleanup task is created
        assert daemon._cleanup_task is not None

        await daemon.stop()


# ============================================================================
# Client Integration Tests
# ============================================================================


@pytest.mark.anyio
async def test_client_get_metrics():
    """Test client get_metrics method."""
    client = TaskClient(auto_start=False)

    # Mock the send_request method
    with patch.object(client, "_send_request", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {
            "status": "ok",
            "data": {
                "metrics": {
                    "total_tasks": 10,
                    "running_tasks": 2,
                    "completed_tasks": 8,
                }
            },
        }

        metrics = await client.get_metrics()

        assert metrics["total_tasks"] == 10
        assert metrics["running_tasks"] == 2
        mock_send.assert_called_once_with("get_metrics", {})


@pytest.mark.anyio
async def test_client_get_health():
    """Test client get_health method."""
    client = TaskClient(auto_start=False)

    # Mock the send_request method
    with patch.object(client, "_send_request", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {
            "status": "ok",
            "data": {
                "health": {
                    "is_healthy": True,
                    "issues": [],
                    "warnings": [],
                }
            },
        }

        health = await client.get_health()

        assert health["is_healthy"] is True
        assert len(health["issues"]) == 0
        mock_send.assert_called_once_with("get_health", {})


@pytest.mark.anyio
async def test_client_get_statistics():
    """Test client get_statistics method."""
    client = TaskClient(auto_start=False)

    # Mock the send_request method
    with patch.object(client, "_send_request", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {
            "status": "ok",
            "data": {
                "statistics": {
                    "overview": {"total_tasks": 10},
                    "by_status": {"completed": 8},
                }
            },
        }

        stats = await client.get_statistics()

        assert "overview" in stats
        assert stats["overview"]["total_tasks"] == 10
        mock_send.assert_called_once_with("get_statistics", {})


@pytest.mark.anyio
async def test_client_cleanup_tasks():
    """Test client cleanup_tasks method."""
    client = TaskClient(auto_start=False)

    # Mock the send_request method
    with patch.object(client, "_send_request", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {
            "status": "ok",
            "data": {
                "deleted_count": 5,
                "retention_days": 30,
                "max_tasks": 1000,
            },
        }

        deleted_count = await client.cleanup_tasks(retention_days=30)

        assert deleted_count == 5
        mock_send.assert_called_once_with("cleanup_tasks", {"retention_days": 30})
