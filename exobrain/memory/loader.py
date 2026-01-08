"""Smart loading utilities for conversation history."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class TokenBudgetCalculator:
    """Calculate token budgets for loading conversation history."""

    def __init__(self, model_provider: Any, config: Any):
        """Initialize calculator.

        Args:
            model_provider: Model provider for context window info
            config: Application configuration
        """
        self.model_provider = model_provider
        self.config = config

    def calculate_budget(self, system_prompt_tokens: int = 0) -> int:
        """Calculate available token budget for loading history.

        Args:
            system_prompt_tokens: Estimated tokens in system prompt

        Returns:
            Number of tokens available for history
        """
        # Get model context window
        context_window = self.model_provider.get_context_window()

        # Reserved space for system prompt (if not provided, estimate)
        if system_prompt_tokens == 0:
            system_prompt_tokens = self._estimate_system_prompt_tokens()

        # Reserved space for model response
        reserved_response = 4096  # Default reservation for output

        # Load percentage from config
        load_percentage = getattr(self.config.memory.long_term, "load_percentage", 0.5)

        # Calculate available budget
        available_for_history = context_window - system_prompt_tokens - reserved_response
        budget = int(available_for_history * load_percentage)

        logger.debug(
            f"Token budget calculation: "
            f"context={context_window}, "
            f"system={system_prompt_tokens}, "
            f"reserved={reserved_response}, "
            f"percentage={load_percentage:.0%}, "
            f"budget={budget}"
        )

        return max(budget, 0)  # Ensure non-negative

    def _estimate_system_prompt_tokens(self) -> int:
        """Estimate tokens used by system prompt.

        This is a rough estimate. Actual implementation should count real prompt.

        Returns:
            Estimated token count
        """
        # Rough estimate: system prompt + skills summary
        # Actual value should be calculated from real system prompt
        estimated_base = 1000  # Basic system prompt
        estimated_skills = 1000  # Skills summary (if enabled)

        return estimated_base + estimated_skills


def format_load_stats(stats: dict[str, Any]) -> str:
    """Format loading statistics for display.

    Args:
        stats: Statistics dict from ConversationManager.load_session

    Returns:
        Formatted string for user display
    """
    loaded = stats["loaded_count"]
    tokens = stats["loaded_tokens"]
    truncated = stats["truncated_count"]
    total = stats["total_count"]

    if truncated > 0:
        return (
            f"Loaded {loaded}/{total} messages ({tokens:,} tokens), "
            f"{truncated} older messages truncated"
        )
    else:
        return f"Loaded {loaded} messages ({tokens:,} tokens)"
