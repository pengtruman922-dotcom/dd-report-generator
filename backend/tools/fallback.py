"""Fallback wrapper for tool providers - tries multiple providers in sequence."""

from __future__ import annotations

import logging
from typing import Any, Callable

from tools.base import ToolProvider
from tools import registry

log = logging.getLogger(__name__)


class FallbackToolProvider(ToolProvider):
    """Wrapper that tries multiple providers in fallback order.

    This class wraps multiple ToolProvider instances and tries them in sequence
    until one succeeds. It's transparent to the agent - the agent sees a single
    tool, but behind the scenes we try multiple providers.
    """

    def __init__(
        self,
        tool_type: str,
        provider_ids: list[str],
        provider_configs: dict[str, dict[str, Any]],
        primary_provider_id: str,
        quality_assessor: Callable[[Any, str], float] | None = None,
        quality_threshold: float = 0.3,
    ):
        """Initialize fallback wrapper.

        Args:
            tool_type: "search" or "scraper"
            provider_ids: List of provider IDs to try in order
            provider_configs: Dict mapping provider_id -> config dict
            primary_provider_id: The primary provider (used for metadata)
            quality_assessor: Optional function to assess result quality (result, query) -> score
            quality_threshold: Minimum quality score to accept (0.0-1.0)
        """
        super().__init__({})
        self._tool_type = tool_type
        self.provider_ids = provider_ids
        self.provider_configs = provider_configs
        self.primary_provider_id = primary_provider_id
        self.quality_assessor = quality_assessor
        self.quality_threshold = quality_threshold

        # Create instances for all providers
        self.providers: list[ToolProvider] = []
        for pid in provider_ids:
            try:
                instance = registry.create_instance(pid, provider_configs.get(pid, {}))
                self.providers.append(instance)
            except Exception as e:
                log.warning(f"Failed to create provider {pid}: {e}")

        if not self.providers:
            raise ValueError(f"No valid providers for tool_type={tool_type}")

        # Use primary provider for metadata
        self.primary = self.providers[0]
        self.tool_type = self._tool_type
        self.provider_id = f"{primary_provider_id}_fallback"
        self.display_name = self.primary.display_name
        self.description = self.primary.description
        self.target_company_type = self.primary.target_company_type

    @classmethod
    def config_schema(cls) -> list[dict[str, Any]]:
        """Not used - fallback wrapper is created programmatically."""
        return []

    def openai_function_def(self) -> dict[str, Any]:
        """Return the primary provider's function definition."""
        return self.primary.openai_function_def()

    async def execute(self, args: dict[str, Any]) -> Any:
        """Try each provider in sequence until one succeeds with acceptable quality."""
        last_error = None
        query = args.get("query", args.get("url", ""))  # For search or scraper

        for i, provider in enumerate(self.providers):
            try:
                log.info(f"Trying provider {provider.provider_id} ({i+1}/{len(self.providers)})")
                result = await provider.execute(args)

                # Check if result is valid (not empty)
                if not self._is_valid_result(result):
                    log.warning(f"Provider {provider.provider_id} returned empty result")
                    last_error = Exception(f"{provider.provider_id} returned empty result")
                    continue

                # Assess quality if assessor is provided
                if self.quality_assessor and self._tool_type == "search":
                    quality_score = self.quality_assessor(result, query)
                    if quality_score < self.quality_threshold:
                        log.warning(
                            f"Provider {provider.provider_id} quality too low: {quality_score:.2f} < {self.quality_threshold}"
                        )
                        last_error = Exception(
                            f"{provider.provider_id} quality score {quality_score:.2f} below threshold"
                        )
                        continue

                # Success!
                if i > 0:
                    log.info(f"Fallback succeeded with {provider.provider_id}")
                return result

            except Exception as e:
                log.warning(f"Provider {provider.provider_id} failed: {e}")
                last_error = e
                continue

        # All providers failed
        error_msg = f"All {len(self.providers)} providers failed"
        if last_error:
            error_msg += f". Last error: {last_error}"
        raise Exception(error_msg)

    def _is_valid_result(self, result: Any) -> bool:
        """Check if a result is valid (not empty)."""
        if result is None:
            return False
        if isinstance(result, (list, dict, str)) and not result:
            return False
        return True

    def validate_config(self) -> list[str]:
        """Validate all provider configs."""
        errors = []
        for provider in self.providers:
            provider_errors = provider.validate_config()
            if provider_errors:
                errors.append(f"{provider.display_name}: {', '.join(provider_errors)}")
        return errors
