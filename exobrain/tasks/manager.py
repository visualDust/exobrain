"""Task manager for lifecycle management."""

import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional

from .executor import AgentExecutor, ProcessExecutor, TaskExecutor
from .models import Task, TaskStatus, TaskType
from .storage import TaskStorage

logger = logging.getLogger(__name__)


class TaskManager:
    """
    Task manager for lifecycle management.

    Manages task execution, monitoring, and coordination.
    Singleton pattern to ensure only one manager per daemon.
    """

    _instance: Optional["TaskManager"] = None

    def __new__(cls, *args, **kwargs):
        """Ensure singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        storage: TaskStorage,
        max_concurrent_tasks: int = 10,
    ):
        """
        Initialize task manager.

        Args:
            storage: Task storage instance
            max_concurrent_tasks: Maximum number of concurrent tasks
        """
        # Only initialize once
        if hasattr(self, "_initialized"):
            return

        self.storage = storage
        self.max_concurrent_tasks = max_concurrent_tasks

        # Active tasks and executors
        self._tasks: Dict[str, Task] = {}
        self._executors: Dict[str, TaskExecutor] = {}
        self._task_futures: Dict[str, asyncio.Task] = {}

        # Semaphore for concurrent task limit
        self._semaphore = asyncio.Semaphore(max_concurrent_tasks)

        self._initialized = True

    async def initialize(self) -> None:
        """Initialize the task manager."""
        logger.info("Initializing task manager")
        # Load active tasks from storage
        tasks = await self.storage.list_tasks(status=TaskStatus.RUNNING)
        logger.info(f"Found {len(tasks)} running tasks to mark as interrupted")

        # Mark interrupted tasks
        for task in tasks:
            task.status = TaskStatus.INTERRUPTED
            task.error = "Daemon restarted while task was running"
            await self.storage.save_task(task)

        logger.info("Task manager initialized")

    async def create_task(
        self,
        name: str,
        description: str = "",
        task_type: TaskType = TaskType.AGENT,
        config: Optional[Dict] = None,
    ) -> Task:
        """
        Create and start a new task.

        Args:
            name: Task name
            description: Task description
            task_type: Type of task (AGENT or PROCESS)
            config: Task configuration

        Returns:
            Created task
        """
        logger.info(f"Creating task: name={name}, type={task_type.value}")

        # Create task
        task = Task(
            name=name,
            description=description,
            task_type=task_type,
            config=config or {},
        )

        # For process tasks, extract command from config
        if task_type == TaskType.PROCESS and config:
            task.command = config.get("command")
            task.working_directory = config.get("working_directory")

        # Save task
        await self.storage.save_task(task)
        logger.info(f"Task saved: task_id={task.task_id}, status={task.status.value}")

        # Store in memory
        self._tasks[task.task_id] = task

        # Start task execution
        logger.info(f"Starting task execution: task_id={task.task_id}")
        await self._start_task(task)

        return task

    async def get_task(self, task_id: str) -> Optional[Task]:
        """
        Get task by ID.

        Args:
            task_id: Task ID

        Returns:
            Task if found, None otherwise
        """
        # Try memory first
        task = self._tasks.get(task_id)

        # Fall back to storage
        if not task:
            task = await self.storage.load_task(task_id)

        return task

    async def list_tasks(
        self,
        status: Optional[TaskStatus] = None,
        task_type: Optional[TaskType] = None,
        limit: Optional[int] = None,
    ) -> List[Task]:
        """
        List tasks with optional filters.

        Args:
            status: Filter by status
            task_type: Filter by type
            limit: Maximum number of tasks to return

        Returns:
            List of tasks
        """
        return await self.storage.list_tasks(status, task_type, limit)

    async def cancel_task(self, task_id: str) -> bool:
        """
        Cancel a running task.

        Args:
            task_id: Task ID

        Returns:
            True if task was cancelled, False otherwise
        """
        task = self._tasks.get(task_id)
        if not task:
            task = await self.storage.load_task(task_id)

        if not task:
            return False

        # Check if task is active
        if not task.is_active:
            return False

        # Cancel executor
        executor = self._executors.get(task_id)
        if executor:
            await executor.cancel()

        # Cancel future
        future = self._task_futures.get(task_id)
        if future and not future.done():
            future.cancel()

        # Update task status
        task.status = TaskStatus.CANCELLED
        task.completed_at = datetime.now()
        await self.storage.save_task(task)

        return True

    async def delete_task(self, task_id: str) -> bool:
        """
        Delete a task.

        Args:
            task_id: Task ID

        Returns:
            True if task was deleted, False otherwise
        """
        # Cancel if running
        task = self._tasks.get(task_id)
        if task and task.is_active:
            await self.cancel_task(task_id)

        # Remove from memory
        if task_id in self._tasks:
            del self._tasks[task_id]
        if task_id in self._executors:
            del self._executors[task_id]
        if task_id in self._task_futures:
            del self._task_futures[task_id]

        # Delete from storage
        return await self.storage.delete_task(task_id)

    async def _start_task(self, task: Task) -> None:
        """
        Start task execution.

        Args:
            task: Task to start
        """
        logger.info(f"_start_task called for task_id={task.task_id}")

        # Create executor
        if task.task_type == TaskType.AGENT:
            executor = AgentExecutor(task, self.storage)
            logger.info(f"Created AgentExecutor for task_id={task.task_id}")
        elif task.task_type == TaskType.PROCESS:
            executor = ProcessExecutor(task, self.storage)
            logger.info(f"Created ProcessExecutor for task_id={task.task_id}")
        else:
            raise ValueError(f"Unknown task type: {task.task_type}")

        self._executors[task.task_id] = executor

        # Create task future
        logger.info(f"Creating asyncio task for task_id={task.task_id}")
        future = asyncio.create_task(self._run_task(task, executor))
        self._task_futures[task.task_id] = future
        logger.info(f"Task future created and stored for task_id={task.task_id}")

    async def _run_task(self, task: Task, executor: TaskExecutor) -> None:
        """
        Run task with executor.

        Args:
            task: Task to run
            executor: Task executor
        """
        logger.info(f"_run_task started for task_id={task.task_id}")
        logger.info(
            f"Waiting for semaphore (current active: {self.active_task_count}/{self.max_concurrent_tasks})"
        )

        async with self._semaphore:
            logger.info(f"Acquired semaphore for task_id={task.task_id}")
            try:
                # Update task status
                task.status = TaskStatus.RUNNING
                task.started_at = datetime.now()
                await self.storage.save_task(task)
                logger.info(f"Task status updated to RUNNING: task_id={task.task_id}")

                # Execute task
                logger.info(f"Starting executor.execute() for task_id={task.task_id}")
                await executor.execute()
                logger.info(f"Executor.execute() completed for task_id={task.task_id}")

                # Update task status
                if task.status == TaskStatus.RUNNING:
                    task.status = TaskStatus.COMPLETED
                    task.completed_at = datetime.now()
                    await self.storage.save_task(task)
                    logger.info(f"Task completed successfully: task_id={task.task_id}")

            except asyncio.CancelledError:
                # Task was cancelled
                logger.info(f"Task cancelled: task_id={task.task_id}")
                task.status = TaskStatus.CANCELLED
                task.completed_at = datetime.now()
                await self.storage.save_task(task)

            except Exception as e:
                # Task failed
                logger.error(f"Task failed: task_id={task.task_id}, error={str(e)}", exc_info=True)
                task.status = TaskStatus.FAILED
                task.error = str(e)
                task.completed_at = datetime.now()
                await self.storage.save_task(task)

            finally:
                # Clean up
                logger.info(f"Cleaning up task: task_id={task.task_id}")
                if task.task_id in self._executors:
                    del self._executors[task.task_id]
                if task.task_id in self._task_futures:
                    del self._task_futures[task.task_id]

    async def shutdown(self) -> None:
        """Shutdown the task manager."""
        # Cancel all running tasks
        for task_id in list(self._tasks.keys()):
            task = self._tasks[task_id]
            if task.is_active:
                await self.cancel_task(task_id)

        # Wait for all futures to complete
        if self._task_futures:
            await asyncio.gather(*self._task_futures.values(), return_exceptions=True)

    @property
    def active_task_count(self) -> int:
        """Get number of active tasks."""
        return sum(1 for task in self._tasks.values() if task.is_active)

    @property
    def total_task_count(self) -> int:
        """Get total number of tasks in memory."""
        return len(self._tasks)
