"""Tests for handler integration with ConversationManager."""

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from exobrain.memory.conversations import ConversationManager
from exobrain.memory.handlers.truncating import TruncatingMessageHandler
from exobrain.providers.base import Message, ModelProvider


class MockModelProvider(ModelProvider):
    """Mock model provider for testing."""

    def __init__(self, context_window: int = 128000):
        self._context_window = context_window

    def get_context_window(self) -> int:
        return self._context_window

    def count_tokens(self, text: str) -> int:
        return len(text) // 4

    def supports_tool_calling(self) -> bool:
        return True

    async def generate(self, *args, **kwargs):
        pass

    async def embed(self, texts: list[str], **kwargs):
        return [[0.0] * 768 for _ in texts]


class TestConversationManagerWithHandler:
    """Tests for ConversationManager integration with message handlers."""

    def test_conversation_manager_default_handler(self):
        """Test that ConversationManager creates default handler."""
        with TemporaryDirectory() as tmpdir:
            provider = MockModelProvider()
            manager = ConversationManager(
                storage_path=Path(tmpdir),
                model_provider=provider,
            )

            # Should have created a default TruncatingMessageHandler
            assert manager.message_handler is not None
            assert isinstance(manager.message_handler, TruncatingMessageHandler)

    def test_conversation_manager_custom_handler(self):
        """Test providing custom handler to ConversationManager."""
        with TemporaryDirectory() as tmpdir:
            provider = MockModelProvider()
            custom_handler = TruncatingMessageHandler(
                model_provider=provider,
                load_percentage=0.7,
            )
            manager = ConversationManager(
                storage_path=Path(tmpdir),
                model_provider=provider,
                message_handler=custom_handler,
            )

            # Should use provided handler
            assert manager.message_handler is custom_handler
            assert manager.message_handler.load_percentage == 0.7

    def test_load_session_with_handler(self):
        """Test loading session uses handler."""
        with TemporaryDirectory() as tmpdir:
            provider = MockModelProvider(context_window=10000)
            handler = TruncatingMessageHandler(
                model_provider=provider,
                load_percentage=0.5,
                reserved_output_tokens=1000,
            )
            manager = ConversationManager(
                storage_path=Path(tmpdir),
                model_provider=provider,
                message_handler=handler,
            )

            # Create session and save messages
            session_id = manager.create_session(model="test-model")

            # Budget: (10000 - ~7 - 1000) * 0.5 = ~4496 tokens
            # Create messages that exceed budget
            # Each "X" * 1000 = 1000 chars = 250 tokens
            messages = [
                Message(role="user", content="A" * 8000),  # 2000 tokens
                Message(role="assistant", content="B" * 8000),  # 2000 tokens
                Message(role="user", content="C" * 4000),  # 1000 tokens
                Message(role="assistant", content="D" * 4000),  # 1000 tokens
            ]

            for msg in messages:
                manager.save_message(session_id, msg)

            # Load session with system prompt
            result = manager.load_session(
                session_id=session_id,
                system_prompt="You are a helpful assistant.",
            )

            # Should have truncated old messages
            # Budget is ~4496, so we can fit 1000 + 1000 + 2000 = 4000 tokens (3 messages)
            # The fourth message (2000 tokens) would exceed budget
            assert result["stats"]["truncated_count"] > 0
            assert result["stats"]["loaded_count"] < result["stats"]["total_count"]

    def test_load_session_without_constraints(self):
        """Test loading session without constraints loads all messages."""
        with TemporaryDirectory() as tmpdir:
            provider = MockModelProvider()
            manager = ConversationManager(
                storage_path=Path(tmpdir),
                model_provider=provider,
            )

            # Create session and save messages
            session_id = manager.create_session(model="test-model")

            messages = [
                Message(role="user", content="Message 1"),
                Message(role="assistant", content="Response 1"),
                Message(role="user", content="Message 2"),
            ]

            for msg in messages:
                manager.save_message(session_id, msg)

            # Load without constraints
            result = manager.load_session(session_id=session_id)

            # Should load all messages
            assert result["stats"]["loaded_count"] == 3
            assert result["stats"]["truncated_count"] == 0
            assert result["stats"]["total_count"] == 3

    def test_deprecated_load_within_budget(self):
        """Test that deprecated _load_within_budget still works."""
        with TemporaryDirectory() as tmpdir:
            provider = MockModelProvider()
            manager = ConversationManager(
                storage_path=Path(tmpdir),
                model_provider=provider,
            )

            messages = [
                {"role": "user", "content": "Hello", "tokens": 10},
                {"role": "assistant", "content": "Hi", "tokens": 10},
            ]

            # Should emit deprecation warning
            with pytest.warns(DeprecationWarning):
                result = manager._load_within_budget(messages, token_budget=1000)

            # Should still work
            assert result["loaded_count"] == 2
            assert "messages" in result
