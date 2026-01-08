"""Base classes for model providers."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, AsyncIterator

from pydantic import BaseModel


class Message(BaseModel):
    """A message in the conversation."""

    role: str  # system, user, assistant, tool
    content: str | list[dict[str, Any]]
    name: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None
    timestamp: str | None = None  # ISO format timestamp, set when message is created


class ModelResponse(BaseModel):
    """Response from a model."""

    content: str | None = ""  # Allow None when model calls tools
    tool_calls: list[dict[str, Any]] | None = None
    finish_reason: str | None = None
    usage: dict[str, int] | None = None


class ModelProvider(ABC):
    """Base class for all model providers."""

    @abstractmethod
    async def generate(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> ModelResponse | AsyncIterator[ModelResponse]:
        """Generate a response from the model.

        Args:
            messages: List of messages in the conversation
            tools: Optional list of tools available to the model
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            stream: Whether to stream the response
            **kwargs: Additional provider-specific parameters

        Returns:
            ModelResponse or async iterator of ModelResponse chunks
        """
        pass

    @abstractmethod
    async def embed(
        self,
        texts: list[str],
        **kwargs: Any,
    ) -> list[list[float]]:
        """Generate embeddings for texts.

        Args:
            texts: List of texts to embed
            **kwargs: Additional provider-specific parameters

        Returns:
            List of embedding vectors
        """
        pass

    @abstractmethod
    def supports_tool_calling(self) -> bool:
        """Check if the provider supports tool calling."""
        pass

    @abstractmethod
    def get_context_window(self) -> int:
        """Get the context window size in tokens."""
        pass

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """Count tokens in a text string."""
        pass
