"""Truncating message handler - drops oldest messages when exceeding budget."""

import logging
from typing import Any

from exobrain.memory.handlers.base import LoadResult, MessageHandler
from exobrain.providers.base import Message, ModelProvider

logger = logging.getLogger(__name__)


class TruncatingMessageHandler(MessageHandler):
    """Handler that drops oldest messages when exceeding context window.

    This handler implements the default behavior:
    1. Calculate token budget based on context window and constraints
    2. Load messages from most recent backwards
    3. Stop when budget would be exceeded
    4. Drop oldest messages that don't fit

    This preserves recent conversation context while staying within limits.
    """

    def __init__(
        self,
        model_provider: ModelProvider,
        context_window: int | None = None,
        load_percentage: float = 0.5,
        reserved_output_tokens: int = 4096,
    ):
        """Initialize truncating handler.

        Args:
            model_provider: Provider for token counting
            context_window: Override context window size (None = use provider's)
            load_percentage: Percentage of available context to use (0.0-1.0)
            reserved_output_tokens: Tokens to reserve for model output
        """
        super().__init__(model_provider, context_window)
        self.load_percentage = load_percentage
        self.reserved_output_tokens = reserved_output_tokens

        logger.debug(
            f"Initialized TruncatingMessageHandler: "
            f"context={self.context_window}, "
            f"load_percentage={load_percentage:.0%}, "
            f"reserved_output={reserved_output_tokens}"
        )

    def calculate_budget(
        self,
        system_prompt: str | None = None,
        reserved_output_tokens: int | None = None,
    ) -> int:
        """Calculate token budget for loading messages.

        Formula:
            budget = (context_window - system_prompt_tokens - reserved_output) * load_percentage

        Args:
            system_prompt: System prompt to account for (None = estimate)
            reserved_output_tokens: Override reserved output tokens

        Returns:
            Available token budget for history
        """
        # Calculate system prompt tokens
        if system_prompt:
            system_tokens = self.count_tokens(system_prompt)
        else:
            # Rough estimate if not provided
            system_tokens = 2000

        # Use provided or default reserved tokens
        reserved = reserved_output_tokens or self.reserved_output_tokens

        # Calculate budget
        available = self.context_window - system_tokens - reserved
        budget = int(available * self.load_percentage)

        logger.debug(
            f"Token budget calculation: "
            f"context={self.context_window}, "
            f"system={system_tokens}, "
            f"reserved={reserved}, "
            f"percentage={self.load_percentage:.0%}, "
            f"budget={budget}"
        )

        return max(budget, 0)  # Ensure non-negative

    def load_messages(
        self,
        all_messages: list[dict[str, Any]],
        system_prompt: str | None = None,
        reserved_output_tokens: int | None = None,
    ) -> LoadResult:
        """Load messages by dropping oldest when budget exceeded.

        Strategy:
        1. Calculate token budget
        2. Iterate through messages from most recent to oldest
        3. Accumulate tokens until budget would be exceeded
        4. Return loaded messages in chronological order

        Args:
            all_messages: All available messages from storage
            system_prompt: System prompt to account for in budget
            reserved_output_tokens: Tokens to reserve for output (None = use handler's default)

        Returns:
            LoadResult with loaded messages and statistics
        """
        if not all_messages:
            return LoadResult(
                messages=[],
                loaded_count=0,
                loaded_tokens=0,
                total_count=0,
                metadata={"budget": 0, "strategy": "truncate_oldest"},
            )

        # Calculate budget (use handler's default if not specified)
        if reserved_output_tokens is None:
            reserved_output_tokens = self.reserved_output_tokens
        budget = self.calculate_budget(system_prompt, reserved_output_tokens)

        # Load from most recent backwards
        messages_reversed = list(reversed(all_messages))
        loaded = []
        total_tokens = 0

        for msg in messages_reversed:
            msg_tokens = self.estimate_message_tokens(msg)

            if total_tokens + msg_tokens > budget:
                # Would exceed budget, stop loading
                logger.debug(
                    f"Stopping at message (would exceed budget): "
                    f"current={total_tokens}, msg={msg_tokens}, budget={budget}"
                )
                break

            loaded.append(msg)
            total_tokens += msg_tokens

        # Reverse back to chronological order
        loaded.reverse()

        truncated_count = len(all_messages) - len(loaded)

        result = LoadResult(
            messages=loaded,
            loaded_count=len(loaded),
            loaded_tokens=total_tokens,
            total_count=len(all_messages),
            truncated_count=truncated_count,
            metadata={
                "budget": budget,
                "strategy": "truncate_oldest",
                "load_percentage": self.load_percentage,
            },
        )

        # Log summary at INFO level
        logger.info(
            f"Loaded {len(loaded)}/{len(all_messages)} messages "
            f"({total_tokens:,} tokens), "
            f"truncated {truncated_count} older messages"
        )

        # Log detailed result at DEBUG level
        logger.debug(f"\n{result}")

        return result

    def prepare_for_api(
        self,
        messages: list[Message],
        system_prompt: str,
    ) -> list[Message]:
        """Prepare messages for API - prepend system prompt.

        For the truncating handler, this simply adds the system prompt
        at the beginning. Future handlers may do more sophisticated
        transformations here.

        Args:
            messages: Messages from conversation history
            system_prompt: System prompt to prepend

        Returns:
            [system_message] + messages
        """
        system_message = Message(role="system", content=system_prompt)
        return [system_message] + messages

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"TruncatingMessageHandler("
            f"context_window={self.context_window}, "
            f"load_percentage={self.load_percentage:.0%}, "
            f"reserved_output={self.reserved_output_tokens})"
        )
