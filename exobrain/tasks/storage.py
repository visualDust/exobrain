"""Task storage with file-based persistence."""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from .models import Task, TaskStatus


class TaskStorage:
    """File-based task storage."""

    def __init__(self, storage_path: str = "~/.exobrain/data/tasks"):
        """
        Initialize task storage.

        Args:
            storage_path: Base path for task storage
        """
        self.storage_path = Path(storage_path).expanduser()
        self.index_file = self.storage_path / "tasks_index.json"
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        """Initialize storage directory and index."""
        # Create storage directory
        self.storage_path.mkdir(parents=True, exist_ok=True)

        # Create index file if it doesn't exist
        if not self.index_file.exists():
            await self._write_index({})

    def _get_task_dir(self, task_id: str) -> Path:
        """
        Get directory path for a task.

        Args:
            task_id: Task ID

        Returns:
            Path to task directory
        """
        return self.storage_path / task_id

    def _get_metadata_file(self, task_id: str) -> Path:
        """
        Get metadata file path for a task.

        Args:
            task_id: Task ID

        Returns:
            Path to metadata file
        """
        return self._get_task_dir(task_id) / "metadata.json"

    def _get_output_file(self, task_id: str) -> Path:
        """
        Get output file path for a task.

        Args:
            task_id: Task ID

        Returns:
            Path to output file
        """
        return self._get_task_dir(task_id) / "output.log"

    def _get_events_file(self, task_id: str) -> Path:
        """
        Get events file path for a task.

        Args:
            task_id: Task ID

        Returns:
            Path to events file
        """
        return self._get_task_dir(task_id) / "events.jsonl"

    async def _read_index(self) -> Dict[str, Dict]:
        """
        Read task index.

        Returns:
            Task index dictionary
        """
        async with self._lock:
            if not self.index_file.exists():
                return {}

            with open(self.index_file, "r") as f:
                return json.load(f)

    async def _write_index(self, index: Dict[str, Dict]) -> None:
        """
        Write task index.

        Args:
            index: Task index dictionary
        """
        async with self._lock:
            with open(self.index_file, "w") as f:
                json.dump(index, f, indent=2)

    async def save_task(self, task: Task) -> None:
        """
        Save task to storage.

        Args:
            task: Task to save
        """
        # Create task directory
        task_dir = self._get_task_dir(task.task_id)
        task_dir.mkdir(parents=True, exist_ok=True)

        # Save metadata
        metadata_file = self._get_metadata_file(task.task_id)
        with open(metadata_file, "w") as f:
            json.dump(task.to_dict(), f, indent=2)

        # Update index
        index = await self._read_index()
        index[task.task_id] = {
            "task_id": task.task_id,
            "name": task.name,
            "task_type": task.task_type.value,
            "status": task.status.value,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "updated_at": datetime.now().isoformat(),
        }
        await self._write_index(index)

        # Set output paths
        task.output_path = str(self._get_output_file(task.task_id))
        task.events_path = str(self._get_events_file(task.task_id))

    async def load_task(self, task_id: str) -> Optional[Task]:
        """
        Load task from storage.

        Args:
            task_id: Task ID

        Returns:
            Task instance, or None if not found
        """
        metadata_file = self._get_metadata_file(task_id)
        if not metadata_file.exists():
            return None

        with open(metadata_file, "r") as f:
            data = json.load(f)

        return Task.from_dict(data)

    async def delete_task(self, task_id: str) -> bool:
        """
        Delete task from storage.

        Args:
            task_id: Task ID

        Returns:
            True if task was deleted, False if not found
        """
        # Remove from index
        index = await self._read_index()
        if task_id not in index:
            return False

        del index[task_id]
        await self._write_index(index)

        # Remove task directory
        task_dir = self._get_task_dir(task_id)
        if task_dir.exists():
            import shutil

            shutil.rmtree(task_dir)

        return True

    async def list_tasks(
        self,
        status: Optional[TaskStatus] = None,
        task_type: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Task]:
        """
        List tasks from storage.

        Args:
            status: Filter by status
            task_type: Filter by task type
            limit: Maximum number of tasks to return

        Returns:
            List of tasks
        """
        index = await self._read_index()

        # Filter tasks
        task_ids = []
        for task_id, info in index.items():
            if status and info.get("status") != status.value:
                continue
            if task_type and info.get("task_type") != task_type:
                continue
            task_ids.append(task_id)

        # Sort by creation time (newest first)
        task_ids.sort(key=lambda tid: index[tid].get("created_at", ""), reverse=True)

        # Apply limit
        if limit:
            task_ids = task_ids[:limit]

        # Load tasks
        tasks = []
        for task_id in task_ids:
            task = await self.load_task(task_id)
            if task:
                tasks.append(task)

        return tasks

    async def append_output(self, task_id: str, output: str) -> None:
        """
        Append output to task output file.

        Args:
            task_id: Task ID
            output: Output text to append
        """
        output_file = self._get_output_file(task_id)
        output_file.parent.mkdir(parents=True, exist_ok=True)

        with open(output_file, "a") as f:
            f.write(output)

    async def read_output(self, task_id: str, offset: int = 0, limit: Optional[int] = None) -> str:
        """
        Read output from task output file.

        Args:
            task_id: Task ID
            offset: Byte offset to start reading from
            limit: Maximum number of bytes to read

        Returns:
            Output text
        """
        output_file = self._get_output_file(task_id)
        if not output_file.exists():
            return ""

        with open(output_file, "r", encoding="utf-8", errors="replace") as f:
            f.seek(offset)
            if limit:
                return f.read(limit)
            return f.read()

    async def append_event(self, task_id: str, event: Dict) -> None:
        """
        Append event to task events file.

        Args:
            task_id: Task ID
            event: Event dictionary
        """
        events_file = self._get_events_file(task_id)
        events_file.parent.mkdir(parents=True, exist_ok=True)

        # Add timestamp
        event["timestamp"] = datetime.now().isoformat()

        with open(events_file, "a") as f:
            f.write(json.dumps(event) + "\n")

    async def read_events(self, task_id: str, limit: Optional[int] = None) -> List[Dict]:
        """
        Read events from task events file.

        Args:
            task_id: Task ID
            limit: Maximum number of events to return (most recent)

        Returns:
            List of event dictionaries
        """
        events_file = self._get_events_file(task_id)
        if not events_file.exists():
            return []

        events = []
        with open(events_file, "r") as f:
            for line in f:
                if line.strip():
                    events.append(json.loads(line))

        # Return most recent events if limit specified
        if limit:
            events = events[-limit:]

        return events

    async def cleanup_old_tasks(self, retention_days: int = 30, max_tasks: int = 1000) -> int:
        """
        Clean up old completed tasks.

        Args:
            retention_days: Delete tasks older than this many days
            max_tasks: Keep at most this many tasks

        Returns:
            Number of tasks deleted
        """
        index = await self._read_index()

        # Get all completed tasks
        completed_tasks = []
        for task_id, info in index.items():
            if info.get("status") in (
                TaskStatus.COMPLETED.value,
                TaskStatus.FAILED.value,
                TaskStatus.CANCELLED.value,
            ):
                completed_tasks.append((task_id, info))

        # Sort by creation time (oldest first)
        completed_tasks.sort(key=lambda x: x[1].get("created_at", ""))

        # Determine tasks to delete
        tasks_to_delete = []

        # Delete tasks older than retention period
        cutoff_date = datetime.now().timestamp() - (retention_days * 86400)
        for task_id, info in completed_tasks:
            created_at = info.get("created_at")
            if created_at:
                created_timestamp = datetime.fromisoformat(created_at).timestamp()
                if created_timestamp < cutoff_date:
                    tasks_to_delete.append(task_id)

        # Delete excess tasks if over max_tasks
        total_tasks = len(index)
        if total_tasks > max_tasks:
            excess = total_tasks - max_tasks
            for task_id, _ in completed_tasks[:excess]:
                if task_id not in tasks_to_delete:
                    tasks_to_delete.append(task_id)

        # Delete tasks
        deleted_count = 0
        for task_id in tasks_to_delete:
            if await self.delete_task(task_id):
                deleted_count += 1

        return deleted_count
