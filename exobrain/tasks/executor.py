"""Task executors for different task types."""

import asyncio
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from .models import Task
from .storage import TaskStorage

logger = logging.getLogger(__name__)


class TaskExecutor(ABC):
    """
    Abstract base class for task executors.

    Executors handle the actual execution of tasks.
    """

    def __init__(self, task: Task, storage: TaskStorage):
        """
        Initialize task executor.

        Args:
            task: Task to execute
            storage: Task storage instance
        """
        self.task = task
        self.storage = storage
        self._cancelled = False

    @abstractmethod
    async def execute(self) -> None:
        """
        Execute the task.

        This method should be implemented by subclasses.
        """

    async def cancel(self) -> None:
        """
        Cancel the task execution.

        This method can be overridden by subclasses for custom cancellation logic.
        """
        self._cancelled = True

    async def _append_output(self, text: str) -> None:
        """
        Append text to task output.

        Args:
            text: Text to append
        """
        await self.storage.append_output(self.task.task_id, text)

    async def _update_progress(self, progress: float) -> None:
        """
        Update task progress.

        Args:
            progress: Progress value (0.0 to 1.0)
        """
        self.task.progress = progress
        await self.storage.save_task(self.task)


class AgentExecutor(TaskExecutor):
    """
    Executor for agent tasks.

    Runs an agent with the given configuration.
    """

    def _truncate_tool_output(self, text: str, max_lines: int = 50, max_chars: int = 1200) -> str:
        """
        Truncate tool output in task output text while preserving agent messages.

        Args:
            text: Text that may contain tool output
            max_lines: Maximum number of lines for tool output
            max_chars: Maximum number of characters for tool output

        Returns:
            Text with tool output truncated if needed

        todo)): this is a workaround solution, we should handle this better with unified event handling.
        """
        # Check if this chunk contains tool output (format: "[Tool: tool_name]\n{output}\n")
        if not text.startswith("\n\n[Tool: ") and "[Tool: " not in text:
            # Not a tool output chunk, return as-is
            return text

        # Extract tool name and output
        lines = text.split("\n")
        tool_header_idx = -1
        for i, line in enumerate(lines):
            if line.startswith("[Tool: "):
                tool_header_idx = i
                break

        if tool_header_idx == -1:
            return text

        # Split into: prefix + tool header + tool output + suffix
        prefix_lines = lines[:tool_header_idx]
        tool_header = lines[tool_header_idx]
        output_start_idx = tool_header_idx + 1

        # Find where tool output ends (empty line or end of text)
        output_end_idx = len(lines)
        for i in range(output_start_idx, len(lines)):
            if not lines[i].strip():
                output_end_idx = i
                break

        output_lines = lines[output_start_idx:output_end_idx]
        suffix_lines = lines[output_end_idx:]

        # Check if truncation is needed
        output_text = "\n".join(output_lines)
        needs_truncation = len(output_lines) > max_lines or len(output_text) > max_chars

        if not needs_truncation:
            return text

        # Truncate output
        if len(output_lines) > max_lines:
            truncated_output_lines = output_lines[:max_lines]
            remaining_lines = len(output_lines) - max_lines
            truncated_output_lines.append(
                f"[Content truncated: {remaining_lines} more lines. Total {len(output_lines)} lines.]"
            )
        else:
            truncated_output_lines = output_lines

        truncated_output = "\n".join(truncated_output_lines)
        if len(truncated_output) > max_chars:
            truncated_output = truncated_output[:max_chars]
            truncated_output += "\n[Content truncated at {max_chars} characters.]"

        # Reconstruct text
        result_lines = prefix_lines + [tool_header] + [truncated_output] + suffix_lines
        return "\n".join(result_lines)

    async def execute(self) -> None:
        """Execute agent task."""
        logger.info(f"AgentExecutor.execute() started for task_id={self.task.task_id}")

        # Import here to avoid circular dependency
        from exobrain.agent.events import EventType, IterationStartedEvent
        from exobrain.cli.util import create_agent_from_config
        from exobrain.config import load_config

        try:
            # Get configuration
            logger.info("Loading config")
            config, _ = load_config()
            logger.info(f"Config loaded successfully")

            # Check if task has a working directory with .exobrain folder
            # If so, add it to allowed directories for shell execution
            working_dir = self.task.config.get("working_directory")
            if working_dir:
                working_dir_path = Path(working_dir)
                exobrain_dir = working_dir_path / ".exobrain"
                if exobrain_dir.exists() and exobrain_dir.is_dir():
                    # Ensure shell_execution permissions exist in config
                    if hasattr(config.permissions, "shell_execution"):
                        shell_exec_config = config.permissions.shell_execution
                        if not hasattr(shell_exec_config, "allowed_directories"):
                            shell_exec_config.allowed_directories = []

                        # Add working directory if not already in allowed list
                        working_dir_str = str(working_dir_path)
                        if working_dir_str not in shell_exec_config.allowed_directories:
                            shell_exec_config.allowed_directories.append(working_dir_str)
                            logger.info(
                                f"Detected .exobrain in task working directory, automatically allowing: {working_dir_str}"
                            )

            # Get agent configuration from task config
            agent_config = self.task.config.copy()

            # Set max iterations
            max_iterations = agent_config.pop("max_iterations", self.task.max_iterations)
            self.task.max_iterations = max_iterations
            logger.info(f"Max iterations set to: {max_iterations}")

            # Get prompt
            prompt = agent_config.pop("prompt", self.task.description or self.task.name)
            logger.info(f"Prompt: {prompt}")

            # Get model spec if provided
            model_spec = agent_config.pop("model", None)

            # Create agent
            logger.info("Creating Agent instance")
            agent, _ = create_agent_from_config(config, model_spec=model_spec)
            logger.info("Agent instance created")

            # Register event handler to track iterations
            async def on_iteration_started(event):
                if isinstance(event, IterationStartedEvent):
                    self.task.iterations = event.iteration
                    progress = min(event.iteration / event.max_iterations, 1.0)
                    await self._update_progress(progress)
                    logger.info(f"Iteration {event.iteration}/{event.max_iterations} started")

            agent.events.register(on_iteration_started, EventType.ITERATION_STARTED)

            # Run agent
            logger.info("Starting agent.process_message()")

            # Process the message
            result = await agent.process_message(prompt)

            # Handle streaming vs non-streaming
            if hasattr(result, "__aiter__"):
                # Streaming response
                async for chunk in result:
                    # Check if cancelled
                    if self._cancelled:
                        logger.info("Task cancelled, breaking loop")
                        break

                    # Truncate tool output if present, keep agent messages full
                    chunk_str = str(chunk)
                    truncated_chunk = self._truncate_tool_output(chunk_str)
                    await self._append_output(truncated_chunk)
            else:
                # Non-streaming response
                await self._append_output(str(result))
                # For non-streaming, set iterations to 1 if not already set
                if self.task.iterations == 0:
                    self.task.iterations = 1
                    await self._update_progress(1.0)

            logger.info(
                f"AgentExecutor.execute() completed for task_id={self.task.task_id}, iterations={self.task.iterations}"
            )

        except Exception as e:
            # Log error
            logger.error(
                f"AgentExecutor.execute() failed for task_id={self.task.task_id}: {str(e)}",
                exc_info=True,
            )
            await self._append_output(f"\nError: {str(e)}\n")
            raise


class ProcessExecutor(TaskExecutor):
    """
    Executor for process tasks.

    Runs a subprocess with the given command.
    """

    def __init__(self, task: Task, storage: TaskStorage):
        """
        Initialize process executor.

        Args:
            task: Task to execute
            storage: Task storage instance
        """
        super().__init__(task, storage)
        self._process: Optional[asyncio.subprocess.Process] = None

    async def execute(self) -> None:
        """Execute process task."""
        # Get command
        command = self.task.command
        if not command:
            raise ValueError("Process task requires 'command' field")

        # Get working directory
        working_dir = self.task.working_directory
        if working_dir:
            working_dir = Path(working_dir).expanduser()
            if not working_dir.exists():
                raise ValueError(f"Working directory does not exist: {working_dir}")
        else:
            working_dir = Path.cwd()

        try:
            # Start process
            self._process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(working_dir),
            )

            # Store PID
            self.task.pid = self._process.pid
            await self.storage.save_task(self.task)

            # Read output
            if self._process.stdout:
                while True:
                    # Check if cancelled
                    if self._cancelled:
                        break

                    # Read line
                    line = await self._process.stdout.readline()
                    if not line:
                        break

                    # Decode and append
                    text = line.decode("utf-8", errors="replace")
                    await self._append_output(text)

            # Wait for process to complete
            exit_code = await self._process.wait()

            # Store exit code and save task BEFORE checking exit code
            self.task.exit_code = exit_code
            await self.storage.save_task(self.task)

            # Append exit code info to output
            await self._append_output(f"\n--- Process exited with code {exit_code} ---\n")

            # Check exit code
            if exit_code != 0:
                raise RuntimeError(f"Process exited with code {exit_code}")

        except Exception as e:
            # Log error
            await self._append_output(f"\nError: {str(e)}\n")
            raise

        finally:
            # Clean up process
            if self._process and self._process.returncode is None:
                try:
                    self._process.terminate()
                    await asyncio.wait_for(self._process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    self._process.kill()
                    await self._process.wait()

    async def cancel(self) -> None:
        """Cancel the process execution."""
        await super().cancel()

        # Terminate process
        if self._process and self._process.returncode is None:
            try:
                # Try graceful termination first
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                # Force kill if termination times out
                self._process.kill()
                await self._process.wait()

            await self._append_output("\n--- Process cancelled ---\n")
