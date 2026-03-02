"""Tests for search engine fallback chain functionality."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any

from tools.fallback import FallbackToolProvider
from tools.base import ToolProvider


class MockSearchProvider(ToolProvider):
    """Mock search provider for testing."""

    tool_type = "search"
    provider_id = "mock_search"
    display_name = "Mock Search"
    description = "Mock search provider for testing"

    def __init__(self, config: dict[str, Any] | None = None, should_fail: bool = False, return_empty: bool = False):
        super().__init__(config)
        self.should_fail = should_fail
        self.return_empty = return_empty
        self.call_count = 0

    @classmethod
    def config_schema(cls) -> list[dict[str, Any]]:
        return []

    def openai_function_def(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Mock search",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"}
                    },
                    "required": ["query"]
                }
            }
        }

    async def execute(self, args: dict[str, Any]) -> Any:
        self.call_count += 1

        if self.should_fail:
            raise Exception(f"{self.provider_id} failed")

        if self.return_empty:
            return []

        return [
            {"title": f"Result from {self.provider_id}", "url": "http://example.com", "snippet": "Test snippet"}
        ]


@pytest.mark.asyncio
async def test_fallback_on_provider_failure():
    """Test that fallback occurs when a provider fails."""
    provider1 = MockSearchProvider(should_fail=True)
    provider1.provider_id = "provider1"

    provider2 = MockSearchProvider(should_fail=False)
    provider2.provider_id = "provider2"

    # Create fallback wrapper manually
    fallback = FallbackToolProvider.__new__(FallbackToolProvider)
    fallback.providers = [provider1, provider2]
    fallback.primary = provider1
    fallback.tool_type = "search"
    fallback.quality_assessor = None
    fallback.quality_threshold = 0.3

    result = await fallback.execute({"query": "test"})

    assert provider1.call_count == 1, "First provider should be called"
    assert provider2.call_count == 1, "Second provider should be called after first fails"
    assert result[0]["title"] == "Result from provider2", "Should return result from second provider"


@pytest.mark.asyncio
async def test_fallback_on_empty_results():
    """Test that fallback occurs when a provider returns empty results."""
    provider1 = MockSearchProvider(return_empty=True)
    provider1.provider_id = "provider1"

    provider2 = MockSearchProvider(should_fail=False)
    provider2.provider_id = "provider2"

    fallback = FallbackToolProvider.__new__(FallbackToolProvider)
    fallback.providers = [provider1, provider2]
    fallback.primary = provider1
    fallback.tool_type = "search"
    fallback.quality_assessor = None
    fallback.quality_threshold = 0.3

    result = await fallback.execute({"query": "test"})

    assert provider1.call_count == 1
    assert provider2.call_count == 1
    assert result[0]["title"] == "Result from provider2"


@pytest.mark.asyncio
async def test_all_providers_fail():
    """Test error handling when all providers fail."""
    provider1 = MockSearchProvider(should_fail=True)
    provider1.provider_id = "provider1"

    provider2 = MockSearchProvider(should_fail=True)
    provider2.provider_id = "provider2"

    fallback = FallbackToolProvider.__new__(FallbackToolProvider)
    fallback.providers = [provider1, provider2]
    fallback.primary = provider1
    fallback.tool_type = "search"
    fallback.quality_assessor = None
    fallback.quality_threshold = 0.3

    with pytest.raises(Exception) as exc_info:
        await fallback.execute({"query": "test"})

    assert "All 2 providers failed" in str(exc_info.value)
    assert provider1.call_count == 1
    assert provider2.call_count == 1


@pytest.mark.asyncio
async def test_fallback_chain_order():
    """Test that providers are tried in the correct order."""
    call_order = []

    class OrderTrackingProvider(MockSearchProvider):
        async def execute(self, args: dict[str, Any]) -> Any:
            call_order.append(self.provider_id)
            if self.should_fail:
                raise Exception(f"{self.provider_id} failed")
            return await super().execute(args)

    provider1 = OrderTrackingProvider(should_fail=True)
    provider1.provider_id = "first"

    provider2 = OrderTrackingProvider(should_fail=True)
    provider2.provider_id = "second"

    provider3 = OrderTrackingProvider(should_fail=False)
    provider3.provider_id = "third"

    fallback = FallbackToolProvider.__new__(FallbackToolProvider)
    fallback.providers = [provider1, provider2, provider3]
    fallback.primary = provider1
    fallback.tool_type = "search"
    fallback.quality_assessor = None
    fallback.quality_threshold = 0.3

    result = await fallback.execute({"query": "test"})

    assert call_order == ["first", "second", "third"], "Providers should be called in order"
    assert result[0]["title"] == "Result from third"


@pytest.mark.asyncio
async def test_no_fallback_on_success():
    """Test that fallback doesn't occur when first provider succeeds."""
    provider1 = MockSearchProvider(should_fail=False)
    provider1.provider_id = "provider1"

    provider2 = MockSearchProvider(should_fail=False)
    provider2.provider_id = "provider2"

    fallback = FallbackToolProvider.__new__(FallbackToolProvider)
    fallback.providers = [provider1, provider2]
    fallback.primary = provider1
    fallback.tool_type = "search"
    fallback.quality_assessor = None
    fallback.quality_threshold = 0.3

    result = await fallback.execute({"query": "test"})

    assert provider1.call_count == 1
    assert provider2.call_count == 0, "Second provider should not be called"
    assert result[0]["title"] == "Result from provider1"
