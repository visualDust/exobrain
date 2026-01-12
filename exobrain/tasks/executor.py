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

    async def execute(self) -> None:
        """Execute agent task."""
        logger.info(f"AgentExecutor.execute() started for task_id={self.task.task_id}")

        # Import here to avoid circular dependency
        from exobrain.cli.util import create_agent_from_config
        from exobrain.config import load_config

        try:
            # Get configuration
            logger.info("Loading config")
            config, _ = load_config()
            logger.info(f"Config loaded successfully")

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

            # Set up output capture
            output_buffer = []

            def capture_output(text: str):
                """Capture agent output."""
                output_buffer.append(text)

            # Run agent
            logger.info("Starting agent.process_message()")
            iteration = 0

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

                    # Append output
                    await self._append_output(str(chunk))

                    # Update iteration count
                    iteration += 1
                    self.task.iterations = iteration

                    # Update progress
                    progress = min(iteration / max_iterations, 1.0)
                    await self._update_progress(progress)

                    # Check max iterations
                    if iteration >= max_iterations:
                        logger.info(f"Max iterations reached: {iteration}")
                        break
            else:
                # Non-streaming response
                await self._append_output(str(result))
                iteration = 1
                self.task.iterations = iteration
                await self._update_progress(1.0)

            logger.info(f"AgentExecutor.execute() completed for task_id={self.task.task_id}")

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

            # Store exit code
            self.task.exit_code = exit_code
            await self.storage.save_task(self.task)

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
