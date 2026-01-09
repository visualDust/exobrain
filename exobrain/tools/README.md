# ExoBrain Tools System

This document describes the ExoBrain tools system and how to add new tools.

## Overview

ExoBrain uses an automatic tool registration system where tools register themselves via decorators and are instantiated based on configuration. The system consists of:

- **ToolRegistry**: A registry that manages both tool classes (global) and tool instances (per-agent)
- **ConfigurableTool**: Base class for tools that can be auto-registered and configured
- **@register_tool**: Decorator for automatic tool discovery
- **from_config()**: Class method for configuration-based instantiation

## Tool Initialization Flow

1. **Registration Phase** (at import time):

   - Tool modules are imported via `import exobrain.tools`
   - `@register_tool` decorator registers each tool class to `ToolRegistry._tool_classes`
   - Tools are grouped by `config_key` (e.g., "file_system", "web_access", "skills")

2. **Instantiation Phase** (at agent creation):

   - `auto_register_tools()` is called with the config
   - For each registered tool class, `from_config(config)` is called
   - Tool decides whether to enable itself based on config
   - If enabled, tool instance is registered to `ToolRegistry._tool_instances`

3. **Agent Usage**:
   - Agent receives the ToolRegistry and can access all registered tools
   - Tools can execute with permission checks if required

## Creating a New Tool

### Step 1: Define Tool Class

Create a new tool class that inherits from `ConfigurableTool`:

```python
from typing import TYPE_CHECKING, Any, ClassVar
from exobrain.tools.base import ConfigurableTool, ToolParameter, register_tool

if TYPE_CHECKING:
    from exobrain.config import Config

@register_tool
class MyTool(ConfigurableTool):
    """My custom tool description."""

    # Configuration key - used to group tools and check config
    # Use "" for always-enabled tools
    config_key: ClassVar[str] = "my_category"

    def __init__(self, param1: str, param2: int = 10):
        """Initialize the tool with configuration parameters."""
        super().__init__(
            name="my_tool",
            description="What this tool does",
            parameters={
                "input": ToolParameter(
                    type="string",
                    description="Input parameter description",
                    required=True,
                ),
            },
            requires_permission=True,  # Set to True if tool needs permission
            permission_scope="my_category",  # Permission scope name
        )
        self._param1 = param1
        self._param2 = param2
```

### Step 2: Implement execute() Method

```python
    async def execute(self, **kwargs: Any) -> str:
        """Execute the tool.

        Args:
            **kwargs: Tool parameters

        Returns:
            Tool execution result as string
        """
        input_value = kwargs.get("input", "")

        # Tool logic here
        result = f"Processed: {input_value} with {self._param1}"

        return result
```

### Step 3: Implement from_config() Class Method

```python
    @classmethod
    def from_config(cls, config: "Config") -> "MyTool | None":
        """Create tool instance from configuration.

        Args:
            config: Global application configuration

        Returns:
            Tool instance if enabled in config, None otherwise
        """
        # Check if this tool category is enabled
        if not getattr(config.tools, "my_category", False):
            return None

        # Get tool-specific configuration
        tool_config = config.permissions.my_category
        if not tool_config.get("enabled", False):
            return None

        # Extract parameters from config
        param1 = tool_config.get("param1", "default")
        param2 = tool_config.get("param2", 10)

        return cls(param1=param1, param2=param2)
```

## Existing Tools

Tools are organized by `config_key` in the configuration file

### Always-Enabled Tools (`config_key = ""`)

- **MathEvaluateTool**: Evaluate mathematical expressions
- **GetOSInfoTool**: Get operating system information
- **GetUserInfoTool**: Get current user information

These tools don't require configuration and are always available.

### File System Tools (`config_key = "file_system"`)

- **ReadFileTool**: Read file contents
- **WriteFileTool**: Write content to files
- **ListDirectoryTool**: List directory contents
- **SearchFilesTool**: Search for files by pattern
- **EditFileTool**: Edit file contents
- **GrepFileTool**: Search file contents with regex

### Web Access Tools (`config_key = "web_access"`)

- **WebSearchTool**: Search the web using DuckDuckGo
- **WebFetchTool**: Fetch and extract text from web pages
- **Context7SearchTool**: Search using Context7 API

### Shell Execution Tools (`config_key = "shell_execution"`)

- **ShellExecuteTool**: Execute shell commands with permission checks

### Time Management Tools (`config_key = "time_management"`)

- **GetCurrentTimeTool**: Get current date and time
- **GetWorldTimeTool**: Get time for specific timezone

### Location Tools (`config_key = "location"`)

- **GetUserLocationTool**: Get user's location information

### Skill Tools (`config_key = "skills"`)

- **GetSkillTool**: Retrieve detailed skill instructions
- **SearchSkillsTool**: Search for skills by query
- **ListSkillsTool**: List all available skills

Skill tools are special - they initialize their own `SkillsManager` in `from_config()`.

## Tool Configuration

Tools read their configuration from two places:

1. **`config.tools.<config_key>`**: Boolean flag to enable/disable the tool category
2. **`config.permissions.<config_key>`**: Detailed configuration including:
   - `enabled`: Whether the tool is enabled
   - Tool-specific parameters (e.g., `max_results`, `timeout`, `allowed_directories`)

Example configuration:

```yaml
tools:
  web_access: true
  file_system: true

permissions:
  web_access:
    enabled: true
    max_results: 5
    max_content_length: 10000

  file_system:
    enabled: true
    allowed_directories:
      - "/home/user/projects"
```

## Permission System

Tools can require permission by setting:

```python
super().__init__(
    # ...
    requires_permission=True,
    permission_scope="my_category",
)
```

When a tool requires permission:

- The agent will prompt the user before executing
- Users can grant permission for the session or permanently
- Permission is checked against the `permission_scope`

## Best Practices

1. **Single Responsibility**: Each tool should do one thing well
2. **Clear Descriptions**: Write clear tool and parameter descriptions for the LLM
3. **Error Handling**: Return error messages as strings, don't raise exceptions
4. **Configuration**: Use `from_config()` to read configuration and decide if the tool should be enabled
5. **Type Hints**: Use proper type hints for better IDE support
6. **Permissions**: Set `requires_permission=True` for tools that access external resources
7. **Testing**: Test both enabled and disabled states in `from_config()`

## Example: Complete Tool Implementation

```python
"""Example tool for demonstration."""

from typing import TYPE_CHECKING, Any, ClassVar
from exobrain.tools.base import ConfigurableTool, ToolParameter, register_tool

if TYPE_CHECKING:
    from exobrain.config import Config


@register_tool
class ExampleTool(ConfigurableTool):
    """Example tool that demonstrates the pattern."""

    config_key: ClassVar[str] = "example"

    def __init__(self, api_key: str, timeout: int = 30):
        super().__init__(
            name="example_tool",
            description="An example tool that calls an API",
            parameters={
                "query": ToolParameter(
                    type="string",
                    description="The query to search for",
                    required=True,
                ),
                "max_results": ToolParameter(
                    type="integer",
                    description="Maximum number of results (default: 10)",
                    required=False,
                ),
            },
            requires_permission=True,
            permission_scope="example",
        )
        self._api_key = api_key
        self._timeout = timeout

    async def execute(self, query: str, max_results: int = 10, **kwargs: Any) -> str:
        """Execute the example tool."""
        if not query:
            return "Error: query parameter is required"

        # Tool implementation here
        result = f"Searched for '{query}' with max {max_results} results"
        return result

    @classmethod
    def from_config(cls, config: "Config") -> "ExampleTool | None":
        """Create tool from configuration."""
        # Check if enabled
        if not getattr(config.tools, "example", False):
            return None

        # Get permissions config
        perms = config.permissions.example
        if not perms.get("enabled", False):
            return None

        # Extract parameters
        api_key = perms.get("api_key")
        if not api_key:
            return None  # Required parameter missing

        timeout = perms.get("timeout", 30)

        return cls(api_key=api_key, timeout=timeout)
```

## File Organization

- **base.py**: Core tool system (Tool, ConfigurableTool, ToolRegistry)
- **file_tools.py**: File system operations
- **web_tools.py**: Web search and fetch
- **shell_tools.py**: Shell command execution
- **time_tools.py**: Time and timezone tools
- **math_tools.py**: Mathematical operations
- **location_tools.py**: Location information
- **skill_tools.py**: Skill management tools
- **context7_tools.py**: Context7 integration

Create new tool files following this pattern, and import them in `__init__.py`.

## Adding Your Tool to the System

1. Create your tool file in `exobrain/tools/`
2. Import it in `exobrain/tools/__init__.py`:
   ```python
   from exobrain.tools import (
       # ... existing imports
       your_tool_module,
   )
   ```
3. Add configuration to `config.yaml`:

   ```yaml
   tools:
     your_category: true

   permissions:
     your_category:
       enabled: true
       # your tool parameters
   ```

4. The tool will automatically be discovered and registered!

No manual registration in `cli/util.py` is needed - the system handles everything automatically.
