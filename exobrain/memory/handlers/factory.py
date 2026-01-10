"""Factory for creating message handlers."""

import logging
from typing import Any

from exobrain.memory.handlers.base import MessageHandler
from exobrain.memory.handlers.truncating import TruncatingMessageHandler
from exobrain.providers.base import ModelProvider

logger = logging.getLogger(__name__)


class MessageHandlerFactory:
    """Factory for creating message handlers based on configuration."""

    @staticmethod
    def create(
        handler_type: str,
        model_provider: ModelProvider,
        config: dict[str, Any] | None = None,
    ) -> MessageHandler:
        """Create a message handler based on type.

        Args:
            handler_type: Type of handler (truncating, sliding_window, compressing, hybrid)
            model_provider: Model provider instance
            config: Handler-specific configuration

        Returns:
            Configured MessageHandler instance

        Raises:
            ValueError: If handler type is unknown or not yet implemented
        """
        config = config or {}

        if handler_type == "truncating":
            return TruncatingMessageHandler(
                model_provider=model_provider,
                context_window=config.get("context_window"),
                load_percentage=config.get("load_percentage", 0.5),
                reserved_output_tokens=config.get("reserved_output_tokens", 4096),
            )
        elif handler_type == "sliding_window":
            raise NotImplementedError(
                "SlidingWindowHandler is not yet implemented. "
                "This will be added in Phase 2. "
                "Use 'truncating' handler for now."
            )
        elif handler_type == "compressing":
            raise NotImplementedError(
                "CompressingMessageHandler is not yet implemented. "
                "This will be added in Phase 2. "
                "Use 'truncating' handler for now."
            )
        elif handler_type == "hybrid":
            raise NotImplementedError(
                "HybridHandler is not yet implemented. "
                "This will be added in Phase 3. "
                "Use 'truncating' handler for now."
            )
        else:
            raise ValueError(
                f"Unknown handler type: {handler_type}. "
                f"Supported types: truncating, sliding_window, compressing, hybrid"
            )

    @staticmethod
    def get_available_handlers() -> list[str]:
        """Get list of available handler types.

        Returns:
            List of handler type names
        """
        return ["truncating"]

    @staticmethod
    def get_planned_handlers() -> list[str]:
        """Get list of planned but not yet implemented handler types.

        Returns:
            List of planned handler type names
        """
        return ["sliding_window", "compressing", "hybrid"]
