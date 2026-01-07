"""Base classes and interfaces for MCP-style clients."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class MCPClient(ABC):
    """Abstract MCP client interface."""

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection if needed."""

    @abstractmethod
    async def list_tools(self) -> list[dict[str, Any]]:
        """Return available tools metadata."""

    @abstractmethod
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Invoke a tool by name."""

    async def list_resources(self) -> list[dict[str, Any]]:
        """Optional: list remote resources."""
        return []

    async def read_resource(self, uri: str) -> Any:
        """Optional: read a remote resource."""
        raise NotImplementedError("Resource reading not supported by this client.")
