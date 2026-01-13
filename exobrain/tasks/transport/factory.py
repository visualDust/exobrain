"""Transport factory with platform auto-detection."""

import platform
from typing import Any, Dict, Optional

from .base import Transport, TransportServer, TransportType
from .named_pipe import NamedPipeServer, NamedPipeTransport
from .unix_socket import UnixSocketServer, UnixSocketTransport

# Conditionally import HTTP transport
try:
    from .http import HTTPServer, HTTPTransport

    HTTP_AVAILABLE = True
except ImportError:
    HTTP_AVAILABLE = False
    HTTPTransport = None
    HTTPServer = None


class TransportFactory:
    """Factory for creating transport instances with platform auto-detection."""

    @staticmethod
    def detect_platform_transport() -> TransportType:
        """
        Detect the best transport type for the current platform.

        Returns:
            TransportType enum value
        """
        system = platform.system()

        if system in ("Linux", "Darwin"):  # Linux or macOS
            return TransportType.UNIX
        elif system == "Windows":
            return TransportType.PIPE
        else:
            # Fallback to HTTP for unknown platforms
            return TransportType.HTTP

    @staticmethod
    def create_transport(
        transport_type: TransportType = TransportType.AUTO, config: Optional[Dict[str, Any]] = None
    ) -> Transport:
        """
        Create a client-side transport instance.

        Args:
            transport_type: Type of transport to create (AUTO for auto-detection)
            config: Transport-specific configuration

        Returns:
            Transport instance

        Raises:
            ValueError: If transport type is invalid or not supported
        """
        config = config or {}

        # Auto-detect if needed
        if transport_type == TransportType.AUTO:
            transport_type = TransportFactory.detect_platform_transport()

        # Create transport based on type
        if transport_type == TransportType.UNIX:
            socket_path = config.get("socket_path", "~/.exobrain/task-daemon.sock")
            return UnixSocketTransport(socket_path)

        elif transport_type == TransportType.PIPE:
            pipe_name = config.get("pipe_name", r"\\.\pipe\exobrain-task-daemon")
            return NamedPipeTransport(pipe_name)

        elif transport_type == TransportType.HTTP:
            if not HTTP_AVAILABLE:
                raise ImportError(
                    "aiohttp is required for HTTP transport. "
                    "Install it with: pip install aiohttp"
                )
            host = config.get("host", "localhost")
            port = config.get("port", 8765)
            auth_token = config.get("auth_token")
            return HTTPTransport(host, port, auth_token)

        else:
            raise ValueError(f"Unsupported transport type: {transport_type}")

    @staticmethod
    def create_server(
        transport_type: TransportType = TransportType.AUTO, config: Optional[Dict[str, Any]] = None
    ) -> TransportServer:
        """
        Create a server-side transport instance.

        Args:
            transport_type: Type of transport to create (AUTO for auto-detection)
            config: Transport-specific configuration

        Returns:
            TransportServer instance

        Raises:
            ValueError: If transport type is invalid or not supported
        """
        config = config or {}

        # Auto-detect if needed
        if transport_type == TransportType.AUTO:
            transport_type = TransportFactory.detect_platform_transport()

        # Create server based on type
        if transport_type == TransportType.UNIX:
            socket_path = config.get("socket_path", "~/.exobrain/task-daemon.sock")
            return UnixSocketServer(socket_path)

        elif transport_type == TransportType.PIPE:
            pipe_name = config.get("pipe_name", r"\\.\pipe\exobrain-task-daemon")
            return NamedPipeServer(pipe_name)

        elif transport_type == TransportType.HTTP:
            if not HTTP_AVAILABLE:
                raise ImportError(
                    "aiohttp is required for HTTP transport. "
                    "Install it with: pip install aiohttp"
                )
            host = config.get("host", "localhost")
            port = config.get("port", 8765)
            enable_remote = config.get("enable_remote", False)
            auth_token = config.get("auth_token")
            return HTTPServer(host, port, enable_remote, auth_token)

        else:
            raise ValueError(f"Unsupported transport type: {transport_type}")

    @staticmethod
    def get_default_config(transport_type: TransportType = TransportType.AUTO) -> Dict[str, Any]:
        """
        Get default configuration for a transport type.

        Args:
            transport_type: Type of transport (AUTO for auto-detection)

        Returns:
            Default configuration dictionary
        """
        # Auto-detect if needed
        if transport_type == TransportType.AUTO:
            transport_type = TransportFactory.detect_platform_transport()

        if transport_type == TransportType.UNIX:
            return {"socket_path": "~/.exobrain/task-daemon.sock"}

        elif transport_type == TransportType.PIPE:
            return {"pipe_name": r"\\.\pipe\exobrain-task-daemon"}

        elif transport_type == TransportType.HTTP:
            return {"host": "localhost", "port": 8765, "enable_remote": False, "auth_token": None}

        else:
            raise ValueError(f"Unsupported transport type: {transport_type}")

    @staticmethod
    def is_transport_available(transport_type: TransportType) -> bool:
        """
        Check if a transport type is available on the current platform.

        Args:
            transport_type: Type of transport to check

        Returns:
            True if transport is available, False otherwise
        """
        if transport_type == TransportType.AUTO:
            return True

        if transport_type == TransportType.UNIX:
            # Unix sockets available on Linux and macOS
            return platform.system() in ("Linux", "Darwin")

        elif transport_type == TransportType.PIPE:
            # Named pipes available on Windows (requires pywin32)
            if platform.system() != "Windows":
                return False
            try:
                return True
            except ImportError:
                return False

        elif transport_type == TransportType.HTTP:
            # HTTP available on all platforms (requires aiohttp)
            return HTTP_AVAILABLE

        return False
