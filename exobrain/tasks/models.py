"""Task models and data structures."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


class TaskStatus(str, Enum):
    """Task status enumeration."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"  # Daemon restarted while task was running


class TaskType(str, Enum):
    """Task type enumeration."""

    AGENT = "agent"
    PROCESS = "process"


@dataclass
class Task:
    """Task data model."""

    # Identity
    task_id: str = field(default_factory=lambda: f"task-{uuid.uuid4().hex[:8]}")
    name: str = ""
    description: str = ""

    # Type and configuration
    task_type: TaskType = TaskType.AGENT
    config: Dict[str, Any] = field(default_factory=dict)

    # Status
    status: TaskStatus = TaskStatus.PENDING
    progress: float = 0.0  # 0.0 to 1.0
    error: Optional[str] = None

    # Timing
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Agent-specific fields
    iterations: int = 0
    max_iterations: int = 500

    # Process-specific fields
    command: Optional[str] = None
    working_directory: Optional[str] = None
    exit_code: Optional[int] = None
    pid: Optional[int] = None

    # Output
    output_path: Optional[str] = None
    events_path: Optional[str] = None

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert task to dictionary.

        Returns:
            Dictionary representation of task
        """
        return {
            "task_id": self.task_id,
            "name": self.name,
            "description": self.description,
            "task_type": self.task_type.value,
            "config": self.config,
            "status": self.status.value,
            "progress": self.progress,
            "error": self.error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "iterations": self.iterations,
            "max_iterations": self.max_iterations,
            "command": self.command,
            "working_directory": self.working_directory,
            "exit_code": self.exit_code,
            "pid": self.pid,
            "output_path": self.output_path,
            "events_path": self.events_path,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Task":
        """
        Create task from dictionary.

        Args:
            data: Dictionary representation of task

        Returns:
            Task instance
        """
        # Parse enums
        task_type = TaskType(data.get("task_type", TaskType.AGENT.value))
        status = TaskStatus(data.get("status", TaskStatus.PENDING.value))

        # Parse datetimes
        created_at = None
        if data.get("created_at"):
            created_at = datetime.fromisoformat(data["created_at"])

        started_at = None
        if data.get("started_at"):
            started_at = datetime.fromisoformat(data["started_at"])

        completed_at = None
        if data.get("completed_at"):
            completed_at = datetime.fromisoformat(data["completed_at"])

        return cls(
            task_id=data.get("task_id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            task_type=task_type,
            config=data.get("config", {}),
            status=status,
            progress=data.get("progress", 0.0),
            error=data.get("error"),
            created_at=created_at,
            started_at=started_at,
            completed_at=completed_at,
            iterations=data.get("iterations", 0),
            max_iterations=data.get("max_iterations", 500),
            command=data.get("command"),
            working_directory=data.get("working_directory"),
            exit_code=data.get("exit_code"),
            pid=data.get("pid"),
            output_path=data.get("output_path"),
            events_path=data.get("events_path"),
            metadata=data.get("metadata", {}),
        )

    @property
    def duration(self) -> Optional[float]:
        """
        Get task duration in seconds.

        Returns:
            Duration in seconds, or None if not started
        """
        if not self.started_at:
            return None

        end_time = self.completed_at or datetime.now()
        return (end_time - self.started_at).total_seconds()

    @property
    def is_terminal(self) -> bool:
        """
        Check if task is in a terminal state.

        Returns:
            True if task is completed, failed, or cancelled
        """
        return self.status in (
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        )

    @property
    def is_active(self) -> bool:
        """
        Check if task is actively running.

        Returns:
            True if task is pending or running
        """
        return self.status in (TaskStatus.PENDING, TaskStatus.RUNNING)

    def __repr__(self) -> str:
        """String representation of task."""
        duration_str = ""
        if self.duration:
            duration_str = f" ({self.duration:.1f}s)"

        return (
            f"Task(id={self.task_id}, name={self.name!r}, "
            f"type={self.task_type.value}, status={self.status.value}{duration_str})"
        )
