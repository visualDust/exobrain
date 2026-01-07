"""Google Gemini model provider implementation."""

import json
from typing import Any, AsyncIterator

import httpx

from exobrain.providers.base import Message, ModelProvider, ModelResponse


def _simplify_usage(usage_metadata: dict[str, Any] | None) -> dict[str, int] | None:
    """Simplify Gemini usage metadata to match ModelResponse format."""
    if not usage_metadata:
        return None

    # Extract only integer fields
    simplified = {}
    for key, value in usage_metadata.items():
        if isinstance(value, int):
            simplified[key] = value

    return simplified if simplified else None


class GeminiProvider(ModelProvider):
    """Google Gemini API provider."""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-flash",
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        default_params: dict[str, Any] | None = None,
    ):
        """Initialize Gemini provider.

        Args:
            api_key: Google API key
            model: Model name
            base_url: API base URL
            default_params: Default parameters for generation
        """
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
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
        """Generate a response from Gemini."""
        # Convert messages to Gemini format
        gemini_contents = self._messages_to_gemini(messages)

        # Build request payload
        generation_config = {
            "temperature": temperature,
            **self.default_params,
            **kwargs,
        }

        # Convert snake_case parameters to camelCase for Gemini API
        if "max_tokens" in generation_config:
            generation_config["maxOutputTokens"] = generation_config.pop("max_tokens")

        if max_tokens:
            generation_config["maxOutputTokens"] = max_tokens

        payload: dict[str, Any] = {
            "contents": gemini_contents,
            "generationConfig": generation_config,
        }

        # Gemini has a different tool format
        if tools:
            payload["tools"] = self._convert_tools_to_gemini(tools)

        # Build URL
        method = "streamGenerateContent" if stream else "generateContent"
        url = f"{self.base_url}/models/{self.model}:{method}?key={self.api_key}"

        if stream:
            # For streaming, return the async generator
            return self._stream_response(url, payload)
        else:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, json=payload)
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as e:
                    # Log the error response body for debugging
                    import logging

                    logger = logging.getLogger(__name__)
                    logger.error(f"Gemini API error: {e.response.text}")
                    raise
                return self._parse_response(response.json())

    async def _stream_response(
        self,
        url: str,
        payload: dict[str, Any],
    ) -> AsyncIterator[ModelResponse]:
        """Stream responses from Gemini."""
        import logging

        logger = logging.getLogger(__name__)

        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream("POST", url, json=payload) as response:
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as e:
                    # Log the error response body for debugging
                    error_body = await response.aread()
                    logger.error(f"Gemini API streaming error: {error_body.decode()}")
                    raise

                # Gemini streaming API returns a JSON array: [{chunk1},{chunk2},...]
                # Each chunk contains delta (incremental) text, not cumulative
                buffer = ""
                in_array = False
                brace_count = 0

                async for chunk_bytes in response.aiter_bytes():
                    chunk_text = chunk_bytes.decode("utf-8", errors="ignore")
                    buffer += chunk_text

                    # Process the buffer to extract complete JSON objects
                    continue_processing = True
                    while continue_processing and buffer:
                        # Skip array opening bracket and whitespace
                        if not in_array:
                            idx = buffer.find("[")
                            if idx >= 0:
                                buffer = buffer[idx + 1 :]
                                in_array = True
                            else:
                                break

                        # Find complete JSON objects
                        if in_array:
                            # Skip commas and whitespace
                            buffer = buffer.lstrip(", \n\r\t")

                            # Check for array closing bracket
                            if buffer.startswith("]"):
                                # Don't break out of the async for loop - just stop processing this buffer
                                buffer = buffer[1:]
                                in_array = False
                                continue_processing = False
                                continue

                            if not buffer or buffer[0] != "{":
                                break

                            # Count braces to find complete JSON object
                            brace_count = 0
                            i = 0
                            found_complete_json = False
                            for i, char in enumerate(buffer):
                                if char == "{":
                                    brace_count += 1
                                elif char == "}":
                                    brace_count -= 1
                                    if brace_count == 0:
                                        # Found a complete JSON object
                                        json_str = buffer[: i + 1]
                                        buffer = buffer[i + 1 :]
                                        found_complete_json = True

                                        try:
                                            chunk_data = json.loads(json_str)
                                            if (
                                                "candidates" in chunk_data
                                                and len(chunk_data["candidates"]) > 0
                                            ):
                                                candidate = chunk_data["candidates"][0]
                                                content_part = candidate.get("content", {})
                                                parts = content_part.get("parts", [])

                                                # Check for text content
                                                if parts and "text" in parts[0]:
                                                    # Gemini returns delta text in each chunk, not cumulative
                                                    delta_text = parts[0]["text"]
                                                    if delta_text:
                                                        yield ModelResponse(
                                                            content=delta_text,
                                                            tool_calls=None,
                                                            finish_reason=candidate.get(
                                                                "finishReason"
                                                            ),
                                                            usage=_simplify_usage(
                                                                chunk_data.get("usageMetadata")
                                                            ),
                                                        )

                                                # Check for function calls (tool calls)
                                                elif parts and "functionCall" in parts[0]:
                                                    # Convert Gemini functionCall to OpenAI tool_calls format
                                                    function_call = parts[0]["functionCall"]
                                                    tool_calls = [
                                                        {
                                                            "id": f"call_{hash(json.dumps(function_call, sort_keys=True))}",
                                                            "type": "function",
                                                            "function": {
                                                                "name": function_call.get(
                                                                    "name", ""
                                                                ),
                                                                "arguments": json.dumps(
                                                                    function_call.get("args", {})
                                                                ),
                                                            },
                                                        }
                                                    ]
                                                    yield ModelResponse(
                                                        content="",
                                                        tool_calls=tool_calls,
                                                        finish_reason=candidate.get("finishReason"),
                                                        usage=_simplify_usage(
                                                            chunk_data.get("usageMetadata")
                                                        ),
                                                    )
                                        except json.JSONDecodeError as e:
                                            # Incomplete JSON, continue accumulating
                                            logger.debug(
                                                f"JSON decode error: {e}, will retry with more data"
                                            )
                                            buffer = json_str + buffer
                                        break

                            if not found_complete_json:
                                # No complete JSON object yet, wait for more data
                                break

    def _parse_response(self, response_data: dict[str, Any]) -> ModelResponse:
        """Parse Gemini response."""
        if "candidates" not in response_data or not response_data["candidates"]:
            return ModelResponse(content="", tool_calls=None, finish_reason="error")

        candidate = response_data["candidates"][0]
        content_part = candidate.get("content", {})
        parts = content_part.get("parts", [])

        content = ""
        tool_calls = None

        if parts:
            # Check for text content
            if "text" in parts[0]:
                content = parts[0].get("text", "")

            # Check for function calls (tool calls)
            elif "functionCall" in parts[0]:
                function_call = parts[0]["functionCall"]
                tool_calls = [
                    {
                        "id": f"call_{hash(json.dumps(function_call, sort_keys=True))}",
                        "type": "function",
                        "function": {
                            "name": function_call.get("name", ""),
                            "arguments": json.dumps(function_call.get("args", {})),
                        },
                    }
                ]

        return ModelResponse(
            content=content,
            tool_calls=tool_calls,
            finish_reason=candidate.get("finishReason"),
            usage=_simplify_usage(response_data.get("usageMetadata")),
        )

    def _messages_to_gemini(self, messages: list[Message]) -> list[dict[str, Any]]:
        """Convert messages to Gemini format."""
        gemini_contents = []

        for msg in messages:
            if msg.role == "system":
                # Gemini doesn't have a system role, prepend to first user message
                continue

            # Handle tool response messages
            if msg.role == "tool":
                # Gemini expects functionResponse format for tool results
                # Tool responses should be in "model" role with functionResponse
                parts = []
                if msg.name:  # Tool name from the message
                    try:
                        # Parse tool result as response
                        response_data = (
                            {"result": msg.content} if isinstance(msg.content, str) else msg.content
                        )
                        parts.append(
                            {
                                "functionResponse": {
                                    "name": msg.name,
                                    "response": response_data,
                                }
                            }
                        )
                    except Exception:
                        # Fallback to text if parsing fails
                        parts.append({"text": str(msg.content)})
                else:
                    parts.append({"text": str(msg.content)})

                content: dict[str, Any] = {
                    "role": "function",  # Gemini uses "function" role for tool responses
                    "parts": parts,
                }
                gemini_contents.append(content)
                continue

            # Handle assistant messages with tool calls
            if msg.role == "assistant" and msg.tool_calls:
                # Convert OpenAI tool_calls to Gemini functionCall format
                parts = []
                for tool_call in msg.tool_calls:
                    if tool_call.get("type") == "function":
                        func = tool_call.get("function", {})
                        try:
                            args = json.loads(func.get("arguments", "{}"))
                        except json.JSONDecodeError:
                            args = {}

                        parts.append(
                            {
                                "functionCall": {
                                    "name": func.get("name", ""),
                                    "args": args,
                                }
                            }
                        )

                # Add text content if present
                if msg.content:
                    parts.insert(0, {"text": msg.content})

                content: dict[str, Any] = {
                    "role": "model",
                    "parts": parts,
                }
                gemini_contents.append(content)
                continue

            # Handle regular messages
            role = "user" if msg.role in ["user", "system"] else "model"

            content = {
                "role": role,
                "parts": [{"text": msg.content if isinstance(msg.content, str) else ""}],
            }

            gemini_contents.append(content)

        return gemini_contents

    def _convert_tools_to_gemini(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert OpenAI-style tools to Gemini format."""
        # Gemini has function declarations
        function_declarations = []

        for tool in tools:
            if tool.get("type") == "function":
                func = tool.get("function", {})
                function_declarations.append(
                    {
                        "name": func.get("name"),
                        "description": func.get("description"),
                        "parameters": func.get("parameters"),
                    }
                )

        return [{"functionDeclarations": function_declarations}] if function_declarations else []

    async def embed(
        self,
        texts: list[str],
        **kwargs: Any,
    ) -> list[list[float]]:
        """Generate embeddings using Gemini.

        Note: Gemini uses a different model for embeddings.
        """
        url = f"{self.base_url}/models/embedding-001:embedContent?key={self.api_key}"

        embeddings = []
        async with httpx.AsyncClient(timeout=60.0) as client:
            for text in texts:
                payload = {
                    "model": "models/embedding-001",
                    "content": {"parts": [{"text": text}]},
                }

                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()

                embedding = data.get("embedding", {}).get("values", [])
                embeddings.append(embedding)

        return embeddings

    def supports_tool_calling(self) -> bool:
        """Gemini supports function calling."""
        return True

    def get_context_window(self) -> int:
        """Get context window size."""
        context_windows = {
            "gemini-2.5-pro": 1048576,
            "gemini-2.5-flash": 1048576,
            "gemini-2.0-flash": 1048576,
            "gemini-2.0-flash-exp": 1048576,
        }

        for model_name, window_size in context_windows.items():
            if model_name in self.model:
                return window_size

        return 1048576

    def count_tokens(self, text: str) -> int:
        """Count tokens in text.

        Note: This is an approximation. Gemini has a countTokens API
        that should be used for accurate counting.
        """
        # Rough approximation: 1 token ≈ 4 characters
        return len(text) // 4
