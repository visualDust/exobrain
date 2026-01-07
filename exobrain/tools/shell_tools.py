"""Shell execution tools for ExoBrain."""

import asyncio
import logging
import platform
import re
from pathlib import Path
from typing import Any

from exobrain.tools.base import Tool, ToolParameter

logger = logging.getLogger(__name__)


class ShellExecuteTool(Tool):
    """Tool to execute shell commands with permission checks."""

    def __init__(
        self,
        allowed_directories: list[str],
        denied_directories: list[str],
        allowed_commands: list[str],
        denied_commands: list[str],
        timeout: int = 30,
    ) -> None:
        super().__init__(
            name="shell_execute",
            description="Execute a shell command in a specified directory. Use this to run terminal commands like ls, git, python scripts, etc.",
            parameters={
                "command": ToolParameter(
                    type="string",
                    description="The shell command to execute",
                    required=True,
                ),
                "working_directory": ToolParameter(
                    type="string",
                    description="The directory to execute the command in (default: current directory)",
                    required=False,
                ),
            },
            requires_permission=True,
            permission_scope="shell_execution",
        )

        self._allowed_directories = [Path(p).expanduser().resolve() for p in allowed_directories]
        self._denied_directories = [Path(p).expanduser().resolve() for p in denied_directories]
        self._allowed_commands = allowed_commands
        self._denied_commands = denied_commands
        self._timeout = timeout

    def _check_directory_permission(self, directory: Path) -> tuple[bool, str]:
        """Check if command execution is allowed in the given directory.

        Args:
            directory: Directory to check

        Returns:
            Tuple of (allowed, message)
        """
        directory = directory.expanduser().resolve()

        # Check denied directories first
        for denied in self._denied_directories:
            try:
                directory.relative_to(denied)
                return (
                    False,
                    f"Access denied: cannot execute commands in {denied}",
                )
            except ValueError:
                continue

        # Check allowed directories
        for allowed in self._allowed_directories:
            try:
                directory.relative_to(allowed)
                return True, ""
            except ValueError:
                continue

        return (
            False,
            f"Access denied: directory {directory} is not in allowed list",
        )

    def _check_command_permission(self, command: str) -> tuple[bool, str]:
        """Check if the command is allowed to be executed.

        Args:
            command: Command to check

        Returns:
            Tuple of (allowed, message)
        """
        command = command.strip()

        # Check denied commands first (exact match or pattern)
        for denied_pattern in self._denied_commands:
            if self._match_command_pattern(command, denied_pattern):
                return (
                    False,
                    f"Access denied: command matches denied pattern '{denied_pattern}'",
                )

        # If allowed_commands is empty, allow all commands (unless denied)
        if not self._allowed_commands:
            return True, ""

        # Check allowed commands
        for allowed_pattern in self._allowed_commands:
            if self._match_command_pattern(command, allowed_pattern):
                return True, ""

        return False, f"Access denied: command not in allowed list"

    def _match_command_pattern(self, command: str, pattern: str) -> bool:
        """Match a command against a pattern.

        Patterns support:
        - Exact match: "ls"
        - Wildcard suffix: "git *" (matches "git status", "git commit", etc.)
        - Regex: "/^python.*/" (anything between slashes is treated as regex)

        Args:
            command: Command to match
            pattern: Pattern to match against

        Returns:
            True if command matches pattern
        """
        # Regex pattern (between slashes)
        if pattern.startswith("/") and pattern.endswith("/"):
            regex = pattern[1:-1]
            try:
                return bool(re.match(regex, command))
            except re.error:
                logger.warning(f"Invalid regex pattern: {pattern}")
                return False

        # Wildcard pattern
        if "*" in pattern:
            # Convert shell-style wildcard to regex
            # Escape special regex chars except *
            escaped = re.escape(pattern).replace(r"\*", ".*")
            return bool(re.match(f"^{escaped}$", command))

        # Exact match
        return command == pattern or command.split()[0] == pattern

    async def execute(self, **kwargs: Any) -> str:
        """Execute shell command.

        Args:
            **kwargs: Tool parameters including 'command' and 'working_directory'

        Returns:
            Command output or error message
        """
        command = kwargs.get("command", "")
        working_directory = kwargs.get("working_directory", ".")

        if not command:
            return "Error: command parameter is required"

        # Check command permission
        allowed, message = self._check_command_permission(command)
        if not allowed:
            return message

        # Resolve working directory
        work_dir = Path(working_directory).expanduser().resolve()

        # Check if directory exists
        if not work_dir.exists():
            return f"Error: directory not found: {work_dir}"

        if not work_dir.is_dir():
            return f"Error: path is not a directory: {work_dir}"

        # Check directory permission
        allowed, message = self._check_directory_permission(work_dir)
        if not allowed:
            return message

        # Execute command
        try:
            logger.debug(f"Executing command: {command} in {work_dir}")

            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(work_dir),
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self._timeout,
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return f"Error: command timed out after {self._timeout} seconds"

            # Decode output
            stdout_text = stdout.decode("utf-8", errors="replace").strip()
            stderr_text = stderr.decode("utf-8", errors="replace").strip()

            # Format result
            result_parts = [
                f"Command: {command}",
                f"Working directory: {work_dir}",
                f"Exit code: {process.returncode}",
            ]

            if stdout_text:
                result_parts.append(f"\n--- Standard Output ---\n{stdout_text}")

            if stderr_text:
                result_parts.append(f"\n--- Standard Error ---\n{stderr_text}")

            if process.returncode != 0:
                result_parts.append(f"\n⚠ Command failed with exit code {process.returncode}")

            return "\n".join(result_parts)

        except Exception as e:
            logger.error(f"Error executing command: {e}")
            return f"Error executing command: {e}"


class GetOSInfoTool(Tool):
    """Tool to get information about the current operating system."""

    def __init__(self) -> None:
        super().__init__(
            name="get_os_info",
            description="Get information about the current operating system (Windows, Linux, macOS). Use this to determine the OS type before executing OS-specific commands.",
            parameters={},
            requires_permission=False,
        )

    async def execute(self, **kwargs: Any) -> str:  # noqa: ARG002
        """Get operating system information.

        Returns:
            OS information including platform, system, release, and version
        """
        try:
            system = platform.system()

            # Normalize system name
            if system == "Darwin":
                os_type = "macOS"
            elif system == "Windows":
                os_type = "Windows"
            elif system == "Linux":
                os_type = "Linux"
            else:
                os_type = system

            # Gather detailed information
            info_parts = [
                f"Operating System: {os_type}",
                f"Platform: {platform.platform()}",
                f"System: {platform.system()}",
                f"Release: {platform.release()}",
                f"Version: {platform.version()}",
                f"Machine: {platform.machine()}",
                f"Processor: {platform.processor()}",
            ]

            # Add Python version for reference
            info_parts.append(f"Python Version: {platform.python_version()}")

            return "\n".join(info_parts)

        except Exception as e:
            logger.error(f"Error getting OS information: {e}")
            return f"Error getting OS information: {e}"
