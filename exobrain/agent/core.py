"""Core agent implementation."""

import inspect
import json
import logging
from datetime import datetime
from enum import Enum
from typing import Any, AsyncIterator

from pydantic import BaseModel

from exobrain.providers.base import Message, ModelProvider, ModelResponse
from exobrain.tools.base import Tool, ToolRegistry

logger = logging.getLogger(__name__)


class AgentState(Enum):
    """Agent execution states."""

    IDLE = "idle"
    THINKING = "thinking"
    TOOL_CALLING = "tool_calling"
    WAITING = "waiting"
    STREAMING = "streaming"
    ERROR = "error"
    FINISHED = "finished"


class Agent(BaseModel):
    """Core agent class that orchestrates model calls and tool execution."""

    model_provider: ModelProvider
    tool_registry: ToolRegistry
    state: AgentState = AgentState.IDLE
    conversation_history: list[Message] = []
    system_prompt: str = "You are a helpful AI assistant."
    max_iterations: int = 500
    temperature: float = 0.7
    stream: bool = False
    verbose: bool = False  # Show detailed tool execution info
    permission_callback: Any = None  # Callback for permission requests
    status_callback: Any = None  # Callback for status updates
    runtime_permissions: dict = {}  # Runtime-granted permissions

    class Config:
        arbitrary_types_allowed = True

    def _should_continue_iteration(self, iteration: int) -> bool:
        """Check if we should continue iterating.

        Args:
            iteration: Current iteration number

        Returns:
            True if should continue, False otherwise
        """
        # Negative max_iterations means unlimited iterations
        if self.max_iterations < 0:
            return True
        return iteration < self.max_iterations

    def _reached_max_iterations(self, iteration: int) -> bool:
        """Check if we've reached the maximum iterations limit.

        Args:
            iteration: Current iteration number

        Returns:
            True if reached limit, False otherwise
        """
        # Negative max_iterations means unlimited iterations
        if self.max_iterations < 0:
            return False
        return iteration >= self.max_iterations

    async def process_message(self, user_message: str) -> str | AsyncIterator[str]:
        """Process a user message and return a response.

        Args:
            user_message: The user's input message

        Returns:
            The agent's response (string or async iterator for streaming)
        """
        # Add user message to history
        self.add_message(Message(role="user", content=user_message))

        # Build messages including system prompt
        messages = [Message(role="system", content=self.system_prompt)] + self.conversation_history

        # Get available tools
        available_tools = self.get_available_tools()

        # Only include tools if the model supports tool calling
        if available_tools and self.model_provider.supports_tool_calling():
            tools_spec = [tool.to_openai_format() for tool in available_tools]
        else:
            tools_spec = None
            # If tools are available but model doesn't support them, clear the list
            if available_tools and not self.model_provider.supports_tool_calling():
                logger.warning(
                    f"Tools are available but model doesn't support tool calling. Tools will not be used."
                )
                available_tools = []

        if self.stream:
            return self._process_streaming(messages, tools_spec, available_tools)
        else:
            return await self._process_non_streaming(messages, tools_spec, available_tools)

    async def _notify_status(self, state: AgentState, **details: Any) -> None:
        """Notify status callback and keep internal state in sync."""
        self.state = state

        if not self.status_callback:
            return

        try:
            callback = self.status_callback
            if inspect.iscoroutinefunction(callback):
                await callback(state, details)
            else:
                result = callback(state, details)
                if inspect.isawaitable(result):
                    await result
        except Exception:
            logger.debug("Status callback error", exc_info=True)

    def _summarize_tool_result(self, result: Any, max_lines: int = 3, max_chars: int = 200) -> str:
        """Summarize tool output for UI displays."""
        text = str(result)
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return ""

        summary_lines = lines[:max_lines]
        summary = "\n".join(summary_lines)
        if len(summary) > max_chars:
            summary = summary[: max_chars - 3] + "..."
        elif len(lines) > max_lines:
            summary += " ..."
        return summary

    async def _process_non_streaming(
        self,
        messages: list[Message],
        tools_spec: list[dict[str, Any]] | None,
        available_tools: list[Tool],
    ) -> str:
        """Process message without streaming."""
        iteration = 0
        final_response = ""
        executed_tool_cache: dict[tuple[str, str], str] = {}

        while self._should_continue_iteration(iteration):
            iteration += 1
            await self._notify_status(AgentState.THINKING, iteration=iteration)

            # Call model
            try:
                response = await self.model_provider.generate(
                    messages=messages,
                    tools=tools_spec,
                    temperature=self.temperature,
                    stream=False,
                )
            except Exception as e:
                logger.error(f"Error calling model: {e}")
                await self._notify_status(AgentState.ERROR, iteration=iteration, error=str(e))
                return f"Error: {e}"

            if not isinstance(response, ModelResponse):
                self.state = AgentState.ERROR
                return "Error: unexpected response type"

            # Check if model wants to call tools
            if response.tool_calls:
                await self._notify_status(
                    AgentState.TOOL_CALLING,
                    iteration=iteration,
                    tool_count=len(response.tool_calls),
                )

                # Add assistant message with tool calls
                self.add_message(
                    Message(
                        role="assistant",
                        content=response.content or "",
                        tool_calls=response.tool_calls,
                    )
                )
                messages.append(self.conversation_history[-1])

                # Execute tools
                for tool_call in response.tool_calls:
                    logger.debug(f"Tool call raw data: {tool_call}")

                    tool_name = tool_call.get("function", {}).get("name", "")
                    tool_args_str = tool_call.get("function", {}).get("arguments", "{}")
                    tool_id = tool_call.get("id", "")

                    logger.debug(f"Parsed tool_name: {tool_name}, tool_args_str: {tool_args_str}")

                    # Skip empty tool names
                    if not tool_name or not tool_name.strip():
                        logger.warning(f"Skipping tool call with empty name: {tool_call}")
                        continue

                    await self._notify_status(
                        AgentState.TOOL_CALLING,
                        iteration=iteration,
                        tool=tool_name,
                    )

                    try:
                        tool_args = json.loads(tool_args_str) if tool_args_str else {}
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse tool arguments: {tool_args_str}, error: {e}")
                        tool_args = {}

                    # Deduplicate identical tool calls within the same user turn
                    signature_payload = tool_args if isinstance(tool_args, dict) else {}
                    try:
                        signature = json.dumps(signature_payload, sort_keys=True)
                    except Exception:
                        signature = str(signature_payload)
                    cache_key = (tool_name, signature)

                    if cache_key in executed_tool_cache:
                        tool_result = executed_tool_cache[cache_key]
                    else:
                        # Execute tool
                        tool_result = await self._execute_tool(
                            tool_name, tool_args, available_tools
                        )
                        executed_tool_cache[cache_key] = tool_result

                    # Execute tool
                    # Add tool result message
                    tool_message = Message(
                        role="tool",
                        content=tool_result,
                        tool_call_id=tool_id,
                        name=tool_name,
                        timestamp=datetime.now().isoformat(),
                    )
                    self.add_message(tool_message)
                    messages.append(tool_message)

                # Continue loop to get model's response with tool results
                continue
            else:
                # No tool calls, this is the final response
                await self._notify_status(AgentState.FINISHED, iteration=iteration)
                final_response = response.content or ""
                self.add_message(Message(role="assistant", content=final_response))
                break

        if self._reached_max_iterations(iteration):
            logger.warning("Reached maximum iterations")
            await self._notify_status(AgentState.ERROR, iteration=iteration)
            return final_response or "Error: reached maximum iterations"

        return final_response

    async def _process_streaming(
        self,
        messages: list[Message],
        tools_spec: list[dict[str, Any]] | None,
        available_tools: list[Tool],
    ) -> AsyncIterator[str]:
        """Process message with streaming."""
        iteration = 0
        executed_tool_cache: dict[tuple[str, str], str] = {}

        while self._should_continue_iteration(iteration):
            iteration += 1
            await self._notify_status(AgentState.THINKING, iteration=iteration)

            try:
                response_stream = await self.model_provider.generate(
                    messages=messages,
                    tools=tools_spec,
                    temperature=self.temperature,
                    stream=True,
                )

                if not hasattr(response_stream, "__aiter__"):
                    yield "Error: streaming not supported"
                    return

                accumulated_content = ""
                accumulated_tool_calls: dict[int, dict[str, Any]] = {}  # index -> tool_call

                async for chunk in response_stream:
                    if isinstance(chunk, ModelResponse):
                        if chunk.content:
                            accumulated_content += chunk.content
                            await self._notify_status(
                                AgentState.STREAMING,
                                iteration=iteration,
                            )
                            yield chunk.content

                        # Merge tool calls by index
                        if chunk.tool_calls:
                            for tool_call_delta in chunk.tool_calls:
                                index = tool_call_delta.get("index", 0)

                                if index not in accumulated_tool_calls:
                                    accumulated_tool_calls[index] = {
                                        "id": tool_call_delta.get("id", ""),
                                        "type": tool_call_delta.get("type", "function"),
                                        "function": {
                                            "name": "",
                                            "arguments": "",
                                        },
                                    }

                                # Merge function data
                                if "function" in tool_call_delta:
                                    func_delta = tool_call_delta["function"]
                                    if "name" in func_delta:
                                        accumulated_tool_calls[index]["function"][
                                            "name"
                                        ] += func_delta["name"]
                                    if "arguments" in func_delta:
                                        accumulated_tool_calls[index]["function"][
                                            "arguments"
                                        ] += func_delta["arguments"]

                                # Update id if present
                                if "id" in tool_call_delta and tool_call_delta["id"]:
                                    accumulated_tool_calls[index]["id"] = tool_call_delta["id"]

                # Convert tool_calls dict to list
                tool_calls_list = (
                    list(accumulated_tool_calls.values()) if accumulated_tool_calls else []
                )

                # After streaming, handle tool calls if any
                if tool_calls_list:
                    await self._notify_status(
                        AgentState.TOOL_CALLING,
                        iteration=iteration,
                        tool_count=len(tool_calls_list),
                    )

                    # Add assistant message with tool calls to history
                    self.add_message(
                        Message(
                            role="assistant",
                            content=accumulated_content,
                            tool_calls=tool_calls_list,
                        )
                    )
                    messages.append(self.conversation_history[-1])

                    # Execute tools and add results to history
                    for tool_call in tool_calls_list:
                        tool_name = tool_call.get("function", {}).get("name", "")
                        tool_args_str = tool_call.get("function", {}).get("arguments", "{}")
                        tool_id = tool_call.get("id", "")

                        # Skip empty tool names
                        if not tool_name or not tool_name.strip():
                            logger.warning(f"Skipping tool call with empty name: {tool_call}")
                            continue

                        await self._notify_status(
                            AgentState.TOOL_CALLING,
                            iteration=iteration,
                            tool=tool_name,
                        )

                        try:
                            tool_args = json.loads(tool_args_str)
                        except json.JSONDecodeError:
                            tool_args = {}

                        signature_payload = tool_args if isinstance(tool_args, dict) else {}
                        try:
                            signature = json.dumps(signature_payload, sort_keys=True)
                        except Exception:
                            signature = str(signature_payload)
                        cache_key = (tool_name, signature)

                        if cache_key in executed_tool_cache:
                            tool_result = executed_tool_cache[cache_key]
                        else:
                            # Execute tool
                            tool_result = await self._execute_tool(
                                tool_name, tool_args, available_tools
                            )
                            executed_tool_cache[cache_key] = tool_result

                        # Execute tool
                        yield f"\n\n[Tool: {tool_name}]\n{tool_result}\n"

                        # Add tool result to conversation history
                        tool_message = Message(
                            role="tool",
                            content=tool_result,
                            tool_call_id=tool_id,
                            name=tool_name,
                            timestamp=datetime.now().isoformat(),
                        )
                        self.add_message(tool_message)
                        messages.append(tool_message)

                    # Continue loop to get model's response with tool results
                    continue

                else:
                    # No tool calls, this is the final response
                    self.add_message(Message(role="assistant", content=accumulated_content))
                    await self._notify_status(AgentState.FINISHED, iteration=iteration)
                    break

            except Exception as e:
                logger.error(f"Error in streaming: {e}")
                await self._notify_status(AgentState.ERROR, iteration=iteration, error=str(e))
                yield f"\n\nError: {e}"
                break

        if self._reached_max_iterations(iteration):
            logger.warning(
                "Reached maximum iterations in streaming mode, if you want to increase the maximum, please adjust the settings."
            )
            await self._notify_status(AgentState.ERROR, iteration=iteration)
            yield "\n\n⚠️ I reached the maximum number of iterations, if you want to increase the maximum, please adjust the settings."

    def _truncate_for_display(self, text: str, max_lines: int = 3) -> str:
        """Truncate text to maximum number of lines for display.

        Args:
            text: Text to truncate
            max_lines: Maximum number of lines to show

        Returns:
            Truncated text with ellipsis if needed
        """
        lines = text.split("\n")
        if len(lines) <= max_lines:
            return text

        truncated = "\n".join(lines[:max_lines])
        return f"{truncated}\n... ({len(lines) - max_lines} more lines)"

    async def _execute_tool(
        self,
        tool_name: str,
        tool_args: dict[str, Any],
        available_tools: list[Tool],
    ) -> str:
        """Execute a tool with permission checking.

        Args:
            tool_name: Name of the tool to execute
            tool_args: Arguments for the tool
            available_tools: List of available tools

        Returns:
            Tool execution result as string
        """
        logger.debug(f"Executing tool: {tool_name} with args: {tool_args}")

        # Find tool
        tool = None
        for t in available_tools:
            if t.name == tool_name:
                tool = t
                break

        if tool is None:
            return f"Error: tool '{tool_name}' not found"

        # Execute tool
        try:
            result = await tool.execute(**tool_args)

            # Check for access denied errors
            if "Access denied" in result or "access denied" in result.lower():
                # Parse denied info
                denied_info = self._parse_access_denied(result, tool_name, tool_args)

                # Check if we have runtime permission for this
                permission_key = self._make_permission_key(denied_info)
                if permission_key in self.runtime_permissions:
                    logger.debug(f"Runtime permission exists for {permission_key}, retrying...")
                    # Already have permission, this shouldn't happen
                    # but just in case, return the result
                    return str(result)

                # Request permission if callback is set
                if self.permission_callback:
                    logger.debug(f"Requesting permission for: {denied_info}")
                    granted = await self.permission_callback(denied_info)

                    if granted:
                        # Permission granted, apply to tool's permission list
                        logger.debug(f"Permission granted, applying to tool: {tool_name}")
                        self._apply_permission_to_tool(tool, denied_info, tool_args)

                        # Retry the tool
                        logger.debug(f"Retrying tool: {tool_name}")
                        result = await tool.execute(**tool_args)

                        # Check if retry was also denied
                        if "Access denied" in str(result) or "access denied" in str(result).lower():
                            logger.warning(f"Tool {tool_name} still denied after permission grant")
                            return f"Permission granted but tool still denied: {result}"

            # Log tool result in verbose mode
            if self.verbose:
                result_preview = self._truncate_for_display(str(result))
                logger.warning(f"[TOOL RESULT] {tool_name}:\n{result_preview}")

            summary = self._summarize_tool_result(result)
            tool_event_data = {"name": tool_name, "summary": summary, "error": False}
            logger.info(
                f"[TOOL EVENT] Sending tool_event for {tool_name}, summary length: {len(summary)}"
            )
            await self._notify_status(
                AgentState.TOOL_CALLING,
                tool=tool_name,
                tool_event=tool_event_data,
            )

            return str(result)
        except Exception as e:
            logger.error(f"Error executing tool {tool_name}: {e}")
            if self.verbose:
                logger.warning(f"[TOOL ERROR] {tool_name}: {e}")
            await self._notify_status(
                AgentState.TOOL_CALLING,
                tool=tool_name,
                tool_event={"name": tool_name, "summary": f"Error: {e}", "error": True},
            )
            return f"Error executing tool: {e}"

    def _apply_permission_to_tool(
        self,
        tool: Any,
        denied_info: dict[str, Any],
        tool_args: dict[str, Any],
    ) -> None:
        """Apply runtime permission to tool's allowed lists.

        Args:
            tool: The tool object
            denied_info: Denial information
            tool_args: Tool arguments
        """
        if denied_info["type"] == "command":
            # Add command to allowed list
            command = denied_info["resource"]
            if hasattr(tool, "_allowed_commands"):
                if command not in tool._allowed_commands:
                    tool._allowed_commands.append(command)
                    logger.debug(f"Added command to allowed list: {command}")
        elif denied_info["type"] == "directory":
            # Add directory to allowed list
            from pathlib import Path

            directory = Path(denied_info["resource"]).expanduser().resolve()
            if hasattr(tool, "_allowed_directories"):
                if directory not in tool._allowed_directories:
                    tool._allowed_directories.append(directory)
                    logger.debug(f"Added directory to allowed list: {directory}")
        elif denied_info["type"] == "path":
            # For file tools, add path to allowed list
            from pathlib import Path

            path_str = denied_info["resource"]
            path = Path(path_str).expanduser().resolve()
            if hasattr(tool, "_allowed_paths"):
                if path not in tool._allowed_paths:
                    tool._allowed_paths.append(path)
                    logger.debug(f"Added path to allowed list: {path}")
        elif denied_info["type"] == "edit":
            if hasattr(tool, "_allow_edit"):
                tool._allow_edit = True
                logger.debug("Enabled edit permission for file tool")

    def _parse_access_denied(
        self,
        error_msg: str,
        tool_name: str,
        tool_args: dict[str, Any],
    ) -> dict[str, Any]:
        """Parse access denied error to extract permission info.

        Args:
            error_msg: The error message
            tool_name: Name of the tool that was denied
            tool_args: Arguments passed to the tool

        Returns:
            Dictionary with denial information
        """
        denied_info = {
            "tool": tool_name,
            "error": error_msg,
            "args": tool_args,
            "type": "unknown",
            "resource": "",
            "action": "",
            "reason": "",
        }

        if tool_name == "shell_execute":
            # Check if it's a directory permission error first
            if "directory" in error_msg.lower():
                denied_info["type"] = "directory"
                denied_info["action"] = "Access directory for shell execution"

                # Extract directory path from error message
                # Error format: "Access denied: directory /path/to/dir is not in allowed list"
                if "directory " in error_msg:
                    # Extract the directory path between "directory " and " is not" or " matches"
                    parts = error_msg.split("directory ")
                    if len(parts) > 1:
                        dir_part = parts[1]
                        # Find the end of the path
                        if " is not" in dir_part:
                            dir_path = dir_part.split(" is not")[0].strip()
                        elif " matches" in dir_part:
                            dir_path = dir_part.split(" matches")[0].strip()
                        else:
                            dir_path = dir_part.strip()
                        denied_info["resource"] = dir_path
                    else:
                        # Fallback to working_directory from args
                        denied_info["resource"] = tool_args.get("working_directory", ".")
                else:
                    denied_info["resource"] = tool_args.get("working_directory", ".")

                if "not in allowed list" in error_msg:
                    denied_info["reason"] = "Directory not in allowed list"
                elif "matches denied pattern" in error_msg or "denied directory" in error_msg:
                    denied_info["reason"] = "Directory in denied list"
                else:
                    denied_info["reason"] = "Directory access denied"
            else:
                # Command permission error
                denied_info["type"] = "command"
                denied_info["resource"] = tool_args.get("command", "")
                denied_info["action"] = "Execute shell command"

                if "not in allowed list" in error_msg:
                    denied_info["reason"] = "Command not in allowed list"
                elif "matches denied pattern" in error_msg:
                    denied_info["reason"] = "Command matches denied pattern"
                else:
                    denied_info["reason"] = "Command access denied"

        elif tool_name in [
            "read_file",
            "write_file",
            "list_directory",
            "search_files",
        ]:
            denied_info["resource"] = tool_args.get("path", "")
            if "editing not allowed" in error_msg.lower():
                denied_info["type"] = "edit"
                denied_info["action"] = "Enable file edits"
                denied_info["reason"] = "Edit permission disabled"
            else:
                denied_info["type"] = "path"
                denied_info["action"] = tool_name.replace("_", " ").title()

            if "not in any allowed directory" in error_msg:
                denied_info["reason"] = "Path not in allowed list"
            elif "blocked directory" in error_msg:
                denied_info["reason"] = "Path in blocked list"

        return denied_info

    def _make_permission_key(self, denied_info: dict[str, Any]) -> str:
        """Create a unique key for a permission.

        Args:
            denied_info: Denial information

        Returns:
            Permission key string
        """
        return f"{denied_info['type']}:{denied_info['resource']}"

    def add_message(self, message: Message) -> None:
        """Add a message to conversation history."""
        self.conversation_history.append(message)

    def get_available_tools(self) -> list[Tool]:
        """Get tools available to the agent."""
        return self.tool_registry.list_tools()

    def clear_history(self) -> None:
        """Clear conversation history."""
        self.conversation_history.clear()
        self.state = AgentState.IDLE

    def get_history_text(self) -> str:
        """Get conversation history as formatted text."""
        lines = []
        for msg in self.conversation_history:
            if msg.role == "system":
                continue
            role = msg.role.upper()
            content = msg.content if isinstance(msg.content, str) else ""
            lines.append(f"{role}: {content}")
        return "\n\n".join(lines)
