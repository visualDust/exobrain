"""Local model provider via OpenAI-compatible API."""

from typing import Any

from exobrain.providers.openai_provider import OpenAIProvider


class OpenAICompatibleModelProvider(OpenAIProvider):
    """Local model provider using OpenAI-compatible API (e.g., vLLM, Ollama)."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "dummy",
        default_params: dict[str, Any] | None = None,
    ):
        """Initialize local model provider.

        Args:
            base_url: API base URL (e.g., http://localhost:8000/v1)
            model: Model name
            api_key: API key (not used for local models, but required by API format)
            default_params: Default parameters for generation
        """
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            model=model,
            default_params=default_params,
        )

    async def embed(
        self,
        texts: list[str],
        **kwargs: Any,
    ) -> list[list[float]]:
        """Local models typically don't provide embeddings via the same API.

        This should be implemented separately using sentence-transformers or similar.
        """
        raise NotImplementedError(
            "Embeddings are not supported for local models via OpenAI-compatible API. "
            "Use sentence-transformers instead."
        )

    def supports_tool_calling(self) -> bool:
        """Tool calling support depends on the local model."""
        # Some models support it, default to False
        # This can be configured per model
        return True

    def get_context_window(self) -> int:
        """Get context window size for local models."""

        # Default
        return 32768
