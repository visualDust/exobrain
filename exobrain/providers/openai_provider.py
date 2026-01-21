"""OpenAI model provider implementation."""

import json
from typing import Any, AsyncIterator

import httpx

from exobrain.providers.base import Message, ModelProvider, ModelResponse


class OpenAIProvider(ModelProvider):
    """OpenAI API provider."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-4o-mini",
        default_params: dict[str, Any] | None = None,
    ):
        """Initialize OpenAI provider.

        Args:
            api_key: OpenAI API key
            base_url: API base URL
            model: Model name
            default_params: Default parameters for generation
        """
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.default_params = default_params or {}

    async def generate(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> ModelResponse | AsyncIterator[ModelResponse]:
        """Generate a response from OpenAI."""
        # Convert messages to OpenAI format
        openai_messages = [self._message_to_openai(msg) for msg in messages]

        # Check if this is a GPT-5 model (requires different parameters)
        is_gpt5 = self.model.startswith("gpt-5")

        # Build request payload
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": openai_messages,
            "stream": stream,
            **self.default_params,
            **kwargs,
        }

        # GPT-5 series has specific parameter requirements
        if is_gpt5:
            # GPT-5 only supports temperature=1 (default), remove if present
            payload.pop("temperature", None)
        else:
            # Other models: use provided temperature
            payload["temperature"] = temperature

        # Handle max_tokens parameter based on model version
        # GPT-5 series uses max_completion_tokens instead of max_tokens
        tokens_value = max_tokens or self.default_params.get("max_tokens")

        if tokens_value:
            # Remove max_tokens if it exists (from default_params)
            payload.pop("max_tokens", None)

            # Clamp to model's maximum output tokens
            max_allowed = self.get_max_output_tokens()
            if tokens_value > max_allowed:
                tokens_value = max_allowed

            # Add the correct parameter based on model version
            if is_gpt5:
                payload["max_completion_tokens"] = tokens_value
            else:
                payload["max_tokens"] = tokens_value

        if tools:
            payload["tools"] = tools

        # Make API request
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        if stream:
            # For streaming, return the async generator
            return self._stream_response(headers, payload)
        else:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                return self._parse_response(response.json())

    async def _stream_response(
        self,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> AsyncIterator[ModelResponse]:
        """Stream responses from OpenAI."""
        import logging

        logger = logging.getLogger(__name__)

        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                ) as response:
                    response.raise_for_status()

                    async for line in response.aiter_lines():
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]":
                                break

                            try:
                                chunk = json.loads(data)
                                if "choices" in chunk and len(chunk["choices"]) > 0:
                                    delta = chunk["choices"][0].get("delta", {})
                                    content = delta.get("content", "")
                                    tool_calls = delta.get("tool_calls", None)

                                    if content or tool_calls:
                                        yield ModelResponse(
                                            content=content,
                                            tool_calls=tool_calls,
                                            finish_reason=chunk["choices"][0].get("finish_reason"),
                                            usage=chunk.get("usage"),
                                        )
                            except json.JSONDecodeError:
                                continue
            except httpx.HTTPStatusError as e:
                # Log detailed error information
                logger.error(f"HTTP {e.response.status_code} error from OpenAI API")
                logger.error(f"Request URL: {e.request.url}")
                logger.error(
                    f"Request payload (messages count): {len(payload.get('messages', []))}"
                )

                # Log each message in the payload for debugging
                for i, msg in enumerate(payload.get("messages", [])):
                    logger.error(
                        f"Message {i}: role={msg.get('role')}, "
                        f"content={repr(msg.get('content'))[:100]}, "
                        f"has_tool_calls={bool(msg.get('tool_calls'))}, "
                        f"has_tool_call_id={bool(msg.get('tool_call_id'))}"
                    )

                # Try to get error details from response
                try:
                    error_body = e.response.json()
                    logger.error(f"API error response: {json.dumps(error_body, indent=2)}")
                except:
                    logger.error(f"API error response (raw): {e.response.text}")

                raise

    def _parse_response(self, response_data: dict[str, Any]) -> ModelResponse:
        """Parse OpenAI response."""
        choice = response_data["choices"][0]
        message = choice["message"]

        # Clean usage data - remove nested dicts that Pydantic can't handle
        usage = response_data.get("usage")
        if usage:
            usage = {
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
                "total_tokens": usage.get("total_tokens", 0),
            }

        return ModelResponse(
            content=message.get("content", ""),
            tool_calls=message.get("tool_calls"),
            finish_reason=choice.get("finish_reason"),
            usage=usage,
        )

    def _message_to_openai(self, message: Message) -> dict[str, Any]:
        """Convert Message to OpenAI format."""
        # For assistant messages with tool_calls, content should be null if empty
        # OpenAI API doesn't accept empty string for assistant with tool_calls
        content = message.content
        if message.role == "assistant" and message.tool_calls and not content:
            content = None

        openai_msg: dict[str, Any] = {
            "role": message.role,
            "content": content,
        }

        if message.name:
            openai_msg["name"] = message.name

        if message.tool_calls:
            openai_msg["tool_calls"] = message.tool_calls

        if message.tool_call_id:
            openai_msg["tool_call_id"] = message.tool_call_id

        return openai_msg

    async def embed(
        self,
        texts: list[str],
        **kwargs: Any,
    ) -> list[list[float]]:
        """Generate embeddings using OpenAI."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": "text-embedding-3-small",
            "input": texts,
            **kwargs,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.base_url}/embeddings",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

            return [item["embedding"] for item in data["data"]]

    def supports_tool_calling(self) -> bool:
        """OpenAI supports tool calling."""
        return True

    def get_context_window(self) -> int:
        """Get context window size (total tokens: input + output)."""

        # Context windows for common models (updated ~2026)
        # Order matters: more specific first
        context_windows = {
            # GPT-5 family
            "gpt-5-pro": 400_000,
            "gpt-5": 400_000,
            "gpt-5-mini": 128_000,
            # GPT-4.1 family
            "gpt-4.1": 1_000_000,
            # GPT-4o family
            "gpt-4o-mini": 128_000,
            "gpt-4o": 128_000,
            # GPT-4 legacy
            "gpt-4-turbo": 128_000,
            "gpt-4-32k": 32_768,
            "gpt-4": 8_192,
            # GPT-3.5 legacy
            "gpt-3.5-turbo": 16_385,
        }

        model = self.model.lower()
        for name, window in context_windows.items():
            if name in model:
                return window

        # Conservative fallback
        return 8_192

    def get_max_output_tokens(self) -> int:
        """Get maximum output tokens allowed by the model."""

        # Max output tokens (updated ~2026)
        # Order matters: more specific first
        max_output_tokens = {
            # GPT-5 family
            "gpt-5-pro": 128_000,
            "gpt-5": 128_000,
            "gpt-5-mini": 16_384,
            # GPT-4.1 family
            "gpt-4.1": 32_768,
            # GPT-4o family
            "gpt-4o-mini": 16_384,
            "gpt-4o": 16_384,
            # GPT-4 legacy
            "gpt-4-turbo": 4_096,
            "gpt-4": 4_096,
            # GPT-3.5 legacy
            "gpt-3.5-turbo": 4_096,
        }

        model = self.model.lower()
        for name, max_tokens in max_output_tokens.items():
            if name in model:
                return max_tokens

        return 4_096

    def count_tokens(self, text: str) -> int:
        """Count tokens in text (approximate).

        Uses a simple approximation: 1 token ≈ 4 characters
        """
        return len(text) // 4
