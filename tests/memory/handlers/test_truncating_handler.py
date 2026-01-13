"""Tests for message handlers."""


from exobrain.memory.handlers.base import LoadResult
from exobrain.memory.handlers.truncating import TruncatingMessageHandler
from exobrain.providers.base import Message, ModelProvider


class MockModelProvider(ModelProvider):
    """Mock model provider for testing."""

    def __init__(self, context_window: int = 128000):
        self._context_window = context_window

    def get_context_window(self) -> int:
        return self._context_window

    def count_tokens(self, text: str) -> int:
        """Simple approximation: 1 token ≈ 4 characters."""
        return len(text) // 4

    def supports_tool_calling(self) -> bool:
        return True

    async def generate(self, *args, **kwargs):
        """Not needed for handler tests."""

    async def embed(self, texts: list[str], **kwargs):
        """Not needed for handler tests."""
        return [[0.0] * 768 for _ in texts]


class TestLoadResult:
    """Tests for LoadResult data class."""

    def test_load_result_creation(self):
        """Test creating a LoadResult."""
        messages = [{"role": "user", "content": "Hello"}]
        result = LoadResult(
            messages=messages,
            loaded_count=1,
            loaded_tokens=100,
            total_count=10,
            truncated_count=9,
        )

        assert result.messages == messages
        assert result.loaded_count == 1
        assert result.loaded_tokens == 100
        assert result.total_count == 10
        assert result.truncated_count == 9
        assert result.compressed_count == 0
        assert result.metadata == {}

    def test_load_result_to_dict(self):
        """Test converting LoadResult to dict."""
        messages = [{"role": "user", "content": "Hello"}]
        result = LoadResult(
            messages=messages,
            loaded_count=1,
            loaded_tokens=100,
            total_count=10,
            truncated_count=9,
            metadata={"strategy": "test"},
        )

        result_dict = result.to_dict()

        assert result_dict["messages"] == messages
        assert result_dict["loaded_count"] == 1
        assert result_dict["loaded_tokens"] == 100
        assert result_dict["total_count"] == 10
        assert result_dict["truncated_count"] == 9
        assert result_dict["compressed_count"] == 0
        assert result_dict["metadata"] == {"strategy": "test"}

    def test_load_result_repr(self):
        """Test LoadResult string representation."""
        result = LoadResult(
            messages=[],
            loaded_count=5,
            loaded_tokens=1000,
            total_count=10,
            truncated_count=5,
        )

        repr_str = repr(result)
        assert "loaded=5/10" in repr_str
        assert "tokens=1000" in repr_str
        assert "truncated=5" in repr_str


class TestTruncatingMessageHandler:
    """Tests for TruncatingMessageHandler."""

    def test_handler_initialization(self):
        """Test handler initialization with default values."""
        provider = MockModelProvider(context_window=128000)
        handler = TruncatingMessageHandler(model_provider=provider)

        assert handler.context_window == 128000
        assert handler.load_percentage == 0.5
        assert handler.reserved_output_tokens == 4096

    def test_handler_initialization_with_custom_values(self):
        """Test handler initialization with custom values."""
        provider = MockModelProvider(context_window=100000)
        handler = TruncatingMessageHandler(
            model_provider=provider,
            context_window=50000,  # Override
            load_percentage=0.7,
            reserved_output_tokens=2048,
        )

        assert handler.context_window == 50000  # Overridden
        assert handler.load_percentage == 0.7
        assert handler.reserved_output_tokens == 2048

    def test_calculate_budget_with_system_prompt(self):
        """Test budget calculation with system prompt."""
        provider = MockModelProvider(context_window=128000)
        handler = TruncatingMessageHandler(
            model_provider=provider,
            load_percentage=0.5,
            reserved_output_tokens=4096,
        )

        # System prompt: 100 chars = ~25 tokens
        system_prompt = "You are a helpful assistant." * 4  # ~100 chars
        budget = handler.calculate_budget(system_prompt=system_prompt)

        # Expected: (128000 - 25 - 4096) * 0.5 = ~61939
        assert budget > 60000
        assert budget < 65000

    def test_calculate_budget_without_system_prompt(self):
        """Test budget calculation without system prompt (uses estimate)."""
        provider = MockModelProvider(context_window=128000)
        handler = TruncatingMessageHandler(
            model_provider=provider,
            load_percentage=0.5,
            reserved_output_tokens=4096,
        )

        budget = handler.calculate_budget(system_prompt=None)

        # Expected: (128000 - 2000 - 4096) * 0.5 = ~60952
        assert budget > 60000
        assert budget < 62000

    def test_load_messages_empty_list(self):
        """Test loading empty message list."""
        provider = MockModelProvider()
        handler = TruncatingMessageHandler(model_provider=provider)

        result = handler.load_messages(all_messages=[])

        assert result.messages == []
        assert result.loaded_count == 0
        assert result.loaded_tokens == 0
        assert result.total_count == 0
        assert result.truncated_count == 0

    def test_load_messages_within_budget(self):
        """Test loading messages that fit within budget."""
        provider = MockModelProvider(context_window=128000)
        handler = TruncatingMessageHandler(model_provider=provider)

        # Create small messages that will fit
        messages = [
            {"role": "user", "content": "Hello", "tokens": 10},
            {"role": "assistant", "content": "Hi there!", "tokens": 10},
            {"role": "user", "content": "How are you?", "tokens": 10},
        ]

        result = handler.load_messages(all_messages=messages)

        # All messages should be loaded
        assert result.loaded_count == 3
        assert result.total_count == 3
        assert result.truncated_count == 0
        assert len(result.messages) == 3

    def test_load_messages_exceeds_budget(self):
        """Test loading messages that exceed budget (truncation)."""
        provider = MockModelProvider(context_window=10000)
        handler = TruncatingMessageHandler(
            model_provider=provider,
            load_percentage=0.5,
            reserved_output_tokens=1000,
        )

        # Budget: (10000 - 2000 - 1000) * 0.5 = 3500 tokens
        # Create messages that exceed budget
        messages = [
            {"role": "user", "content": "Old message 1", "tokens": 2000},
            {"role": "assistant", "content": "Old response 1", "tokens": 2000},
            {"role": "user", "content": "Recent message", "tokens": 1000},
            {"role": "assistant", "content": "Recent response", "tokens": 1000},
        ]

        result = handler.load_messages(all_messages=messages)

        # Should load only recent messages (last 2)
        # Budget is 3500, so we can fit 1000 + 1000 = 2000 tokens (2 messages)
        # The third message (2000 tokens) would make it 4000 > 3500, so it's dropped
        assert result.loaded_count == 2
        assert result.total_count == 4
        assert result.truncated_count == 2
        assert result.loaded_tokens == 2000
        assert len(result.messages) == 2
        # Check that recent messages are loaded
        assert result.messages[0]["content"] == "Recent message"
        assert result.messages[1]["content"] == "Recent response"

    def test_load_messages_estimates_missing_tokens(self):
        """Test that handler estimates tokens when not provided."""
        provider = MockModelProvider()
        handler = TruncatingMessageHandler(model_provider=provider)

        # Messages without token counts
        messages = [
            {"role": "user", "content": "A" * 100},  # ~25 tokens
            {"role": "assistant", "content": "B" * 100},  # ~25 tokens
        ]

        result = handler.load_messages(all_messages=messages)

        # Should estimate and load both
        assert result.loaded_count == 2
        assert result.loaded_tokens > 0  # Estimated tokens

    def test_load_messages_chronological_order(self):
        """Test that loaded messages are in chronological order."""
        provider = MockModelProvider(context_window=10000)
        handler = TruncatingMessageHandler(model_provider=provider)

        messages = [
            {"role": "user", "content": "Message 1", "tokens": 100},
            {"role": "assistant", "content": "Response 1", "tokens": 100},
            {"role": "user", "content": "Message 2", "tokens": 100},
            {"role": "assistant", "content": "Response 2", "tokens": 100},
        ]

        result = handler.load_messages(all_messages=messages)

        # Messages should be in chronological order (oldest first)
        assert result.messages[0]["content"] == "Message 1"
        assert result.messages[1]["content"] == "Response 1"
        assert result.messages[2]["content"] == "Message 2"
        assert result.messages[3]["content"] == "Response 2"

    def test_prepare_for_api(self):
        """Test preparing messages for API call."""
        provider = MockModelProvider()
        handler = TruncatingMessageHandler(model_provider=provider)

        messages = [
            Message(role="user", content="Hello"),
            Message(role="assistant", content="Hi there!"),
        ]
        system_prompt = "You are a helpful assistant."

        prepared = handler.prepare_for_api(messages=messages, system_prompt=system_prompt)

        # Should prepend system message
        assert len(prepared) == 3
        assert prepared[0].role == "system"
        assert prepared[0].content == system_prompt
        assert prepared[1].role == "user"
        assert prepared[1].content == "Hello"
        assert prepared[2].role == "assistant"
        assert prepared[2].content == "Hi there!"

    def test_count_tokens(self):
        """Test token counting."""
        provider = MockModelProvider()
        handler = TruncatingMessageHandler(model_provider=provider)

        # 100 chars = ~25 tokens
        text = "A" * 100
        tokens = handler.count_tokens(text)

        assert tokens == 25

    def test_estimate_message_tokens_with_stored_count(self):
        """Test estimating tokens when count is stored."""
        provider = MockModelProvider()
        handler = TruncatingMessageHandler(model_provider=provider)

        message = {"role": "user", "content": "Hello", "tokens": 42}
        tokens = handler.estimate_message_tokens(message)

        # Should use stored count
        assert tokens == 42

    def test_estimate_message_tokens_without_stored_count(self):
        """Test estimating tokens when count is not stored."""
        provider = MockModelProvider()
        handler = TruncatingMessageHandler(model_provider=provider)

        message = {"role": "user", "content": "A" * 100}  # 100 chars
        tokens = handler.estimate_message_tokens(message)

        # Should estimate: 100 / 4 = 25
        assert tokens == 25

    def test_handler_repr(self):
        """Test handler string representation."""
        provider = MockModelProvider(context_window=128000)
        handler = TruncatingMessageHandler(
            model_provider=provider,
            load_percentage=0.5,
            reserved_output_tokens=4096,
        )

        repr_str = repr(handler)
        assert "TruncatingMessageHandler" in repr_str
        assert "128000" in repr_str
        assert "50%" in repr_str
        assert "4096" in repr_str

    def test_load_messages_metadata(self):
        """Test that load result includes metadata."""
        provider = MockModelProvider()
        handler = TruncatingMessageHandler(model_provider=provider)

        messages = [{"role": "user", "content": "Hello", "tokens": 10}]
        result = handler.load_messages(all_messages=messages)

        assert "strategy" in result.metadata
        assert result.metadata["strategy"] == "truncate_oldest"
        assert "budget" in result.metadata
        assert "load_percentage" in result.metadata
