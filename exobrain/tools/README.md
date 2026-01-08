# ExoBrain Tools Design Guide

This document explains the design standards of the ExoBrain tool system to help developers extend and add new tools.

## Core Architecture

### 1. Base Classes

**`base.py`** provides the core components of the tool system:

- **`ToolParameter`** - Tool parameter definition
- **`Tool`** - Base class for all tools (Pydantic BaseModel)
- **`ToolRegistry`** - Tool registration and management

### 2. Existing Tool Modules

```
tools/
├── base.py              # Base classes and tool registry
├── file_tools.py        # File system operations
├── shell_tools.py       # Shell command execution
├── time_tools.py        # Time-related tools
├── web_tools.py         # Web search and fetching
├── math_tools.py        # Mathematical evaluation
├── skill_tools.py       # Skill management
├── location_tools.py    # Location services
├── context7_tools.py    # Context7 integration
└── README.md            # This document
```

## Creating New Tools: Standard Process

### Step 1: Define the Tool Class

Inherit from the `Tool` base class and follow this pattern:

```python
from exobrain.tools.base import Tool, ToolParameter
from typing import Any


class MyNewTool(Tool):
    """Brief description of the tool (for Agent understanding)."""

    def __init__(self, config_param1: str, config_param2: int) -> None:
        # 1. Call super().__init__() first (Pydantic requirement)
        super().__init__(
            name="my_new_tool",  # Unique tool identifier (snake_case)
            description="Detailed description of tool functionality and use cases",  # Agent reads this
            parameters={
                "param1": ToolParameter(
                    type="string",  # string, integer, boolean, array, object
                    description="Description of parameter 1",
                    required=True,
                ),
                "param2": ToolParameter(
                    type="integer",
                    description="Description of parameter 2",
                    required=False,
                ),
            },
            requires_permission=True,  # Whether permission check is needed
            permission_scope="my_scope",  # Permission scope identifier
        )

        # 2. Set private attributes after super().__init__()
        self._config_param1 = config_param1
        self._config_param2 = config_param2

    async def execute(self, **kwargs: Any) -> str:
        """Execute tool logic.

        Args:
            **kwargs: Parameters passed from Agent (corresponding to parameters definition)

        Returns:
            str: Tool execution result (returned to Agent)
        """
        # 3. Extract parameters from kwargs
        param1 = kwargs.get("param1", "")
        param2 = kwargs.get("param2", 0)

        # 4. Parameter validation
        if not param1:
            return "Error: param1 is required"

        # 5. Execute tool logic
        try:
            result = await self._do_work(param1, param2)
            return result
        except Exception as e:
            return f"Error: {e}"

    async def _do_work(self, param1: str, param2: int) -> str:
        """Private method: actual work logic."""
        # Implement specific logic
        pass
```

### Step 2: Implement Permission Checks (Optional)

If the tool requires permission control:

```python
from pathlib import Path

class SecureFileTool(Tool):
    def __init__(self, allowed_paths: list[str], denied_paths: list[str]) -> None:
        super().__init__(
            name="secure_file_tool",
            description="A file tool with permission checks",
            parameters={...},
            requires_permission=True,
            permission_scope="file_system",
        )

        # Resolve paths to absolute paths
        self._allowed_paths = [Path(p).expanduser().resolve() for p in allowed_paths]
        self._denied_paths = [Path(p).expanduser().resolve() for p in denied_paths]

    def _check_permission(self, path: Path) -> tuple[bool, str]:
        """Check path permissions.

        Returns:
            tuple[bool, str]: (is_allowed, error_message)
        """
        path = path.expanduser().resolve()

        # Check denied list first (higher priority)
        for denied in self._denied_paths:
            try:
                path.relative_to(denied)
                return False, f"Access denied: path is in blocked directory {denied}"
            except ValueError:
                continue

        # Then check allowed list
        for allowed in self._allowed_paths:
            try:
                path.relative_to(allowed)
                return True, ""
            except ValueError:
                continue

        return False, f"Access denied: path not in allowed list"

    async def execute(self, **kwargs: Any) -> str:
        path_str = kwargs.get("path", "")
        path = Path(path_str)

        # Permission check
        allowed, message = self._check_permission(path)
        if not allowed:
            return message

        # Continue execution...
```

### Step 3: Register to CLI

Register the tool in `cli/__init__.py`:

```python
from exobrain.tools.my_new_tool import MyNewTool

def create_agent_from_config(config: Config, ...) -> tuple[Agent, Any]:
    # ...
    tool_registry = ToolRegistry()

    # Register new tool
    if config.tools.my_feature:  # Check if enabled in config
        # Get parameters from config
        my_config = config.permissions.my_scope
        param1 = my_config.get("param1", "default")
        param2 = my_config.get("param2", 42)

        # Register tool instance
        tool_registry.register(MyNewTool(param1, param2))
```

### Step 4: Add Configuration

Add configuration support in `config.py`:

```python
class ToolsConfig(BaseModel):
    # ...
    my_feature: bool = False  # Toggle for new tool

class PermissionsConfig(BaseModel):
    # ...
    my_scope: dict[str, Any] = Field(default_factory=dict)  # Permission config for new tool
```

Add configuration examples in `config.yaml` and `config.example.yaml`:

```yaml
tools:
  my_feature: true

permissions:
  my_scope:
    enabled: true
    param1: "value"
    param2: 42
```

## Design Principles

### ✅ Must Follow

1. **Call `super().__init__()` first, then set private attributes**

   ```python
   # ✅ Correct
   super().__init__(name="tool", ...)
   self._config = config

   # ❌ Wrong - Pydantic will error
   self._config = config
   super().__init__(name="tool", ...)
   ```

2. **`execute()` must use `**kwargs`\*\*

   ```python
   # ✅ Correct
   async def execute(self, **kwargs: Any) -> str:
       param = kwargs.get("param", "")

   # ❌ Wrong - Agent calls will fail
   async def execute(self, param: str) -> str:
       ...
   ```

3. **Always return strings**

   ```python
   # ✅ Correct
   return "Success: file created"
   return json.dumps({"status": "ok", "data": result})

   # ❌ Wrong - Inconsistent return types
   return True
   return {"status": "ok"}
   ```

4. **Clear error handling**

   ```python
   # ✅ Correct - Return error messages
   if not valid:
       return "Error: invalid parameter"

   try:
       result = risky_operation()
   except Exception as e:
       return f"Error: {e}"

   # ❌ Wrong - Raising exceptions interrupts Agent
   raise ValueError("Invalid parameter")
   ```

5. **Detailed, Agent-oriented descriptions**

   ```python
   # ✅ Correct - Agent understands when to use it
   description="Search the web for information. Use this when you need current data or answers requiring up-to-date knowledge."

   # ❌ Wrong - Too brief, Agent might misuse
   description="Search"
   ```

### 🎯 Best Practices

1. **Naming Conventions**

   - Tool name: `snake_case` (e.g., `web_search`, `list_directory`)
   - Class name: `PascalCase` + `Tool` suffix (e.g., `WebSearchTool`)
   - File name: `snake_case` + `_tools.py` (e.g., `web_tools.py`)

2. **Permission Priority**

   - Denied list > Allowed list
   - Check denied list first, then allowed list

3. **Output Formatting**

   ```python
   # User-friendly output
   result = [
       f"Command: {command}",
       f"Working directory: {work_dir}",
       f"Exit code: {exit_code}",
       "",
       "--- Output ---",
       output,
   ]
   return "\n".join(result)
   ```

4. **Async First**

   - Use `async/await` for all I/O operations
   - Use async libraries like `aiofiles`, `httpx.AsyncClient`

5. **Logging**

   ```python
   import logging
   logger = logging.getLogger(__name__)

   async def execute(self, **kwargs: Any) -> str:
       logger.info(f"Executing tool with params: {kwargs}")
       try:
           result = await self._do_work()
           logger.debug(f"Tool result: {result[:100]}")
           return result
       except Exception as e:
           logger.error(f"Tool error: {e}")
           return f"Error: {e}"
   ```

## Tool Type Examples

### 1. Simple Tool (No Permission Checks)

```python
class GetCurrentTimeTool(Tool):
    """Get current time - no permission needed."""

    def __init__(self) -> None:
        super().__init__(
            name="get_current_time",
            description="Get the current date and time",
            parameters={},  # No parameters
            requires_permission=False,
        )

    async def execute(self, **kwargs: Any) -> str:
        from datetime import datetime
        now = datetime.now()
        return f"Current time: {now.strftime('%Y-%m-%d %H:%M:%S')}"
```

### 2. Tool with Permission Checks

See implementation in `file_tools.py`.

### 3. Tool with Configuration Parameters

```python
class WebSearchTool(Tool):
    """Web search tool - requires configuration for max results."""

    def __init__(self, max_results: int = 5) -> None:
        super().__init__(
            name="web_search",
            description="Search the web for information",
            parameters={
                "query": ToolParameter(
                    type="string",
                    description="The search query",
                    required=True,
                ),
            },
            requires_permission=True,
        )
        self._max_results = max_results

    async def execute(self, **kwargs: Any) -> str:
        query = kwargs.get("query", "")
        results = await self._search(query, self._max_results)
        return self._format_results(results)
```

## OpenAI Function Calling Format

Tools are automatically converted to OpenAI function calling format:

```python
{
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the web for information...",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query"
                }
            },
            "required": ["query"]
        }
    }
}
```

Conversion is handled automatically by the `Tool.to_openai_format()` method, no manual implementation needed.

## Anthropic Format Support

Tools also support Anthropic's format via `Tool.to_anthropic_format()`:

```python
{
    "name": "web_search",
    "description": "Search the web for information...",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query"
            }
        },
        "required": ["query"]
    }
}
```

## Testing Recommendations

```python
# test_my_tool.py
import asyncio
from exobrain.tools.my_tool import MyNewTool


async def test_basic_functionality():
    tool = MyNewTool(param1="test", param2=42)

    # Test normal case
    result = await tool.execute(param1="value")
    assert "expected" in result

    # Test error handling
    result = await tool.execute(param1="")
    assert "Error" in result

    print("✓ All tests passed")


if __name__ == "__main__":
    asyncio.run(test_basic_functionality())
```

## Common Questions

### Q: Why must `super().__init__()` be called first?

**A:** `Tool` inherits from Pydantic `BaseModel`, which requires model initialization before setting attributes. Setting attributes first will raise `AttributeError`.

### Q: Can I raise exceptions in `execute()`?

**A:** Not recommended. You should catch exceptions and return error message strings so the Agent can see the error and try alternative approaches.

### Q: How to handle tools requiring streaming output?

**A:** Current version returns strings. Future versions may support `AsyncIterator[str]` for streaming output.

### Q: How to handle permission check failures?

**A:** Call `_check_permission()` in `execute()`. If it returns `False`, directly return the error message:

```python
allowed, message = self._check_permission(path)
if not allowed:
    return message  # Return error, don't raise exception
```

## Reference Implementations

Check existing tool implementations for inspiration:

- **Simple tools**: `time_tools.py` - `GetCurrentTimeTool`
- **Permission control**: `file_tools.py` - `ReadFileTool`, `ListDirectoryTool`
- **Complex permissions**: `shell_tools.py` - `ShellExecuteTool`
- **Network requests**: `web_tools.py` - `WebSearchTool`, `WebFetchTool`
- **Safe evaluation**: `math_tools.py` - `MathEvaluateTool`
- **External integration**: `context7_tools.py` - `Context7SearchTool`

## Permission Scope Reference

Common permission scopes used in ExoBrain:

- `file_system` - File operations (read, write, edit, search)
- `shell_execution` - Shell command execution
- `web_access` - Web search and fetching
- `location` - Location services

---

**Remember: Tools are designed to be easily understood and correctly used by Agents, not to showcase complex programming techniques. Keep it simple, clear, and reliable.**
