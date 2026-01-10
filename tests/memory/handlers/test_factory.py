"""Tests for message handler factory."""

import pytest

from exobrain.memory.handlers.factory import MessageHandlerFactory
from exobrain.memory.handlers.truncating import TruncatingMessageHandler
from exobrain.providers.base import ModelProvider


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


class TestMessageHandlerFactory:
    """Tests for MessageHandlerFactory."""

    def test_create_truncating_handler_default_config(self):
        """Test creating truncating handler with default config."""
        provider = MockModelProvider()
        handler = MessageHandlerFactory.create(
            handler_type="truncating",
            model_provider=provider,
        )

        assert isinstance(handler, TruncatingMessageHandler)
        assert handler.load_percentage == 0.5
        assert handler.reserved_output_tokens == 4096

    def test_create_truncating_handler_custom_config(self):
        """Test creating truncating handler with custom config."""
        provider = MockModelProvider()
        config = {
            "load_percentage": 0.7,
            "reserved_output_tokens": 2048,
        }
        handler = MessageHandlerFactory.create(
            handler_type="truncating",
            model_provider=provider,
            config=config,
        )

        assert isinstance(handler, TruncatingMessageHandler)
        assert handler.load_percentage == 0.7
        assert handler.reserved_output_tokens == 2048

    def test_create_truncating_handler_with_context_override(self):
        """Test creating handler with context window override."""
        provider = MockModelProvider(context_window=128000)
        config = {
            "context_window": 50000,
        }
        handler = MessageHandlerFactory.create(
            handler_type="truncating",
            model_provider=provider,
            config=config,
        )

        assert handler.context_window == 50000  # Overridden

    def test_create_sliding_window_handler_not_implemented(self):
        """Test that sliding_window handler raises NotImplementedError."""
        provider = MockModelProvider()

        with pytest.raises(NotImplementedError) as exc_info:
            MessageHandlerFactory.create(
                handler_type="sliding_window",
                model_provider=provider,
            )

        assert "SlidingWindowHandler is not yet implemented" in str(exc_info.value)
        assert "Phase 2" in str(exc_info.value)

    def test_create_compressing_handler_not_implemented(self):
        """Test that compressing handler raises NotImplementedError."""
        provider = MockModelProvider()

        with pytest.raises(NotImplementedError) as exc_info:
            MessageHandlerFactory.create(
                handler_type="compressing",
                model_provider=provider,
            )

        assert "CompressingMessageHandler is not yet implemented" in str(exc_info.value)

    def test_create_hybrid_handler_not_implemented(self):
        """Test that hybrid handler raises NotImplementedError."""
        provider = MockModelProvider()

        with pytest.raises(NotImplementedError) as exc_info:
            MessageHandlerFactory.create(
                handler_type="hybrid",
                model_provider=provider,
            )

        assert "HybridHandler is not yet implemented" in str(exc_info.value)

    def test_create_unknown_handler_type(self):
        """Test that unknown handler type raises ValueError."""
        provider = MockModelProvider()

        with pytest.raises(ValueError) as exc_info:
            MessageHandlerFactory.create(
                handler_type="unknown_type",
                model_provider=provider,
            )

        assert "Unknown handler type: unknown_type" in str(exc_info.value)
        assert "Supported types:" in str(exc_info.value)

    def test_get_available_handlers(self):
        """Test getting list of available handlers."""
        available = MessageHandlerFactory.get_available_handlers()

        assert isinstance(available, list)
        assert "truncating" in available
        assert len(available) == 1  # Only truncating is implemented

    def test_get_planned_handlers(self):
        """Test getting list of planned handlers."""
        planned = MessageHandlerFactory.get_planned_handlers()

        assert isinstance(planned, list)
        assert "sliding_window" in planned
        assert "compressing" in planned
        assert "hybrid" in planned
        assert len(planned) == 3
