"""Base classes for transport abstraction layer."""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict


class TransportType(str, Enum):
    """Transport type enumeration."""

    UNIX = "unix"
    PIPE = "pipe"
    HTTP = "http"
    AUTO = "auto"


class Transport(ABC):
    """Abstract base class for client-side transport."""

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the daemon."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection to the daemon."""

    @abstractmethod
    async def send_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send a request to the daemon and wait for response.

        Args:
            request: Request dictionary with 'action' and 'params' keys

        Returns:
            Response dictionary with 'status', 'data', and optional 'error' keys
        """

    @abstractmethod
    def is_connected(self) -> bool:
        """Check if transport is connected."""

    async def __aenter__(self):
        """Async context manager entry."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.disconnect()


class TransportServer(ABC):
    """Abstract base class for server-side transport."""

    @abstractmethod
    async def start(self) -> None:
        """Start the transport server."""

    @abstractmethod
    async def stop(self) -> None:
        """Stop the transport server."""

    @abstractmethod
    async def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle an incoming request.

        Args:
            request: Request dictionary with 'action' and 'params' keys

        Returns:
            Response dictionary with 'status', 'data', and optional 'error' keys
        """

    @abstractmethod
    def is_running(self) -> bool:
        """Check if server is running."""

    def set_request_handler(self, handler):
        """
        Set the request handler callback.

        Args:
            handler: Async callable that takes a request dict and returns a response dict
        """
        self._request_handler = handler

    async def _handle_request_with_handler(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Internal method to handle request using the registered handler.

        Args:
            request: Request dictionary

        Returns:
            Response dictionary
        """
        if not hasattr(self, "_request_handler") or self._request_handler is None:
            return {"status": "error", "error": "No request handler registered"}

        try:
            return await self._request_handler(request)
        except Exception as e:
            return {"status": "error", "error": f"Request handler error: {str(e)}"}
