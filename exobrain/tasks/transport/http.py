"""HTTP transport implementation for all platforms."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

try:
    import aiohttp
    from aiohttp import web

    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False
    aiohttp = None  # type: ignore
    web = None  # type: ignore

from .base import Transport, TransportServer


class HTTPTransport(Transport):
    """Client-side HTTP transport."""

    def __init__(self, host: str = "localhost", port: int = 8765, auth_token: Optional[str] = None):
        """
        Initialize HTTP transport.

        Args:
            host: Server host
            port: Server port
            auth_token: Optional authentication token
        """
        if not AIOHTTP_AVAILABLE:
            raise ImportError(
                "aiohttp is required for HTTP transport. " "Install it with: pip install aiohttp"
            )

        self.host = host
        self.port = port
        self.auth_token = auth_token
        self.base_url = f"http://{host}:{port}"
        self._session: Optional[aiohttp.ClientSession] = None

    async def connect(self) -> None:
        """Establish connection to the daemon."""
        self._session = aiohttp.ClientSession()

        # Test connection
        try:
            async with self._session.get(
                f"{self.base_url}/health", timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                if response.status != 200:
                    raise ConnectionError(f"Server returned status {response.status}")
        except aiohttp.ClientError as e:
            await self._session.close()
            self._session = None
            raise ConnectionError(f"Failed to connect to {self.base_url}: {e}")

    async def disconnect(self) -> None:
        """Close connection to the daemon."""
        if self._session:
            await self._session.close()
            self._session = None

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

        headers = {"Content-Type": "application/json"}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"

        try:
            async with self._session.post(
                f"{self.base_url}/api/tasks",
                json=request,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                if response.status == 401:
                    return {"status": "error", "error": "Authentication failed"}

                response_data = await response.json()
                return response_data

        except aiohttp.ClientError as e:
            return {"status": "error", "error": f"HTTP request failed: {e}"}

    def is_connected(self) -> bool:
        """Check if transport is connected."""
        return self._session is not None and not self._session.closed


class HTTPServer(TransportServer):
    """Server-side HTTP transport."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 8765,
        enable_remote: bool = False,
        auth_token: Optional[str] = None,
    ):
        """
        Initialize HTTP server.

        Args:
            host: Server host
            port: Server port
            enable_remote: Allow remote connections (bind to 0.0.0.0)
            auth_token: Optional authentication token
        """
        if not AIOHTTP_AVAILABLE:
            raise ImportError(
                "aiohttp is required for HTTP transport. " "Install it with: pip install aiohttp"
            )

        self.host = "0.0.0.0" if enable_remote else host
        self.port = port
        self.auth_token = auth_token
        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None
        self._site: Optional[web.TCPSite] = None
        self._request_handler = None

    async def start(self) -> None:
        """Start the transport server."""
        self._app = web.Application()

        # Add routes
        self._app.router.add_get("/health", self._handle_health)
        self._app.router.add_post("/api/tasks", self._handle_api_request)

        # Start server
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()

        self._site = web.TCPSite(self._runner, self.host, self.port)
        await self._site.start()

    async def stop(self) -> None:
        """Stop the transport server."""
        if self._site:
            await self._site.stop()
            self._site = None

        if self._runner:
            await self._runner.cleanup()
            self._runner = None

        self._app = None

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
        return self._site is not None

    async def _handle_health(self, request: "web.Request") -> "web.Response":
        """
        Handle health check endpoint.

        Args:
            request: HTTP request

        Returns:
            HTTP response
        """
        return web.json_response({"status": "ok"})

    async def _handle_api_request(self, request: "web.Request") -> "web.Response":
        """
        Handle API request endpoint.

        Args:
            request: HTTP request

        Returns:
            HTTP response
        """
        # Check authentication
        if self.auth_token:
            auth_header = request.headers.get("Authorization", "")
            if not auth_header.startswith("Bearer "):
                return web.json_response(
                    {"status": "error", "error": "Missing authentication"}, status=401
                )

            token = auth_header[7:]  # Remove "Bearer " prefix
            if token != self.auth_token:
                return web.json_response(
                    {"status": "error", "error": "Invalid authentication"}, status=401
                )

        # Parse request
        try:
            request_data = await request.json()
        except json.JSONDecodeError:
            return web.json_response({"status": "error", "error": "Invalid JSON"}, status=400)

        # Handle request
        response = await self.handle_request(request_data)

        return web.json_response(response)
