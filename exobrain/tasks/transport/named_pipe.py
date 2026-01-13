"""Named pipe transport implementation for Windows."""

import asyncio
import json
from typing import Any, Dict, Optional

from .base import Transport, TransportServer


class NamedPipeTransport(Transport):
    """Client-side Named pipe transport for Windows."""

    def __init__(self, pipe_name: str):
        r"""
        Initialize Named pipe transport.

        Args:
            pipe_name: Name of the pipe (e.g., r"\\.\pipe\exobrain-task-daemon")
        """
        self.pipe_name = pipe_name
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None

    async def connect(self) -> None:
        """Establish connection to the daemon."""
        try:
            import pywintypes
            import win32file
        except ImportError:
            raise ImportError(
                "pywin32 is required for Named pipe transport on Windows. "
                "Install it with: pip install pywin32"
            )

        # Open named pipe
        try:
            handle = win32file.CreateFile(
                self.pipe_name,
                win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                0,
                None,
                win32file.OPEN_EXISTING,
                0,
                None,
            )
        except pywintypes.error as e:
            raise ConnectionError(f"Failed to connect to pipe {self.pipe_name}: {e}")

        # Create asyncio streams from pipe handle
        # Note: This is a simplified implementation
        # In production, we'd need proper async pipe handling
        self._handle = handle
        self._connected = True

    async def disconnect(self) -> None:
        """Close connection to the daemon."""
        if hasattr(self, "_handle"):
            try:
                import win32file

                win32file.CloseHandle(self._handle)
            except Exception:
                pass
            self._connected = False

    async def send_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send a request to the daemon and wait for response.

        Args:
            request: Request dictionary

        Returns:
            Response dictionary
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to daemon")

        try:
            import win32file
        except ImportError:
            raise ImportError("pywin32 is required for Named pipe transport")

        # Serialize request
        request_data = json.dumps(request).encode("utf-8")
        request_length = len(request_data)

        # Send length prefix (4 bytes) + data
        message = request_length.to_bytes(4, "big") + request_data

        # Write to pipe
        win32file.WriteFile(self._handle, message)

        # Read response length prefix
        _, length_bytes = win32file.ReadFile(self._handle, 4)
        response_length = int.from_bytes(length_bytes, "big")

        # Read response data
        _, response_data = win32file.ReadFile(self._handle, response_length)
        response = json.loads(response_data.decode("utf-8"))

        return response

    def is_connected(self) -> bool:
        """Check if transport is connected."""
        return hasattr(self, "_connected") and self._connected


class NamedPipeServer(TransportServer):
    """Server-side Named pipe transport for Windows."""

    def __init__(self, pipe_name: str):
        r"""
        Initialize Named pipe server.

        Args:
            pipe_name: Name of the pipe (e.g., r"\\.\pipe\exobrain-task-daemon")
        """
        self.pipe_name = pipe_name
        self._running = False
        self._request_handler = None
        self._server_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start the transport server."""
        try:
            pass
        except ImportError:
            raise ImportError(
                "pywin32 is required for Named pipe transport on Windows. "
                "Install it with: pip install pywin32"
            )

        self._running = True
        self._server_task = asyncio.create_task(self._run_server())

    async def stop(self) -> None:
        """Stop the transport server."""
        self._running = False
        if self._server_task:
            self._server_task.cancel()
            try:
                await self._server_task
            except asyncio.CancelledError:
                pass
            self._server_task = None

    async def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle an incoming request.

        Args:
            request: Request dictionary

        Returns:
            Response dictionary
        """
        return await self._handle_request_with_handler(request)

    def is_running(self) -> bool:
        """Check if server is running."""
        return self._running

    async def _run_server(self) -> None:
        """Run the named pipe server loop."""
        try:
            import pywintypes
            import win32pipe
        except ImportError:
            raise ImportError("pywin32 is required for Named pipe transport")

        while self._running:
            try:
                # Create named pipe
                pipe = win32pipe.CreateNamedPipe(
                    self.pipe_name,
                    win32pipe.PIPE_ACCESS_DUPLEX,
                    win32pipe.PIPE_TYPE_MESSAGE
                    | win32pipe.PIPE_READMODE_MESSAGE
                    | win32pipe.PIPE_WAIT,
                    win32pipe.PIPE_UNLIMITED_INSTANCES,
                    65536,
                    65536,
                    0,
                    None,
                )

                # Wait for client connection
                win32pipe.ConnectNamedPipe(pipe, None)

                # Handle client in background
                asyncio.create_task(self._handle_client(pipe))

            except pywintypes.error as e:
                if self._running:
                    print(f"Error in pipe server: {e}")
                    await asyncio.sleep(1)

    async def _handle_client(self, pipe) -> None:
        """
        Handle a client connection.

        Args:
            pipe: Pipe handle
        """
        try:
            import win32file
        except ImportError:
            return

        try:
            while self._running:
                # Read request length prefix
                _, length_bytes = win32file.ReadFile(pipe, 4)
                request_length = int.from_bytes(length_bytes, "big")

                # Read request data
                _, request_data = win32file.ReadFile(pipe, request_length)
                request = json.loads(request_data.decode("utf-8"))

                # Handle request
                response = await self.handle_request(request)

                # Serialize response
                response_data = json.dumps(response).encode("utf-8")
                response_length = len(response_data)

                # Send length prefix + data
                message = response_length.to_bytes(4, "big") + response_data
                win32file.WriteFile(pipe, message)

        except Exception as e:
            if self._running:
                print(f"Error handling client: {e}")
        finally:
            try:
                win32file.CloseHandle(pipe)
            except Exception:
                pass
