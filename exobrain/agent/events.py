"""Event system for agent state and execution tracking."""

import asyncio
import inspect
import logging
from collections import defaultdict
from datetime import datetime
from enum import Enum
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    """Agent event types."""

    STATE_CHANGED = "state_changed"
    TOOL_STARTED = "tool_started"
    TOOL_COMPLETED = "tool_completed"
    PERMISSION_REQUESTED = "permission_requested"
    STREAMING_CHUNK = "streaming_chunk"
    THINKING_STARTED = "thinking_started"
    THINKING_CONTENT = "thinking_content"
    ERROR_OCCURRED = "error_occurred"
    ITERATION_STARTED = "iteration_started"


class BaseEvent(BaseModel):
    """Base event class for all agent events."""

    event_type: EventType
    timestamp: datetime = Field(default_factory=datetime.now)
    agent_id: str | None = None  # Support for multi-agent scenarios


class StateChangedEvent(BaseEvent):
    """Event emitted when agent state changes."""

    event_type: EventType = EventType.STATE_CHANGED
    old_state: str  # AgentState as string to avoid circular import
    new_state: str
    iteration: int | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ToolStartedEvent(BaseEvent):
    """Event emitted when a tool starts execution."""

    event_type: EventType = EventType.TOOL_STARTED
    tool_name: str
    tool_args: dict[str, Any]
    tool_call_id: str | None = None


class ToolCompletedEvent(BaseEvent):
    """Event emitted when a tool completes execution."""

    event_type: EventType = EventType.TOOL_COMPLETED
    tool_name: str
    tool_args: dict[str, Any]
    result: str
    success: bool
    error: str | None = None
    execution_time_ms: float | None = None
    summary: str | None = None  # Brief summary for UI display


class PermissionRequestedEvent(BaseEvent):
    """Event emitted when permission is requested."""

    event_type: EventType = EventType.PERMISSION_REQUESTED
    denied_info: dict[str, Any]


class StreamingChunkEvent(BaseEvent):
    """Event emitted when streaming content chunk is received."""

    event_type: EventType = EventType.STREAMING_CHUNK
    chunk: str
    accumulated_content: str | None = None


class ThinkingContentEvent(BaseEvent):
    """Event emitted when thinking content is available."""

    event_type: EventType = EventType.THINKING_CONTENT
    content: str
    thinking_type: str = "interleaved"  # interleaved, planning, etc.


class ErrorOccurredEvent(BaseEvent):
    """Event emitted when an error occurs."""

    event_type: EventType = EventType.ERROR_OCCURRED
    error_message: str
    error_type: str | None = None
    traceback: str | None = None
    iteration: int | None = None


class IterationStartedEvent(BaseEvent):
    """Event emitted when a new iteration starts."""

    event_type: EventType = EventType.ITERATION_STARTED
    iteration: int
    max_iterations: int


EventCallback = Callable[[BaseEvent], None | Awaitable[None]]


class EventManager:
    """Event manager that supports multiple listeners for different event types."""

    def __init__(self):
        # Event type -> list of callbacks
        self._callbacks: dict[EventType, list[EventCallback]] = defaultdict(list)
        # Global callbacks (subscribe to all events)
        self._global_callbacks: list[EventCallback] = []

    def register(
        self,
        callback: EventCallback,
        event_types: list[EventType] | EventType | None = None,
    ) -> None:
        """Register an event callback.

        Args:
            callback: Callback function that receives a BaseEvent parameter
            event_types: Event types to subscribe to, None means all events
        """
        if event_types is None:
            # Subscribe to all events
            self._global_callbacks.append(callback)
        elif isinstance(event_types, EventType):
            # Subscribe to a single event type
            self._callbacks[event_types].append(callback)
        else:
            # Subscribe to multiple event types
            for event_type in event_types:
                self._callbacks[event_type].append(callback)

    def unregister(
        self,
        callback: EventCallback,
        event_types: list[EventType] | EventType | None = None,
    ) -> None:
        """Remove an event callback.

        Args:
            callback: The callback to remove
            event_types: Event types to unsubscribe from, None means global callbacks
        """
        if event_types is None:
            if callback in self._global_callbacks:
                self._global_callbacks.remove(callback)
        elif isinstance(event_types, EventType):
            if callback in self._callbacks[event_types]:
                self._callbacks[event_types].remove(callback)
        else:
            for event_type in event_types:
                if callback in self._callbacks[event_type]:
                    self._callbacks[event_type].remove(callback)

    async def emit(self, event: BaseEvent) -> None:
        """Emit an event, calling all registered callbacks.

        Args:
            event: The event object to emit
        """
        # Collect all callbacks to call
        callbacks_to_call = []

        # Add global callbacks
        callbacks_to_call.extend(self._global_callbacks)

        # Add event-type-specific callbacks
        if event.event_type in self._callbacks:
            callbacks_to_call.extend(self._callbacks[event.event_type])

        # Call all callbacks (concurrent execution)
        tasks = []
        for callback in callbacks_to_call:
            try:
                if inspect.iscoroutinefunction(callback):
                    tasks.append(callback(event))
                else:
                    result = callback(event)
                    if inspect.isawaitable(result):
                        tasks.append(result)
            except Exception as e:
                logger.error(f"Error calling event callback: {e}", exc_info=True)

        # Wait for all async callbacks to complete
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def clear(self) -> None:
        """Clear all callbacks."""
        self._callbacks.clear()
        self._global_callbacks.clear()

    def get_callback_count(self, event_type: EventType | None = None) -> int:
        """Get the number of registered callbacks (for debugging).

        Args:
            event_type: Event type to count, None means all callbacks

        Returns:
            Number of registered callbacks
        """
        if event_type is None:
            return len(self._global_callbacks) + sum(len(cbs) for cbs in self._callbacks.values())
        return len(self._callbacks.get(event_type, []))
