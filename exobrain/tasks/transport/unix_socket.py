"""Unix socket transport implementation for Linux/macOS."""

import asyncio
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

from .base import Transport, TransportServer


class UnixSocketTransport(Transport):
    """Client-side Unix socket transport."""

    def __init__(self, socket_path: str):
        """
        Initialize Unix socket transport.

        Args:
            socket_path: Path to Unix socket file
        """
        self.socket_path = Path(socket_path).expanduser()
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None

    async def connect(self) -> None:
        """Establish connection to the daemon."""
        if not self.socket_path.exists():
            raise ConnectionError(f"Socket file not found: {self.socket_path}")

        self._reader, self._writer = await asyncio.open_unix_connection(str(self.socket_path))

    async def disconnect(self) -> None:
        """Close connection to the daemon."""
        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()
            self._writer = None
            self._reader = None

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

        # Serialize request
        request_data = json.dumps(request).encode("utf-8")
        request_length = len(request_data)

        # Send length prefix (4 bytes) + data
        self._writer.write(request_length.to_bytes(4, "big"))
        self._writer.write(request_data)
        await self._writer.drain()

        # Read response length prefix
        length_bytes = await self._reader.readexactly(4)
        response_length = int.from_bytes(length_bytes, "big")

        # Read response data
        response_data = await self._reader.readexactly(response_length)
        response = json.loads(response_data.decode("utf-8"))

        return response

    def is_connected(self) -> bool:
        """Check if transport is connected."""
        return self._writer is not None and not self._writer.is_closing()


class UnixSocketServer(TransportServer):
    """Server-side Unix socket transport."""

    def __init__(self, socket_path: str):
        """
        Initialize Unix socket server.

        Args:
            socket_path: Path to Unix socket file
        """
        self.socket_path = Path(socket_path).expanduser()
        self._server: Optional[asyncio.Server] = None
        self._request_handler = None

    async def start(self) -> None:
        """Start the transport server."""
        # Remove existing socket file if it exists
        if self.socket_path.exists():
            self.socket_path.unlink()

        # Ensure parent directory exists
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)

        # Start Unix socket server
        self._server = await asyncio.start_unix_server(self._handle_client, str(self.socket_path))

        # Set socket permissions (owner only)
        os.chmod(self.socket_path, 0o600)

    async def stop(self) -> None:
        """Stop the transport server."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        # Clean up socket file
        if self.socket_path.exists():
            self.socket_path.unlink()

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
        return self._server is not None and self._server.is_serving()

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """
        Handle a client connection.

        Args:
            reader: Stream reader
            writer: Stream writer
        """
        try:
            while True:
                # Read request length prefix
                length_bytes = await reader.readexactly(4)
                request_length = int.from_bytes(length_bytes, "big")

                # Read request data
                request_data = await reader.readexactly(request_length)
                request = json.loads(request_data.decode("utf-8"))

                # Handle request
                response = await self.handle_request(request)

                # Serialize response
                response_data = json.dumps(response).encode("utf-8")
                response_length = len(response_data)

                # Send length prefix + data
                writer.write(response_length.to_bytes(4, "big"))
                writer.write(response_data)
                await writer.drain()

        except asyncio.IncompleteReadError:
            # Client disconnected
            pass
        except Exception as e:
            # Log error but don't crash server
            print(f"Error handling client: {e}")
        finally:
            writer.close()
            await writer.wait_closed()
