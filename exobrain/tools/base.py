"""Base classes for tools."""

from abc import abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

from pydantic import BaseModel

if TYPE_CHECKING:
    from exobrain.config import Config


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
    """Registry for managing tool classes and instances.

    This is a registry with two levels:
    1. Class-level: Global registry of tool classes (shared across all instances)
    2. Instance-level: Tool instances specific to each Agent
    """

    # Class-level: Global tool class registry (shared across all ToolRegistry instances)
    _tool_classes: ClassVar[dict[str, list[type["ConfigurableTool"]]]] = {}

    @classmethod
    def register_tool_class(cls, tool_class: type["ConfigurableTool"]) -> None:
        """Register a tool class in the global registry.

        This is called by the @register_tool decorator.

        Args:
            tool_class: Tool class to register
        """
        if not hasattr(tool_class, "config_key"):
            raise TypeError(f"{tool_class.__name__} must have a config_key attribute")

        # Use special key for always-enabled tools
        key = tool_class.config_key if tool_class.config_key else "__always_enabled__"

        # Allow multiple tools to share the same config_key
        if key not in cls._tool_classes:
            cls._tool_classes[key] = []
        cls._tool_classes[key].append(tool_class)

    @classmethod
    def get_tool_classes(cls) -> dict[str, list[type["ConfigurableTool"]]]:
        """Get all registered tool classes.

        Returns:
            Dictionary mapping config keys to lists of tool classes
        """
        return cls._tool_classes

    @classmethod
    def get_tool_classes_by_key(cls, config_key: str) -> list[type["ConfigurableTool"]]:
        """Get tool classes for a specific config key.

        Args:
            config_key: Configuration key (e.g., "file_system", "web_access")

        Returns:
            List of tool classes for the given key
        """
        return cls._tool_classes.get(config_key, [])

    # Instance-level: Tool instances specific to this registry
    def __init__(self) -> None:
        """Initialize a new tool registry instance."""
        self._tool_instances: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """Register a tool instance.

        Args:
            tool: Tool instance to register
        """
        self._tool_instances[tool.name] = tool

    def unregister(self, name: str) -> None:
        """Unregister a tool by name.

        Args:
            name: Name of the tool to unregister
        """
        if name in self._tool_instances:
            del self._tool_instances[name]

    def get(self, name: str) -> Tool | None:
        """Get a tool instance by name.

        Args:
            name: Name of the tool

        Returns:
            Tool instance or None if not found
        """
        return self._tool_instances.get(name)

    def list_tools(self) -> list[Tool]:
        """List all registered tool instances.

        Returns:
            List of all tool instances
        """
        return list(self._tool_instances.values())

    def get_tools_by_permission(self, permission_scope: str) -> list[Tool]:
        """Get tool instances that require a specific permission scope.

        Args:
            permission_scope: Permission scope to filter by

        Returns:
            List of tools with the specified permission scope
        """
        return [
            tool
            for tool in self._tool_instances.values()
            if tool.requires_permission and tool.permission_scope == permission_scope
        ]


# =============================================================================
# Tool Configuration System
# =============================================================================


@dataclass
class ToolConfig:
    """Base configuration for all tools."""

    enabled: bool = True


def register_tool(tool_class: type["ConfigurableTool"]) -> type["ConfigurableTool"]:
    """Decorator to register a tool class in the global registry.

    Tools with empty config_key are registered under "__always_enabled__".

    Args:
        tool_class: Tool class to register

    Returns:
        The same tool class (for decorator chaining)
    """
    if not issubclass(tool_class, ConfigurableTool):
        raise TypeError(f"{tool_class.__name__} must inherit from ConfigurableTool")

    # Register the tool class using ToolRegistry
    ToolRegistry.register_tool_class(tool_class)

    return tool_class


class ConfigurableTool(Tool):
    """Base class for tools that can be configured and auto-registered.

    Subclasses should:
    1. Set class attribute `config_key` (empty string for always-enabled tools)
    2. Implement `from_config()` classmethod to create instance from config
    3. Decorate class with `@register_tool`

    Example:
        @register_tool
        class MyTool(ConfigurableTool):
            config_key: ClassVar[str] = "my_category"

            @classmethod
            def from_config(cls, config: Config) -> "MyTool | None":
                if not config.tools.my_category:
                    return None
                return cls(...)
    """

    # Subclasses should override this (use ClassVar to tell Pydantic this is a class variable)
    config_key: ClassVar[str] = ""

    @classmethod
    @abstractmethod
    def from_config(cls, config: "Config") -> "ConfigurableTool | None":
        """Create tool instance from configuration.

        Args:
            config: Global application configuration

        Returns:
            Tool instance if enabled in config, None otherwise
        """
