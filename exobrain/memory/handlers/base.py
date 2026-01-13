"""Base classes for message handlers."""

import logging
from abc import ABC, abstractmethod
from typing import Any

from exobrain.providers.base import Message, ModelProvider

logger = logging.getLogger(__name__)


class LoadResult:
    """Result of loading messages from storage.

    Contains the loaded messages along with statistics about the loading process.
    """

    def __init__(
        self,
        messages: list[dict[str, Any]],
        loaded_count: int,
        loaded_tokens: int,
        total_count: int,
        truncated_count: int = 0,
        compressed_count: int = 0,
        metadata: dict[str, Any] | None = None,
    ):
        """Initialize load result.

        Args:
            messages: The loaded messages
            loaded_count: Number of messages loaded
            loaded_tokens: Total tokens in loaded messages
            total_count: Total number of messages available
            truncated_count: Number of messages dropped due to budget
            compressed_count: Number of messages compressed (future use)
            metadata: Handler-specific metadata
        """
        self.messages = messages
        self.loaded_count = loaded_count
        self.loaded_tokens = loaded_tokens
        self.total_count = total_count
        self.truncated_count = truncated_count
        self.compressed_count = compressed_count
        self.metadata = metadata or {}

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for compatibility with existing code.

        Returns:
            Dictionary representation of the load result
        """
        return {
            "messages": self.messages,
            "loaded_count": self.loaded_count,
            "loaded_tokens": self.loaded_tokens,
            "total_count": self.total_count,
            "truncated_count": self.truncated_count,
            "compressed_count": self.compressed_count,
            "metadata": self.metadata,
        }

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"LoadResult(loaded={self.loaded_count}/{self.total_count}, "
            f"tokens={self.loaded_tokens}, truncated={self.truncated_count})"
        )

    # def __repr__(self) -> str:
    #     """String representation, alias for to_debug_string."""

    #     parts = [
    #         f"LoadResult:",
    #         f"  Messages: {self.loaded_count}/{self.total_count} loaded",
    #         f"  Tokens: {self.loaded_tokens:,}",
    #         f"  Truncated: {self.truncated_count}",
    #     ]

    #     if self.compressed_count > 0:
    #         parts.append(f"  Compressed: {self.compressed_count}")

    #     if self.metadata:
    #         parts.append(f"  Metadata:")
    #         for key, value in self.metadata.items():
    #             if key == "budget":
    #                 parts.append(f"    budget: {value:,} tokens")
    #             else:
    #                 parts.append(f"    {key}: {value}")

    #     return "\n".join(parts)


class MessageHandler(ABC):
    """Abstract base class for message history handling.

    Message handlers are responsible for:
    1. Loading messages from storage within context window constraints
    2. Preparing messages for API calls (e.g., adding system prompt, compression)

    Handlers are stateless and can be reused across multiple sessions.
    """

    def __init__(
        self,
        model_provider: ModelProvider,
        context_window: int | None = None,
        **kwargs: Any,
    ):
        """Initialize message handler.

        Args:
            model_provider: Provider for token counting and context info
            context_window: Override context window size (None = use provider's)
            **kwargs: Handler-specific configuration
        """
        self.model_provider = model_provider
        self._context_window = context_window

    @property
    def context_window(self) -> int:
        """Get context window size.

        Returns:
            Context window size in tokens
        """
        if self._context_window is not None:
            return self._context_window
        return self.model_provider.get_context_window()

    @abstractmethod
    def load_messages(
        self,
        all_messages: list[dict[str, Any]],
        system_prompt: str | None = None,
        reserved_output_tokens: int = 4096,
    ) -> LoadResult:
        """Load messages within context window constraints.

        This method is called when loading a conversation session from storage.
        It should select which messages to load based on the handler's strategy
        and the available token budget.

        Args:
            all_messages: All available messages from storage
            system_prompt: System prompt to account for in budget calculation
            reserved_output_tokens: Tokens to reserve for model output

        Returns:
            LoadResult with loaded messages and statistics
        """

    @abstractmethod
    def prepare_for_api(
        self,
        messages: list[Message],
        system_prompt: str,
    ) -> list[Message]:
        """Prepare messages for API call.

        This method is called before sending messages to the model API.
        It allows handlers to do final transformations (e.g., compression,
        summarization) and add the system prompt.

        Args:
            messages: Messages from conversation history
            system_prompt: System prompt to prepend

        Returns:
            Final message list ready for API
        """

    def count_tokens(self, text: str) -> int:
        """Count tokens in text.

        Delegates to model provider by default, but can be overridden
        for more accurate counting.

        Args:
            text: Text to count tokens for

        Returns:
            Estimated token count
        """
        return self.model_provider.count_tokens(text)

    def estimate_message_tokens(self, message: dict[str, Any]) -> int:
        """Estimate tokens for a message.

        Uses stored token count if available, otherwise estimates from content.

        Args:
            message: Message dict with 'content', 'role', etc.

        Returns:
            Estimated token count
        """
        # Use stored token count if available
        if "tokens" in message and message["tokens"] > 0:
            return message["tokens"]

        # Otherwise estimate from content
        content = message.get("content", "")
        if isinstance(content, str):
            return self.count_tokens(content)
        else:
            # For structured content (multimodal), rough estimate
            return self.count_tokens(str(content))

    def __repr__(self) -> str:
        """String representation."""
        return f"{self.__class__.__name__}(context_window={self.context_window})"
