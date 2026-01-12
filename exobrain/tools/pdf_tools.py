"""PDF processing tools."""

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

from exobrain.tools.base import ConfigurableTool, ToolParameter, register_tool

if TYPE_CHECKING:
    from exobrain.config import Config


@register_tool
class ReadPdfTool(ConfigurableTool):
    """Tool to read and extract content from PDF files.

    Supports multiple operations:
    - info: Get basic PDF information (pages, size, etc.)
    - text: Extract text content from specified pages
    - metadata: Get PDF metadata (title, author, etc.)
    - search: Search for text patterns in the PDF
    """

    config_key: ClassVar[str] = "file_system"

    def __init__(
        self,
        allowed_paths: list[str],
        denied_paths: list[str],
        max_file_size: int = 52428800,  # 50MB default
    ) -> None:
        super().__init__(
            name="read_pdf",
            description=(
                "Read and extract content from PDF files. "
                "Supports getting info, extracting text, reading metadata, and searching content. "
                "Use 'operation' parameter to specify the action."
            ),
            parameters={
                "path": ToolParameter(
                    type="string",
                    description="Path to the PDF file",
                    required=True,
                ),
                "operation": ToolParameter(
                    type="string",
                    description=(
                        "Operation to perform: "
                        "'info' (get page count and size), "
                        "'text' (extract text content), "
                        "'metadata' (get PDF metadata), "
                        "'search' (search for text pattern)"
                    ),
                    enum=["info", "text", "metadata", "search"],
                    required=True,
                ),
                "pages": ToolParameter(
                    type="string",
                    description=(
                        "Page range for 'text' operation. "
                        "Examples: '1' (page 1), '1-5' (pages 1 to 5), '1,3,5' (specific pages). "
                        "If not specified, extracts all pages (up to max_length limit)."
                    ),
                    required=False,
                ),
                "pattern": ToolParameter(
                    type="string",
                    description="Text pattern to search for (required for 'search' operation). Supports regex.",
                    required=False,
                ),
                "case_sensitive": ToolParameter(
                    type="boolean",
                    description="Whether search should be case sensitive (default: false)",
                    required=False,
                ),
                "max_length": ToolParameter(
                    type="integer",
                    description=(
                        "Maximum characters to return for 'text' operation (default: 10000). "
                        "Use this to handle large PDFs."
                    ),
                    required=False,
                ),
                "max_results": ToolParameter(
                    type="integer",
                    description="Maximum search results to return for 'search' operation (default: 50)",
                    required=False,
                ),
            },
            requires_permission=True,
            permission_scope="file_system",
        )

        self._allowed_paths = [Path(p).expanduser() for p in allowed_paths]
        self._denied_paths = [Path(p).expanduser() for p in denied_paths]
        self._max_file_size = max_file_size

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
        # Empty allowed_paths list means no restrictions (allow all paths)
        if not self._allowed_paths:
            return True, ""

        for allowed in self._allowed_paths:
            try:
                path.relative_to(allowed)
                return True, ""
            except ValueError:
                continue

        return False, "Access denied: path is not in any allowed directory"

    def _parse_page_range(self, pages_str: str, total_pages: int) -> list[int]:
        """Parse page range string into list of page numbers.

        Args:
            pages_str: Page range string like "1", "1-5", "1,3,5", or "1-3,5,7-9"
            total_pages: Total number of pages in PDF

        Returns:
            List of page numbers (0-indexed)
        """
        page_numbers = set()

        # Split by comma for multiple ranges/pages
        parts = pages_str.split(",")

        for part in parts:
            part = part.strip()
            if "-" in part:
                # Range like "1-5"
                try:
                    start, end = part.split("-")
                    start = int(start.strip())
                    end = int(end.strip())
                    # Convert to 0-indexed and validate
                    for i in range(max(0, start - 1), min(total_pages, end)):
                        page_numbers.add(i)
                except ValueError:
                    continue
            else:
                # Single page like "3"
                try:
                    page_num = int(part)
                    # Convert to 0-indexed and validate
                    if 0 < page_num <= total_pages:
                        page_numbers.add(page_num - 1)
                except ValueError:
                    continue

        return sorted(list(page_numbers))

    async def _operation_info(self, reader: Any, path: Path) -> str:
        """Get basic PDF information."""
        num_pages = len(reader.pages)
        file_size = path.stat().st_size

        # Format file size
        if file_size < 1024:
            size_str = f"{file_size} bytes"
        elif file_size < 1024 * 1024:
            size_str = f"{file_size / 1024:.1f} KB"
        else:
            size_str = f"{file_size / (1024 * 1024):.1f} MB"

        # Check if encrypted
        is_encrypted = reader.is_encrypted

        result = [
            f"PDF Information for: {path.name}",
            f"Pages: {num_pages}",
            f"File size: {size_str}",
            f"Encrypted: {'Yes' if is_encrypted else 'No'}",
        ]

        return "\n".join(result)

    async def _operation_metadata(self, reader: Any) -> str:
        """Get PDF metadata."""
        try:
            meta = reader.metadata
            if not meta:
                return "No metadata available in this PDF"

            result = ["PDF Metadata:"]

            if meta.title:
                result.append(f"Title: {meta.title}")
            if meta.author:
                result.append(f"Author: {meta.author}")
            if meta.subject:
                result.append(f"Subject: {meta.subject}")
            if meta.creator:
                result.append(f"Creator: {meta.creator}")
            if meta.producer:
                result.append(f"Producer: {meta.producer}")
            if meta.creation_date:
                result.append(f"Created: {meta.creation_date}")
            if meta.modification_date:
                result.append(f"Modified: {meta.modification_date}")

            if len(result) == 1:
                return "No metadata available in this PDF"

            return "\n".join(result)
        except Exception as e:
            return f"Error reading metadata: {e}"

    async def _operation_text(
        self,
        reader: Any,
        pages_str: str | None,
        max_length: int,
    ) -> str:
        """Extract text from PDF."""
        total_pages = len(reader.pages)

        # Determine which pages to extract
        if pages_str:
            page_indices = self._parse_page_range(pages_str, total_pages)
            if not page_indices:
                return f"Error: Invalid page range '{pages_str}'. PDF has {total_pages} pages."
        else:
            # Extract all pages (will be limited by max_length)
            page_indices = list(range(total_pages))

        # Extract text
        extracted_text = []
        total_chars = 0
        truncated = False

        for page_idx in page_indices:
            try:
                page = reader.pages[page_idx]
                page_text = page.extract_text()

                if page_text:
                    page_header = f"\n--- Page {page_idx + 1} ---\n"

                    # Check if adding this page would exceed max_length
                    if total_chars + len(page_header) + len(page_text) > max_length:
                        # Add partial content if there's room
                        remaining = max_length - total_chars - len(page_header)
                        if remaining > 100:  # Only add if meaningful amount remains
                            extracted_text.append(page_header)
                            extracted_text.append(page_text[:remaining])
                        truncated = True
                        break

                    extracted_text.append(page_header)
                    extracted_text.append(page_text)
                    total_chars += len(page_header) + len(page_text)
            except Exception as e:
                extracted_text.append(
                    f"\n--- Page {page_idx + 1}: Error extracting text: {e} ---\n"
                )

        if not extracted_text:
            return "No text content found in the specified pages"

        result = "".join(extracted_text)

        # Add truncation notice
        if truncated:
            result += f"\n\n[Content truncated at {max_length} characters. "
            result += f"PDF has {total_pages} pages total. "
            result += "Use 'pages' parameter to read specific pages.]"

        return result

    async def _operation_search(
        self,
        reader: Any,
        pattern: str,
        case_sensitive: bool,
        max_results: int,
    ) -> str:
        """Search for text pattern in PDF."""
        try:
            flags = 0 if case_sensitive else re.IGNORECASE
            regex = re.compile(pattern, flags)
        except re.error as e:
            return f"Error: Invalid regular expression: {e}"

        results = []
        total_matches = 0

        for page_idx, page in enumerate(reader.pages):
            if total_matches >= max_results:
                break

            try:
                text = page.extract_text()
                if not text:
                    continue

                # Search line by line
                lines = text.split("\n")
                for line_idx, line in enumerate(lines):
                    if total_matches >= max_results:
                        break

                    if regex.search(line):
                        # Format: Page X, Line Y: matched_line
                        results.append(f"Page {page_idx + 1}, Line {line_idx + 1}: {line.strip()}")
                        total_matches += 1
            except Exception:
                continue

        if not results:
            return f"No matches found for pattern: {pattern}"

        output = [f"Found {total_matches} match(es) for pattern '{pattern}':\n"]
        output.extend(results)

        if total_matches >= max_results:
            output.append(
                f"\n[Showing first {max_results} results. Use 'max_results' parameter to see more.]"
            )

        return "\n".join(output)

    async def execute(self, **kwargs: Any) -> str:
        """Execute the tool."""
        path_str = kwargs.get("path", "")
        operation = kwargs.get("operation", "")

        if not path_str:
            return "Error: path parameter is required"

        if not operation:
            return "Error: operation parameter is required"

        path = Path(path_str).expanduser()

        # Check permissions
        allowed, message = self._check_permission(path)
        if not allowed:
            return message

        # Check if file exists
        if not path.exists():
            return f"Error: file not found: {path}"

        if not path.is_file():
            return f"Error: path is not a file: {path}"

        # Check file extension
        if path.suffix.lower() != ".pdf":
            return f"Error: file is not a PDF: {path}"

        # Check file size
        file_size = path.stat().st_size
        if file_size > self._max_file_size:
            max_mb = self._max_file_size / (1024 * 1024)
            actual_mb = file_size / (1024 * 1024)
            return f"Error: PDF file size ({actual_mb:.1f}MB) exceeds maximum allowed size ({max_mb:.1f}MB)"

        # Import pypdf (lazy import to avoid dependency issues)
        try:
            from pypdf import PdfReader
        except ImportError:
            return (
                "Error: pypdf library not installed. " "Please install it with: pip install pypdf"
            )

        # Read PDF
        try:
            reader = PdfReader(str(path))
        except Exception as e:
            return f"Error reading PDF: {e}"

        # Check if encrypted and locked
        if reader.is_encrypted:
            try:
                # Try to decrypt with empty password
                reader.decrypt("")
            except Exception:
                return "Error: PDF is password-protected. Please decrypt it first."

        # Execute operation
        try:
            if operation == "info":
                return await self._operation_info(reader, path)

            elif operation == "metadata":
                return await self._operation_metadata(reader)

            elif operation == "text":
                pages_str = kwargs.get("pages")
                max_length = kwargs.get("max_length", 10000)
                return await self._operation_text(reader, pages_str, max_length)

            elif operation == "search":
                pattern = kwargs.get("pattern", "")
                if not pattern:
                    return "Error: 'pattern' parameter is required for search operation"

                case_sensitive = kwargs.get("case_sensitive", False)
                max_results = kwargs.get("max_results", 50)
                return await self._operation_search(reader, pattern, case_sensitive, max_results)

            else:
                return f"Error: Unknown operation '{operation}'"

        except Exception as e:
            return f"Error executing operation '{operation}': {e}"

    @classmethod
    def from_config(cls, config: "Config") -> "ReadPdfTool | None":
        """Create tool instance from configuration.

        Args:
            config: Global application configuration

        Returns:
            ReadPdfTool instance if file_system is enabled, None otherwise
        """
        if not config.tools.file_system:
            return None

        fs_perms = config.permissions.file_system
        if not fs_perms.get("enabled", True):
            return None

        allowed_paths = fs_perms.get("allowed_paths") or []
        denied_paths = fs_perms.get("denied_paths") or []
        max_file_size = fs_perms.get("max_file_size", 52428800)  # 50MB default

        return cls(allowed_paths, denied_paths, max_file_size)
