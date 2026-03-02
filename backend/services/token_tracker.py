"""Token usage tracking and cost estimation for AI pipeline."""

from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger(__name__)

# Token pricing (per 1M tokens) - update these based on your model pricing
# These are example prices, adjust based on actual model costs
TOKEN_PRICING = {
    "default": {
        "prompt": 0.50,  # $0.50 per 1M prompt tokens
        "completion": 1.50,  # $1.50 per 1M completion tokens
    },
    # Add specific model pricing if needed
    "gpt-4": {
        "prompt": 30.0,
        "completion": 60.0,
    },
    "gpt-3.5-turbo": {
        "prompt": 0.50,
        "completion": 1.50,
    },
}


class TokenTracker:
    """Tracks token usage across pipeline steps."""

    def __init__(self):
        self.steps: dict[str, dict] = {}
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_tokens = 0

    def add_usage(self, step_name: str, usage_dict: dict[str, int]):
        """Add token usage for a step.

        Args:
            step_name: Name of the pipeline step (e.g., "extractor", "researcher", "writer")
            usage_dict: Dict with prompt_tokens, completion_tokens, total_tokens
        """
        prompt = usage_dict.get("prompt_tokens", 0)
        completion = usage_dict.get("completion_tokens", 0)
        total = usage_dict.get("total_tokens", 0)

        if step_name not in self.steps:
            self.steps[step_name] = {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "calls": 0,
            }

        self.steps[step_name]["prompt_tokens"] += prompt
        self.steps[step_name]["completion_tokens"] += completion
        self.steps[step_name]["total_tokens"] += total
        self.steps[step_name]["calls"] += 1

        self.total_prompt_tokens += prompt
        self.total_completion_tokens += completion
        self.total_tokens += total

        log.debug(
            f"Token usage for {step_name}: +{prompt} prompt, +{completion} completion, +{total} total"
        )

    def calculate_cost(self, model: str = "default") -> float:
        """Calculate estimated cost based on token usage.

        Args:
            model: Model name to use for pricing lookup

        Returns:
            Estimated cost in USD
        """
        # Get pricing for model (fallback to default)
        pricing = TOKEN_PRICING.get(model, TOKEN_PRICING["default"])

        # Calculate cost (pricing is per 1M tokens)
        prompt_cost = (self.total_prompt_tokens / 1_000_000) * pricing["prompt"]
        completion_cost = (self.total_completion_tokens / 1_000_000) * pricing["completion"]

        total_cost = prompt_cost + completion_cost

        log.info(
            f"Cost calculation: {self.total_prompt_tokens} prompt tokens (${prompt_cost:.4f}) + "
            f"{self.total_completion_tokens} completion tokens (${completion_cost:.4f}) = "
            f"${total_cost:.4f}"
        )

        return total_cost

    def to_dict(self) -> dict[str, Any]:
        """Export token usage as a dictionary."""
        return {
            "steps": self.steps,
            "total": {
                "prompt_tokens": self.total_prompt_tokens,
                "completion_tokens": self.total_completion_tokens,
                "total_tokens": self.total_tokens,
            },
        }

    def to_json(self) -> str:
        """Export token usage as JSON string."""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def __str__(self) -> str:
        """Human-readable summary."""
        lines = [
            f"Token Usage Summary:",
            f"  Total: {self.total_tokens:,} tokens",
            f"  Prompt: {self.total_prompt_tokens:,} tokens",
            f"  Completion: {self.total_completion_tokens:,} tokens",
            f"  Steps:",
        ]
        for step_name, data in self.steps.items():
            lines.append(
                f"    {step_name}: {data['total_tokens']:,} tokens ({data['calls']} calls)"
            )
        return "\n".join(lines)
