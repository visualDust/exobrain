"""File system tools."""

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

import aiofiles

from exobrain.tools.base import ConfigurableTool, ToolParameter, register_tool

if TYPE_CHECKING:
    from exobrain.config import Config


@register_tool
class ReadFileTool(ConfigurableTool):
    """Tool to read file contents."""

    config_key: ClassVar[str] = "file_system"

    def __init__(self, allowed_paths: list[str], denied_paths: list[str]) -> None:
        super().__init__(
            name="read_file",
            description="Read the contents of a file",
            parameters={
                "path": ToolParameter(
                    type="string",
                    description="Path to the file to read",
                    required=True,
                )
            },
            requires_permission=True,
            permission_scope="file_system",
        )

        self._allowed_paths = [Path(p).expanduser() for p in allowed_paths]
        self._denied_paths = [Path(p).expanduser() for p in denied_paths]

    def _check_permission(self, path: Path) -> tuple[bool, str]:
        """Check if access to path is allowed."""
        path = path.expanduser().resolve()

        # Check denied paths first
        for denied in self._denied_paths:
            try:
                path.relative_to(denied)
                return (
                    False,
                    f"Access denied: path is in blocked directory {denied}",
                )
            except ValueError:
                continue

        # Check allowed paths
        for allowed in self._allowed_paths:
            try:
                path.relative_to(allowed)
                return True, ""
            except ValueError:
                continue

        return False, f"Access denied: path is not in any allowed directory"

    async def execute(self, **kwargs: Any) -> str:
        """Execute the tool."""
        path_str = kwargs.get("path", "")
        if not path_str:
            return "Error: path parameter is required"

        path = Path(path_str)

        # Check permissions
        allowed, message = self._check_permission(path)
        if not allowed:
            return message

        # Check if file exists
        if not path.exists():
            return f"Error: file not found: {path}"

        if not path.is_file():
            return f"Error: path is not a file: {path}"

        # Read file
        try:
            async with aiofiles.open(path, "r", encoding="utf-8") as f:
                content = await f.read()
            return content
        except Exception as e:
            return f"Error reading file: {e}"

    @classmethod
    def from_config(cls, config: "Config") -> "ReadFileTool | None":
        """Create tool instance from configuration.

        Args:
            config: Global application configuration

        Returns:
            ReadFileTool instance if file_system is enabled, None otherwise
        """
        if not config.tools.file_system:
            return None

        fs_perms = config.permissions.file_system
        if not fs_perms.get("enabled", True):
            return None

        allowed_paths = fs_perms.get("allowed_paths") or []
        denied_paths = fs_perms.get("denied_paths") or []

        return cls(allowed_paths, denied_paths)


@register_tool
class WriteFileTool(ConfigurableTool):
    """Tool to write contents to a file."""

    config_key: ClassVar[str] = "file_system"

    def __init__(
        self,
        allowed_paths: list[str],
        denied_paths: list[str],
        max_file_size: int,
        allow_edit: bool = False,
    ) -> None:
        super().__init__(
            name="write_file",
            description="Write content to a file",
            parameters={
                "path": ToolParameter(
                    type="string",
                    description="Path to the file to write",
                    required=True,
                ),
                "content": ToolParameter(
                    type="string",
                    description="Content to write to the file",
                    required=True,
                ),
            },
            requires_permission=True,
            permission_scope="file_system",
        )

        self._allowed_paths = [Path(p).expanduser() for p in allowed_paths]
        self._denied_paths = [Path(p).expanduser() for p in denied_paths]
        self._max_file_size = max_file_size
        self._allow_edit = allow_edit

    def _check_permission(self, path: Path) -> tuple[bool, str]:
        """Check if access to path is allowed."""
        path = path.expanduser().resolve()

        # Check denied paths first
        for denied in self._denied_paths:
            try:
                path.relative_to(denied)
                return (
                    False,
                    f"Access denied: path is in blocked directory {denied}",
                )
            except ValueError:
                continue

        # Check allowed paths
        for allowed in self._allowed_paths:
            try:
                path.relative_to(allowed)
                return True, ""
            except ValueError:
                continue

        return False, f"Access denied: path is not in any allowed directory"

    async def execute(self, **kwargs: Any) -> str:
        """Execute the tool."""
        path_str = kwargs.get("path", "")
        content = kwargs.get("content", "")

        if not path_str:
            return "Error: path parameter is required"

        path = Path(path_str)

        # Check permissions
        allowed, message = self._check_permission(path)
        if not allowed:
            return message

        if not self._allow_edit:
            return "Access denied: editing not allowed for this session (requires edit permission)"

        # Check content size
        if len(content.encode("utf-8")) > self._max_file_size:
            return f"Error: content size exceeds maximum of {self._max_file_size} bytes"

        # Create parent directories if needed
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            return f"Error creating parent directories: {e}"

        # Write file
        try:
            async with aiofiles.open(path, "w", encoding="utf-8") as f:
                await f.write(content)
            return f"Successfully wrote {len(content)} characters to {path}"
        except Exception as e:
            return f"Error writing file: {e}"

    @classmethod
    def from_config(cls, config: "Config") -> "WriteFileTool | None":
        """Create tool instance from configuration.

        Args:
            config: Global application configuration

        Returns:
            WriteFileTool instance if file_system is enabled, None otherwise
        """
        if not config.tools.file_system:
            return None

        fs_perms = config.permissions.file_system
        if not fs_perms.get("enabled", True):
            return None

        allowed_paths = fs_perms.get("allowed_paths") or []
        denied_paths = fs_perms.get("denied_paths") or []
        max_file_size = fs_perms.get("max_file_size", 10485760)
        allow_edit = fs_perms.get("allow_edit", False)

        return cls(allowed_paths, denied_paths, max_file_size, allow_edit)


@register_tool
class ListDirectoryTool(ConfigurableTool):
    """Tool to list directory contents."""

    config_key: ClassVar[str] = "file_system"

    def __init__(self, allowed_paths: list[str], denied_paths: list[str]) -> None:
        super().__init__(
            name="list_directory",
            description="List the contents of a directory",
            parameters={
                "path": ToolParameter(
                    type="string",
                    description="Path to the directory to list",
                    required=True,
                )
            },
            requires_permission=True,
            permission_scope="file_system",
        )

        self._allowed_paths = [Path(p).expanduser() for p in allowed_paths]
        self._denied_paths = [Path(p).expanduser() for p in denied_paths]

    def _check_permission(self, path: Path) -> tuple[bool, str]:
        """Check if access to path is allowed."""
        path = path.expanduser().resolve()

        # Check denied paths first
        for denied in self._denied_paths:
            try:
                path.relative_to(denied)
                return (
                    False,
                    f"Access denied: path is in blocked directory {denied}",
                )
            except ValueError:
                continue

        # Check allowed paths
        for allowed in self._allowed_paths:
            try:
                path.relative_to(allowed)
                return True, ""
            except ValueError:
                continue

        return False, f"Access denied: path is not in any allowed directory"

    async def execute(self, **kwargs: Any) -> str:
        """Execute the tool."""
        path_str = kwargs.get("path", "")
        if not path_str:
            return "Error: path parameter is required"

        path = Path(path_str).expanduser()

        # Check permissions
        allowed, message = self._check_permission(path)
        if not allowed:
            return message

        # Check if directory exists
        if not path.exists():
            return f"Error: directory not found: {path}"

        if not path.is_dir():
            return f"Error: path is not a directory: {path}"

        # List directory
        try:
            entries = []
            for entry in sorted(path.iterdir()):
                entry_type = "dir" if entry.is_dir() else "file"
                size = entry.stat().st_size if entry.is_file() else 0
                entries.append(f"{entry_type:4} {size:>10} {entry.name}")

            if not entries:
                return f"Directory is empty: {path}"

            return "\n".join([f"Contents of {path}:", ""] + entries)
        except Exception as e:
            return f"Error listing directory: {e}"

    @classmethod
    def from_config(cls, config: "Config") -> "ListDirectoryTool | None":
        """Create tool instance from configuration.

        Args:
            config: Global application configuration

        Returns:
            ListDirectoryTool instance if file_system is enabled, None otherwise
        """
        if not config.tools.file_system:
            return None

        fs_perms = config.permissions.file_system
        if not fs_perms.get("enabled", True):
            return None

        allowed_paths = fs_perms.get("allowed_paths") or []
        denied_paths = fs_perms.get("denied_paths") or []

        return cls(allowed_paths, denied_paths)


@register_tool
class SearchFilesTool(ConfigurableTool):
    """Tool to search for files matching a pattern."""

    config_key: ClassVar[str] = "file_system"

    def __init__(self, allowed_paths: list[str], denied_paths: list[str]) -> None:
        super().__init__(
            name="search_files",
            description="Search for files matching a pattern (supports wildcards)",
            parameters={
                "pattern": ToolParameter(
                    type="string",
                    description="Pattern to match (e.g., '*.py', 'test_*.txt')",
                    required=True,
                ),
                "path": ToolParameter(
                    type="string",
                    description="Directory to search in (default: current directory)",
                    required=False,
                ),
            },
            requires_permission=True,
            permission_scope="file_system",
        )

        self._allowed_paths = [Path(p).expanduser() for p in allowed_paths]
        self._denied_paths = [Path(p).expanduser() for p in denied_paths]

    def _check_permission(self, path: Path) -> tuple[bool, str]:
        """Check if access to path is allowed."""
        path = path.expanduser().resolve()

        # Check denied paths first
        for denied in self._denied_paths:
            try:
                path.relative_to(denied)
                return (
                    False,
                    f"Access denied: path is in blocked directory {denied}",
                )
            except ValueError:
                continue

        # Check allowed paths
        for allowed in self._allowed_paths:
            try:
                path.relative_to(allowed)
                return True, ""
            except ValueError:
                continue

        return False, f"Access denied: path is not in any allowed directory"

    async def execute(self, **kwargs: Any) -> str:
        """Execute the tool."""
        pattern = kwargs.get("pattern", "")
        path_str = kwargs.get("path", ".")

        if not pattern:
            return "Error: pattern parameter is required"

        path = Path(path_str).expanduser().resolve()

        # Check permissions
        allowed, message = self._check_permission(path)
        if not allowed:
            return message

        # Check if directory exists
        if not path.exists():
            return f"Error: directory not found: {path}"

        if not path.is_dir():
            return f"Error: path is not a directory: {path}"

        # Search for files
        try:
            matches = list(path.rglob(pattern))
            if not matches:
                return f"No files found matching pattern: {pattern}"

            results = [f"Found {len(matches)} files matching '{pattern}':"]
            for match in matches[:50]:  # Limit to 50 results
                results.append(str(match))

            if len(matches) > 50:
                results.append(f"\n... and {len(matches) - 50} more")

            return "\n".join(results)
        except Exception as e:
            return f"Error searching files: {e}"

    @classmethod
    def from_config(cls, config: "Config") -> "SearchFilesTool | None":
        """Create tool instance from configuration.

        Args:
            config: Global application configuration

        Returns:
            SearchFilesTool instance if file_system is enabled, None otherwise
        """
        if not config.tools.file_system:
            return None

        fs_perms = config.permissions.file_system
        if not fs_perms.get("enabled", True):
            return None

        allowed_paths = fs_perms.get("allowed_paths") or []
        denied_paths = fs_perms.get("denied_paths") or []

        return cls(allowed_paths, denied_paths)


@register_tool
class EditFileTool(ConfigurableTool):
    """Tool to perform precise string replacement in files."""

    config_key: ClassVar[str] = "file_system"

    def __init__(
        self,
        allowed_paths: list[str],
        denied_paths: list[str],
        max_file_size: int,
        allow_edit: bool = False,
    ) -> None:
        super().__init__(
            name="edit_file",
            description="Perform precise string replacement in a file. The old_string must exist exactly once in the file to ensure safe replacement.",
            parameters={
                "path": ToolParameter(
                    type="string",
                    description="Path to the file to edit",
                    required=True,
                ),
                "old_string": ToolParameter(
                    type="string",
                    description="Exact string to be replaced (must appear exactly in the file)",
                    required=True,
                ),
                "new_string": ToolParameter(
                    type="string",
                    description="New string to replace the old string with",
                    required=True,
                ),
            },
            requires_permission=True,
            permission_scope="file_system",
        )

        self._allowed_paths = [Path(p).expanduser() for p in allowed_paths]
        self._denied_paths = [Path(p).expanduser() for p in denied_paths]
        self._max_file_size = max_file_size
        self._allow_edit = allow_edit

    def _check_permission(self, path: Path) -> tuple[bool, str]:
        """Check if access to path is allowed."""
        path = path.expanduser().resolve()

        # Check denied paths first
        for denied in self._denied_paths:
            try:
                path.relative_to(denied)
                return (
                    False,
                    f"Access denied: path is in blocked directory {denied}",
                )
            except ValueError:
                continue

        # Check allowed paths
        for allowed in self._allowed_paths:
            try:
                path.relative_to(allowed)
                return True, ""
            except ValueError:
                continue

        return False, f"Access denied: path is not in any allowed directory"

    async def execute(self, **kwargs: Any) -> str:
        """Execute the tool."""
        path_str = kwargs.get("path", "")
        old_string = kwargs.get("old_string", "")
        new_string = kwargs.get("new_string", "")

        if not path_str:
            return "Error: path parameter is required"

        if not old_string:
            return "Error: old_string parameter is required"

        if old_string == new_string:
            return "Error: old_string and new_string are identical, no changes needed"

        path = Path(path_str)

        # Check permissions
        allowed, message = self._check_permission(path)
        if not allowed:
            return message

        if not self._allow_edit:
            return "Access denied: editing not allowed for this session (requires edit permission)"

        # Check if file exists
        if not path.exists():
            return f"Error: file not found: {path}"

        if not path.is_file():
            return f"Error: path is not a file: {path}"

        # Read file content
        try:
            async with aiofiles.open(path, "r", encoding="utf-8") as f:
                content = await f.read()
        except Exception as e:
            return f"Error reading file: {e}"

        # Check file size
        if len(content.encode("utf-8")) > self._max_file_size:
            return f"Error: file size exceeds maximum of {self._max_file_size} bytes"

        # Check if old_string exists in the file
        if old_string not in content:
            return (
                f"Error: old_string not found in file. Please verify the exact string to replace."
            )

        # Count occurrences to ensure uniqueness
        count = content.count(old_string)
        if count > 1:
            return f"Error: old_string appears {count} times in the file. For safety, it must appear exactly once. Please provide a longer, unique string."

        # Perform replacement
        new_content = content.replace(old_string, new_string, 1)

        # Write back to file
        try:
            async with aiofiles.open(path, "w", encoding="utf-8") as f:
                await f.write(new_content)

            lines_changed = len([line for line in old_string.split("\n") if line.strip()])
            return f"Successfully edited {path}: replaced {len(old_string)} characters with {len(new_string)} characters ({lines_changed} lines affected)"
        except Exception as e:
            return f"Error writing file: {e}"

    @classmethod
    def from_config(cls, config: "Config") -> "EditFileTool | None":
        """Create tool instance from configuration.

        Args:
            config: Global application configuration

        Returns:
            EditFileTool instance if file_system is enabled, None otherwise
        """
        if not config.tools.file_system:
            return None

        fs_perms = config.permissions.file_system
        if not fs_perms.get("enabled", True):
            return None

        allowed_paths = fs_perms.get("allowed_paths") or []
        denied_paths = fs_perms.get("denied_paths") or []
        max_file_size = fs_perms.get("max_file_size", 10485760)
        allow_edit = fs_perms.get("allow_edit", False)

        return cls(allowed_paths, denied_paths, max_file_size, allow_edit)


@register_tool
class GrepFileTool(ConfigurableTool):
    """Tool to search for text patterns in file contents."""

    config_key: ClassVar[str] = "file_system"

    def __init__(self, allowed_paths: list[str], denied_paths: list[str]) -> None:
        super().__init__(
            name="grep_files",
            description="Search for text patterns in file contents. Returns matching lines with file names and line numbers.",
            parameters={
                "pattern": ToolParameter(
                    type="string",
                    description="Text pattern to search for (supports regular expressions)",
                    required=True,
                ),
                "path": ToolParameter(
                    type="string",
                    description="Directory or file to search in (default: current directory)",
                    required=False,
                ),
                "file_pattern": ToolParameter(
                    type="string",
                    description="File name pattern to filter (e.g., '*.py', '*.txt')",
                    required=False,
                ),
                "case_sensitive": ToolParameter(
                    type="boolean",
                    description="Whether the search should be case sensitive (default: true)",
                    required=False,
                ),
                "max_results": ToolParameter(
                    type="integer",
                    description="Maximum number of results to return (default: 100)",
                    required=False,
                ),
            },
            requires_permission=True,
            permission_scope="file_system",
        )

        self._allowed_paths = [Path(p).expanduser() for p in allowed_paths]
        self._denied_paths = [Path(p).expanduser() for p in denied_paths]

    def _check_permission(self, path: Path) -> tuple[bool, str]:
        """Check if access to path is allowed."""
        path = path.expanduser().resolve()

        # Check denied paths first
        for denied in self._denied_paths:
            try:
                path.relative_to(denied)
                return (
                    False,
                    f"Access denied: path is in blocked directory {denied}",
                )
            except ValueError:
                continue

        # Check allowed paths
        for allowed in self._allowed_paths:
            try:
                path.relative_to(allowed)
                return True, ""
            except ValueError:
                continue

        return False, f"Access denied: path is not in any allowed directory"

    async def execute(self, **kwargs: Any) -> str:
        """Execute the tool."""
        pattern = kwargs.get("pattern", "")
        path_str = kwargs.get("path", ".")
        file_pattern = kwargs.get("file_pattern", "*")
        case_sensitive = kwargs.get("case_sensitive", True)
        max_results = kwargs.get("max_results", 100)

        if not pattern:
            return "Error: pattern parameter is required"

        path = Path(path_str).expanduser().resolve()

        # Check permissions
        allowed, message = self._check_permission(path)
        if not allowed:
            return message

        # Check if path exists
        if not path.exists():
            return f"Error: path not found: {path}"

        # Compile regex pattern
        try:
            flags = 0 if case_sensitive else re.IGNORECASE
            regex = re.compile(pattern, flags)
        except re.error as e:
            return f"Error: invalid regular expression: {e}"

        # Collect files to search
        files_to_search = []
        if path.is_file():
            files_to_search = [path]
        elif path.is_dir():
            try:
                files_to_search = list(path.rglob(file_pattern))
                # Filter to only include files (not directories)
                files_to_search = [f for f in files_to_search if f.is_file()]
            except Exception as e:
                return f"Error listing files: {e}"
        else:
            return f"Error: path is neither a file nor a directory: {path}"

        # Search in files
        results = []
        total_matches = 0

        for file_path in files_to_search:
            if total_matches >= max_results:
                break

            # Skip binary files and very large files
            try:
                if file_path.stat().st_size > 10 * 1024 * 1024:  # Skip files > 10MB
                    continue

                async with aiofiles.open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = await f.read()

                lines = content.split("\n")
                for line_num, line in enumerate(lines, start=1):
                    if total_matches >= max_results:
                        break

                    if regex.search(line):
                        # Format: filename:line_number: matched_line
                        relative_path = (
                            file_path.relative_to(path) if path.is_dir() else file_path.name
                        )
                        results.append(f"{relative_path}:{line_num}: {line.strip()}")
                        total_matches += 1

            except (UnicodeDecodeError, PermissionError):
                # Skip files that can't be read as text or don't have permission
                continue
            except Exception:
                # Skip files that cause other errors
                continue

        if not results:
            return f"No matches found for pattern: {pattern}"

        output = [f"Found {total_matches} match(es) for pattern '{pattern}':"]
        output.extend(results)

        if total_matches >= max_results:
            output.append(
                f"\n... (showing first {max_results} results, use max_results parameter to see more)"
            )

        return "\n".join(output)

    @classmethod
    def from_config(cls, config: "Config") -> "GrepFileTool | None":
        """Create tool instance from configuration.

        Args:
            config: Global application configuration

        Returns:
            GrepFileTool instance if file_system is enabled, None otherwise
        """
        if not config.tools.file_system:
            return None

        fs_perms = config.permissions.file_system
        if not fs_perms.get("enabled", True):
            return None

        allowed_paths = fs_perms.get("allowed_paths") or []
        denied_paths = fs_perms.get("denied_paths") or []

        return cls(allowed_paths, denied_paths)
