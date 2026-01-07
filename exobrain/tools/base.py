"""Base classes for tools."""

from abc import ABC, abstractmethod
from typing import Any, Callable

from pydantic import BaseModel, Field


class ToolParameter(BaseModel):
    """Definition of a tool parameter."""

    type: str
    description: str
    enum: list[str] | None = None
    required: bool = True


class Tool(BaseModel):
    """Base class for all tools."""

    name: str
    description: str
    parameters: dict[str, ToolParameter]
    requires_permission: bool = False
    permission_scope: str | None = None

    class Config:
        arbitrary_types_allowed = True
        extra = "allow"  # Allow extra attributes

    @abstractmethod
    async def execute(self, **kwargs: Any) -> Any:
        """Execute the tool with given parameters.

        Args:
            **kwargs: Tool parameters

        Returns:
            Tool execution result
        """
        pass

    def to_openai_format(self) -> dict[str, Any]:
        """Convert tool definition to OpenAI format."""
        properties = {}
        required = []

        for param_name, param in self.parameters.items():
            prop: dict[str, Any] = {
                "type": param.type,
                "description": param.description,
            }
            if param.enum:
                prop["enum"] = param.enum

            properties[param_name] = prop

            if param.required:
                required.append(param_name)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

    def to_anthropic_format(self) -> dict[str, Any]:
        """Convert tool definition to Anthropic format."""
        properties = {}
        required = []

        for param_name, param in self.parameters.items():
            prop: dict[str, Any] = {
                "type": param.type,
                "description": param.description,
            }
            if param.enum:
                prop["enum"] = param.enum

            properties[param_name] = prop

            if param.required:
                required.append(param_name)

        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }


class ToolRegistry:
    """Registry for managing tools."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        """Unregister a tool by name."""
        if name in self._tools:
            del self._tools[name]

    def get(self, name: str) -> Tool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[Tool]:
        """List all registered tools."""
        return list(self._tools.values())

    def get_tools_by_permission(self, permission_scope: str) -> list[Tool]:
        """Get tools that require a specific permission scope."""
        return [
            tool
            for tool in self._tools.values()
            if tool.requires_permission
            and tool.permission_scope == permission_scope
        ]
