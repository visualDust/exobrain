"""Task monitoring and metrics collection."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from .models import Task, TaskStatus, TaskType
from .storage import TaskStorage

logger = logging.getLogger(__name__)


@dataclass
class TaskMetrics:
    """Metrics for task execution."""

    # Task counts by status
    total_tasks: int = 0
    pending_tasks: int = 0
    running_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    cancelled_tasks: int = 0
    interrupted_tasks: int = 0

    # Task counts by type
    agent_tasks: int = 0
    process_tasks: int = 0

    # Timing metrics
    avg_duration_seconds: float = 0.0
    min_duration_seconds: float = 0.0
    max_duration_seconds: float = 0.0

    # Success rate
    success_rate: float = 0.0
    failure_rate: float = 0.0

    # Recent activity
    tasks_created_last_hour: int = 0
    tasks_completed_last_hour: int = 0
    tasks_failed_last_hour: int = 0

    # Resource usage
    active_task_count: int = 0
    max_concurrent_tasks: int = 0
    task_queue_size: int = 0

    # Timestamp
    collected_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict:
        """Convert metrics to dictionary."""
        return {
            "total_tasks": self.total_tasks,
            "pending_tasks": self.pending_tasks,
            "running_tasks": self.running_tasks,
            "completed_tasks": self.completed_tasks,
            "failed_tasks": self.failed_tasks,
            "cancelled_tasks": self.cancelled_tasks,
            "interrupted_tasks": self.interrupted_tasks,
            "agent_tasks": self.agent_tasks,
            "process_tasks": self.process_tasks,
            "avg_duration_seconds": self.avg_duration_seconds,
            "min_duration_seconds": self.min_duration_seconds,
            "max_duration_seconds": self.max_duration_seconds,
            "success_rate": self.success_rate,
            "failure_rate": self.failure_rate,
            "tasks_created_last_hour": self.tasks_created_last_hour,
            "tasks_completed_last_hour": self.tasks_completed_last_hour,
            "tasks_failed_last_hour": self.tasks_failed_last_hour,
            "active_task_count": self.active_task_count,
            "max_concurrent_tasks": self.max_concurrent_tasks,
            "task_queue_size": self.task_queue_size,
            "collected_at": self.collected_at.isoformat(),
        }


@dataclass
class HealthStatus:
    """Health status of the task system."""

    is_healthy: bool = True
    issues: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    checked_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict:
        """Convert health status to dictionary."""
        return {
            "is_healthy": self.is_healthy,
            "issues": self.issues,
            "warnings": self.warnings,
            "checked_at": self.checked_at.isoformat(),
        }


class TaskMonitor:
    """
    Task monitoring and metrics collection.

    Collects metrics about task execution, monitors system health,
    and provides insights into task system performance.
    """

    def __init__(
        self,
        storage: TaskStorage,
        max_concurrent_tasks: int = 10,
    ):
        """
        Initialize task monitor.

        Args:
            storage: Task storage instance
            max_concurrent_tasks: Maximum concurrent tasks (for metrics)
        """
        self.storage = storage
        self.max_concurrent_tasks = max_concurrent_tasks
        self._metrics_history: List[TaskMetrics] = []
        self._max_history_size = 100

    async def collect_metrics(
        self,
        active_task_count: int = 0,
        task_queue_size: int = 0,
    ) -> TaskMetrics:
        """
        Collect current task metrics.

        Args:
            active_task_count: Number of currently active tasks
            task_queue_size: Number of tasks waiting in queue

        Returns:
            TaskMetrics instance
        """
        logger.debug("Collecting task metrics")

        # Load all tasks
        all_tasks = await self.storage.list_tasks()

        # Initialize metrics
        metrics = TaskMetrics(
            max_concurrent_tasks=self.max_concurrent_tasks,
            active_task_count=active_task_count,
            task_queue_size=task_queue_size,
        )

        # Count tasks by status
        status_counts = {status: 0 for status in TaskStatus}
        type_counts = {task_type: 0 for task_type in TaskType}
        durations = []

        # Time window for recent activity (1 hour)
        one_hour_ago = datetime.now() - timedelta(hours=1)

        for task in all_tasks:
            # Count by status
            status_counts[task.status] += 1

            # Count by type
            type_counts[task.task_type] += 1

            # Collect durations for completed tasks
            if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                duration = task.duration
                if duration:
                    durations.append(duration)

            # Count recent activity
            if task.created_at and task.created_at > one_hour_ago:
                metrics.tasks_created_last_hour += 1

            if task.completed_at and task.completed_at > one_hour_ago:
                if task.status == TaskStatus.COMPLETED:
                    metrics.tasks_completed_last_hour += 1
                elif task.status == TaskStatus.FAILED:
                    metrics.tasks_failed_last_hour += 1

        # Set status counts
        metrics.total_tasks = len(all_tasks)
        metrics.pending_tasks = status_counts[TaskStatus.PENDING]
        metrics.running_tasks = status_counts[TaskStatus.RUNNING]
        metrics.completed_tasks = status_counts[TaskStatus.COMPLETED]
        metrics.failed_tasks = status_counts[TaskStatus.FAILED]
        metrics.cancelled_tasks = status_counts[TaskStatus.CANCELLED]
        metrics.interrupted_tasks = status_counts[TaskStatus.INTERRUPTED]

        # Set type counts
        metrics.agent_tasks = type_counts[TaskType.AGENT]
        metrics.process_tasks = type_counts[TaskType.PROCESS]

        # Calculate duration metrics
        if durations:
            metrics.avg_duration_seconds = sum(durations) / len(durations)
            metrics.min_duration_seconds = min(durations)
            metrics.max_duration_seconds = max(durations)

        # Calculate success/failure rates
        terminal_tasks = metrics.completed_tasks + metrics.failed_tasks + metrics.cancelled_tasks
        if terminal_tasks > 0:
            metrics.success_rate = metrics.completed_tasks / terminal_tasks
            metrics.failure_rate = metrics.failed_tasks / terminal_tasks

        # Store in history
        self._metrics_history.append(metrics)
        if len(self._metrics_history) > self._max_history_size:
            self._metrics_history.pop(0)

        logger.debug(f"Collected metrics: {metrics.total_tasks} total tasks")
        return metrics

    async def check_health(
        self,
        active_task_count: int = 0,
    ) -> HealthStatus:
        """
        Check health of the task system.

        Args:
            active_task_count: Number of currently active tasks

        Returns:
            HealthStatus instance
        """
        logger.debug("Checking task system health")

        health = HealthStatus()

        # Check if we're at max capacity
        if active_task_count >= self.max_concurrent_tasks:
            health.warnings.append(
                f"At maximum concurrent task capacity ({active_task_count}/{self.max_concurrent_tasks})"
            )

        # Check for stuck tasks (running for more than 24 hours)
        running_tasks = await self.storage.list_tasks(status=TaskStatus.RUNNING)
        stuck_threshold = datetime.now() - timedelta(hours=24)

        for task in running_tasks:
            if task.started_at and task.started_at < stuck_threshold:
                health.warnings.append(
                    f"Task {task.task_id} has been running for more than 24 hours"
                )

        # Check for high failure rate
        metrics = await self.collect_metrics(active_task_count=active_task_count)
        if metrics.failure_rate > 0.5 and metrics.total_tasks > 10:
            health.warnings.append(
                f"High failure rate: {metrics.failure_rate:.1%} of tasks are failing"
            )

        # Check storage accessibility
        try:
            await self.storage.list_tasks(limit=1)
        except Exception as e:
            health.is_healthy = False
            health.issues.append(f"Storage error: {str(e)}")

        # Determine overall health
        if health.issues:
            health.is_healthy = False

        logger.debug(f"Health check complete: healthy={health.is_healthy}")
        return health

    def get_metrics_history(self, limit: Optional[int] = None) -> List[TaskMetrics]:
        """
        Get historical metrics.

        Args:
            limit: Maximum number of metrics to return (most recent)

        Returns:
            List of TaskMetrics instances
        """
        if limit:
            return self._metrics_history[-limit:]
        return self._metrics_history.copy()

    async def get_task_statistics(self) -> Dict:
        """
        Get detailed task statistics.

        Returns:
            Dictionary with detailed statistics
        """
        metrics = await self.collect_metrics()

        # Calculate additional statistics
        stats = {
            "overview": {
                "total_tasks": metrics.total_tasks,
                "active_tasks": metrics.running_tasks + metrics.pending_tasks,
                "completed_tasks": metrics.completed_tasks,
                "failed_tasks": metrics.failed_tasks,
            },
            "by_status": {
                "pending": metrics.pending_tasks,
                "running": metrics.running_tasks,
                "completed": metrics.completed_tasks,
                "failed": metrics.failed_tasks,
                "cancelled": metrics.cancelled_tasks,
                "interrupted": metrics.interrupted_tasks,
            },
            "by_type": {
                "agent": metrics.agent_tasks,
                "process": metrics.process_tasks,
            },
            "performance": {
                "avg_duration_seconds": metrics.avg_duration_seconds,
                "min_duration_seconds": metrics.min_duration_seconds,
                "max_duration_seconds": metrics.max_duration_seconds,
                "success_rate": metrics.success_rate,
                "failure_rate": metrics.failure_rate,
            },
            "recent_activity": {
                "tasks_created_last_hour": metrics.tasks_created_last_hour,
                "tasks_completed_last_hour": metrics.tasks_completed_last_hour,
                "tasks_failed_last_hour": metrics.tasks_failed_last_hour,
            },
            "capacity": {
                "active_task_count": metrics.active_task_count,
                "max_concurrent_tasks": metrics.max_concurrent_tasks,
                "utilization": (
                    metrics.active_task_count / metrics.max_concurrent_tasks
                    if metrics.max_concurrent_tasks > 0
                    else 0.0
                ),
            },
        }

        return stats

    async def get_slow_tasks(self, threshold_seconds: float = 3600) -> List[Task]:
        """
        Get tasks that are running longer than threshold.

        Args:
            threshold_seconds: Duration threshold in seconds

        Returns:
            List of slow-running tasks
        """
        running_tasks = await self.storage.list_tasks(status=TaskStatus.RUNNING)
        slow_tasks = []

        threshold_time = datetime.now() - timedelta(seconds=threshold_seconds)

        for task in running_tasks:
            if task.started_at and task.started_at < threshold_time:
                slow_tasks.append(task)

        return slow_tasks

    async def get_failed_tasks(self, limit: Optional[int] = None) -> List[Task]:
        """
        Get recently failed tasks.

        Args:
            limit: Maximum number of tasks to return

        Returns:
            List of failed tasks
        """
        return await self.storage.list_tasks(
            status=TaskStatus.FAILED,
            limit=limit,
        )
