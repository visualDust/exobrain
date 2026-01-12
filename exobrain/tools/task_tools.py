"""Task management tools for agents."""

from typing import TYPE_CHECKING, Any, ClassVar

from exobrain.tasks import TaskClient, TaskStatus, TaskType
from exobrain.tools.base import ConfigurableTool, ToolParameter, register_tool

if TYPE_CHECKING:
    from exobrain.config import Config


@register_tool
class CreateTaskTool(ConfigurableTool):
    """Tool to create a new background task."""

    config_key: ClassVar[str] = "tasks"

    def __init__(self, enabled: bool = True) -> None:
        super().__init__(
            name="create_task",
            description="Create a new background task that runs independently. Use this to offload long-running operations like research, data processing, or complex analysis.",
            parameters={
                "name": ToolParameter(
                    type="string",
                    description="Short name for the task",
                    required=True,
                ),
                "description": ToolParameter(
                    type="string",
                    description="Detailed description of what the task should do",
                    required=False,
                ),
                "task_type": ToolParameter(
                    type="string",
                    description="Type of task: 'agent' for AI agent tasks, 'process' for shell commands",
                    required=True,
                    enum=["agent", "process"],
                ),
                "config": ToolParameter(
                    type="object",
                    description="Task-specific configuration (e.g., 'prompt' for agent tasks, 'command' for process tasks)",
                    required=False,
                ),
            },
            requires_permission=False,
        )
        self._enabled = enabled

    async def execute(self, **kwargs: Any) -> str:
        """Execute the tool."""
        if not self._enabled:
            return "Error: Task management is not enabled"

        name = kwargs.get("name", "")
        if not name:
            return "Error: name parameter is required"

        description = kwargs.get("description", "")
        task_type_str = kwargs.get("task_type", "")
        if not task_type_str:
            return "Error: task_type parameter is required"

        try:
            task_type = TaskType(task_type_str)
        except ValueError:
            return f"Error: invalid task_type '{task_type_str}'. Must be 'agent' or 'process'"

        config = kwargs.get("config", {})

        try:
            async with TaskClient() as client:
                task = await client.create_task(
                    name=name,
                    description=description,
                    task_type=task_type,
                    config=config,
                )

                result = f"Task created successfully:\n"
                result += f"- ID: {task.task_id}\n"
                result += f"- Name: {task.name}\n"
                result += f"- Type: {task.task_type.value}\n"
                result += f"- Status: {task.status.value}\n"
                result += f"\nUse get_task_status tool to check progress."

                return result

        except Exception as e:
            return f"Error creating task: {e}"

    @classmethod
    def from_config(cls, config: "Config") -> "CreateTaskTool | None":
        """Create tool instance from configuration.

        Args:
            config: Global application configuration

        Returns:
            CreateTaskTool instance if tasks are enabled, None otherwise
        """
        if not getattr(config, "tasks", None) or not config.tasks.enabled:
            return None

        return cls(enabled=True)


@register_tool
class GetTaskStatusTool(ConfigurableTool):
    """Tool to get the status of a background task."""

    config_key: ClassVar[str] = "tasks"

    def __init__(self, enabled: bool = True) -> None:
        super().__init__(
            name="get_task_status",
            description="Get the current status and details of a background task",
            parameters={
                "task_id": ToolParameter(
                    type="string",
                    description="ID of the task to check",
                    required=True,
                ),
            },
            requires_permission=False,
        )
        self._enabled = enabled

    async def execute(self, **kwargs: Any) -> str:
        """Execute the tool."""
        if not self._enabled:
            return "Error: Task management is not enabled"

        task_id = kwargs.get("task_id", "")
        if not task_id:
            return "Error: task_id parameter is required"

        try:
            async with TaskClient() as client:
                task = await client.get_task(task_id)

                result = f"Task Status:\n"
                result += f"- ID: {task.task_id}\n"
                result += f"- Name: {task.name}\n"
                result += f"- Type: {task.task_type.value}\n"
                result += f"- Status: {task.status.value}\n"
                result += f"- Created: {task.created_at}\n"

                if task.started_at:
                    result += f"- Started: {task.started_at}\n"
                if task.completed_at:
                    result += f"- Completed: {task.completed_at}\n"
                if task.duration:
                    result += f"- Duration: {task.duration:.1f}s\n"

                # Task-specific fields
                if task.task_type == TaskType.AGENT:
                    if task.iterations is not None:
                        result += (
                            f"- Progress: {task.iterations}/{task.max_iterations} iterations\n"
                        )
                elif task.task_type == TaskType.PROCESS:
                    if task.exit_code is not None:
                        result += f"- Exit Code: {task.exit_code}\n"

                if task.error:
                    result += f"- Error: {task.error}\n"

                return result

        except Exception as e:
            return f"Error getting task status: {e}"

    @classmethod
    def from_config(cls, config: "Config") -> "GetTaskStatusTool | None":
        """Create tool instance from configuration.

        Args:
            config: Global application configuration

        Returns:
            GetTaskStatusTool instance if tasks are enabled, None otherwise
        """
        if not getattr(config, "tasks", None) or not config.tasks.enabled:
            return None

        return cls(enabled=True)


@register_tool
class ListTasksTool(ConfigurableTool):
    """Tool to list background tasks."""

    config_key: ClassVar[str] = "tasks"

    def __init__(self, enabled: bool = True) -> None:
        super().__init__(
            name="list_tasks",
            description="List all background tasks with optional filtering",
            parameters={
                "status": ToolParameter(
                    type="string",
                    description="Filter by status (pending, running, completed, failed, cancelled, interrupted)",
                    required=False,
                    enum=[
                        "pending",
                        "running",
                        "completed",
                        "failed",
                        "cancelled",
                        "interrupted",
                    ],
                ),
                "task_type": ToolParameter(
                    type="string",
                    description="Filter by type (agent, process)",
                    required=False,
                    enum=["agent", "process"],
                ),
                "limit": ToolParameter(
                    type="integer",
                    description="Maximum number of tasks to return",
                    required=False,
                ),
            },
            requires_permission=False,
        )
        self._enabled = enabled

    async def execute(self, **kwargs: Any) -> str:
        """Execute the tool."""
        if not self._enabled:
            return "Error: Task management is not enabled"

        status_str = kwargs.get("status")
        task_type_str = kwargs.get("task_type")
        limit = kwargs.get("limit")

        status = None
        if status_str:
            try:
                status = TaskStatus(status_str)
            except ValueError:
                return f"Error: invalid status '{status_str}'"

        task_type = None
        if task_type_str:
            try:
                task_type = TaskType(task_type_str)
            except ValueError:
                return f"Error: invalid task_type '{task_type_str}'"

        try:
            async with TaskClient() as client:
                tasks = await client.list_tasks(status=status, task_type=task_type, limit=limit)

                if not tasks:
                    return "No tasks found"

                result = f"Found {len(tasks)} task(s):\n\n"

                for task in tasks:
                    result += f"- {task.task_id[:8]}... | {task.name} | {task.task_type.value} | {task.status.value}"

                    if task.duration:
                        result += f" | {task.duration:.1f}s"

                    result += "\n"

                return result

        except Exception as e:
            return f"Error listing tasks: {e}"

    @classmethod
    def from_config(cls, config: "Config") -> "ListTasksTool | None":
        """Create tool instance from configuration.

        Args:
            config: Global application configuration

        Returns:
            ListTasksTool instance if tasks are enabled, None otherwise
        """
        if not getattr(config, "tasks", None) or not config.tasks.enabled:
            return None

        return cls(enabled=True)


@register_tool
class GetTaskOutputTool(ConfigurableTool):
    """Tool to get the output of a background task."""

    config_key: ClassVar[str] = "tasks"

    def __init__(self, enabled: bool = True) -> None:
        super().__init__(
            name="get_task_output",
            description="Get the output/logs of a background task",
            parameters={
                "task_id": ToolParameter(
                    type="string",
                    description="ID of the task",
                    required=True,
                ),
                "offset": ToolParameter(
                    type="integer",
                    description="Byte offset to start reading from",
                    required=False,
                ),
                "limit": ToolParameter(
                    type="integer",
                    description="Maximum number of bytes to read",
                    required=False,
                ),
            },
            requires_permission=False,
        )
        self._enabled = enabled

    async def execute(self, **kwargs: Any) -> str:
        """Execute the tool."""
        if not self._enabled:
            return "Error: Task management is not enabled"

        task_id = kwargs.get("task_id", "")
        if not task_id:
            return "Error: task_id parameter is required"

        offset = kwargs.get("offset", 0)
        limit = kwargs.get("limit")

        try:
            async with TaskClient() as client:
                output = await client.get_output(task_id=task_id, offset=offset, limit=limit)

                if not output:
                    return "No output available yet"

                return output

        except Exception as e:
            return f"Error getting task output: {e}"

    @classmethod
    def from_config(cls, config: "Config") -> "GetTaskOutputTool | None":
        """Create tool instance from configuration.

        Args:
            config: Global application configuration

        Returns:
            GetTaskOutputTool instance if tasks are enabled, None otherwise
        """
        if not getattr(config, "tasks", None) or not config.tasks.enabled:
            return None

        return cls(enabled=True)


@register_tool
class CancelTaskTool(ConfigurableTool):
    """Tool to cancel a running background task."""

    config_key: ClassVar[str] = "tasks"

    def __init__(self, enabled: bool = True) -> None:
        super().__init__(
            name="cancel_task",
            description="Cancel a running background task",
            parameters={
                "task_id": ToolParameter(
                    type="string",
                    description="ID of the task to cancel",
                    required=True,
                ),
            },
            requires_permission=False,
        )
        self._enabled = enabled

    async def execute(self, **kwargs: Any) -> str:
        """Execute the tool."""
        if not self._enabled:
            return "Error: Task management is not enabled"

        task_id = kwargs.get("task_id", "")
        if not task_id:
            return "Error: task_id parameter is required"

        try:
            async with TaskClient() as client:
                task = await client.cancel_task(task_id)

                result = f"Task cancelled successfully:\n"
                result += f"- ID: {task.task_id}\n"
                result += f"- Name: {task.name}\n"
                result += f"- Status: {task.status.value}\n"

                return result

        except Exception as e:
            return f"Error cancelling task: {e}"

    @classmethod
    def from_config(cls, config: "Config") -> "CancelTaskTool | None":
        """Create tool instance from configuration.

        Args:
            config: Global application configuration

        Returns:
            CancelTaskTool instance if tasks are enabled, None otherwise
        """
        if not getattr(config, "tasks", None) or not config.tasks.enabled:
            return None

        return cls(enabled=True)
