"""Integration tests for Phase 2 reliability features."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Any

from tools.fallback import FallbackToolProvider
from agents.researcher import _assess_search_quality, _is_company_listed
from config import SEARCH_QUALITY_THRESHOLD, RESEARCH_ITERATIONS


class MockQualitySearchProvider:
    """Mock provider that returns results with configurable quality."""

    def __init__(self, provider_id: str, quality_level: str = "high"):
        self.provider_id = provider_id
        self.quality_level = quality_level
        self.call_count = 0
        self.tool_type = "search"
        self.display_name = f"Mock {provider_id}"
        self.description = "Mock provider"
        self.target_company_type = "all"

    def openai_function_def(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "web_search",
                "description": "Mock search",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"]
                }
            }
        }

    async def execute(self, args: dict[str, Any]) -> Any:
        self.call_count += 1
        query = args.get("query", "")

        if self.quality_level == "high":
            # High quality: many relevant recent results
            return [
                {"title": f"{query} Company 2025", "snippet": f"Latest {query} information", "url": "http://example.com/1"},
                {"title": f"{query} Analysis 2024", "snippet": f"Detailed {query} analysis", "url": "http://example.com/2"},
                {"title": f"{query} Report", "snippet": f"Comprehensive {query} report", "url": "http://example.com/3"},
                {"title": f"{query} Data 2026", "snippet": f"Future {query} projections", "url": "http://example.com/4"},
                {"title": f"{query} Overview", "snippet": f"Complete {query} overview", "url": "http://example.com/5"},
            ]
        elif self.quality_level == "low":
            # Low quality: few irrelevant old results
            return [
                {"title": "Unrelated Article", "snippet": "Something from 2010", "url": "http://example.com/1"},
            ]
        else:  # empty
            return []


@pytest.mark.asyncio
async def test_quality_based_fallback_integration():
    """Test that low quality results trigger fallback to next provider."""
    # First provider returns low quality results
    provider1 = MockQualitySearchProvider("provider1", quality_level="low")
    # Second provider returns high quality results
    provider2 = MockQualitySearchProvider("provider2", quality_level="high")

    fallback = FallbackToolProvider.__new__(FallbackToolProvider)
    fallback.providers = [provider1, provider2]
    fallback.primary = provider1
    fallback.tool_type = "search"
    fallback.quality_assessor = _assess_search_quality
    fallback.quality_threshold = SEARCH_QUALITY_THRESHOLD

    result = await fallback.execute({"query": "test company"})

    # Both providers should be called (first for low quality, second for fallback)
    assert provider1.call_count == 1, "First provider should be called"
    assert provider2.call_count == 1, "Second provider should be called after low quality"

    # Result should be from second provider
    assert "provider2" not in result[0]["title"]  # Title contains query, not provider
    assert len(result) >= 5, "Should have high quality results from second provider"


@pytest.mark.asyncio
async def test_no_fallback_on_high_quality():
    """Test that high quality results don't trigger fallback."""
    provider1 = MockQualitySearchProvider("provider1", quality_level="high")
    provider2 = MockQualitySearchProvider("provider2", quality_level="high")

    fallback = FallbackToolProvider.__new__(FallbackToolProvider)
    fallback.providers = [provider1, provider2]
    fallback.primary = provider1
    fallback.tool_type = "search"
    fallback.quality_assessor = _assess_search_quality
    fallback.quality_threshold = SEARCH_QUALITY_THRESHOLD

    result = await fallback.execute({"query": "test company"})

    assert provider1.call_count == 1, "First provider should be called"
    assert provider2.call_count == 0, "Second provider should NOT be called (high quality)"
    assert len(result) >= 5, "Should have high quality results"


@pytest.mark.asyncio
async def test_fallback_chain_exhaustion():
    """Test behavior when all providers return low quality."""
    provider1 = MockQualitySearchProvider("provider1", quality_level="low")
    provider2 = MockQualitySearchProvider("provider2", quality_level="low")
    provider3 = MockQualitySearchProvider("provider3", quality_level="low")

    fallback = FallbackToolProvider.__new__(FallbackToolProvider)
    fallback.providers = [provider1, provider2, provider3]
    fallback.primary = provider1
    fallback.tool_type = "search"
    fallback.quality_assessor = _assess_search_quality
    fallback.quality_threshold = SEARCH_QUALITY_THRESHOLD

    with pytest.raises(Exception) as exc_info:
        await fallback.execute({"query": "test"})

    assert "All 3 providers failed" in str(exc_info.value)
    assert provider1.call_count == 1
    assert provider2.call_count == 1
    assert provider3.call_count == 1


@pytest.mark.asyncio
async def test_empty_results_trigger_fallback():
    """Test that empty results trigger fallback even with quality assessor."""
    provider1 = MockQualitySearchProvider("provider1", quality_level="empty")
    provider2 = MockQualitySearchProvider("provider2", quality_level="high")

    fallback = FallbackToolProvider.__new__(FallbackToolProvider)
    fallback.providers = [provider1, provider2]
    fallback.primary = provider1
    fallback.tool_type = "search"
    fallback.quality_assessor = _assess_search_quality
    fallback.quality_threshold = SEARCH_QUALITY_THRESHOLD

    result = await fallback.execute({"query": "test"})

    assert provider1.call_count == 1
    assert provider2.call_count == 1
    assert len(result) >= 5


def test_adaptive_iterations_integration():
    """Test that company type correctly determines iteration count."""
    # Listed company
    listed_profile = {"is_listed": "是", "company_name": "上市公司"}
    is_listed = _is_company_listed(listed_profile)
    assert is_listed is True
    expected_iterations = RESEARCH_ITERATIONS["listed"]
    assert expected_iterations == 10

    # Unlisted company
    unlisted_profile = {"is_listed": "否", "company_name": "非上市公司"}
    is_listed = _is_company_listed(unlisted_profile)
    assert is_listed is False
    expected_iterations = RESEARCH_ITERATIONS["unlisted"]
    assert expected_iterations == 18

    # Unknown company type
    unknown_profile = {"company_name": "未知公司"}
    is_listed = _is_company_listed(unknown_profile)
    assert is_listed is None
    expected_iterations = RESEARCH_ITERATIONS["default"]
    assert expected_iterations == 15


def test_quality_threshold_configuration():
    """Test that quality threshold is properly configured."""
    assert SEARCH_QUALITY_THRESHOLD == 0.3, "Quality threshold should be 0.3"

    # Test that threshold is used correctly
    low_quality_results = [{"title": "Old", "snippet": "2010", "url": "http://example.com"}]
    score = _assess_search_quality(low_quality_results, "specific query")
    assert score < SEARCH_QUALITY_THRESHOLD, "Low quality should be below threshold"

    high_quality_results = [
        {"title": "Query Result 2025", "snippet": "Specific query information", "url": "http://example.com/1"},
        {"title": "Query Analysis 2024", "snippet": "Detailed specific query data", "url": "http://example.com/2"},
        {"title": "Query Report 2026", "snippet": "Latest specific query findings", "url": "http://example.com/3"},
        {"title": "Query Overview", "snippet": "Complete specific query overview", "url": "http://example.com/4"},
        {"title": "Query Data", "snippet": "Comprehensive specific query data", "url": "http://example.com/5"},
    ]
    score = _assess_search_quality(high_quality_results, "specific query")
    assert score >= SEARCH_QUALITY_THRESHOLD, "High quality should be above threshold"


@pytest.mark.asyncio
async def test_scraper_fallback_no_quality_check():
    """Test that scraper fallback doesn't use quality assessment."""
    class MockScraper:
        def __init__(self, provider_id: str, should_fail: bool = False):
            self.provider_id = provider_id
            self.should_fail = should_fail
            self.call_count = 0
            self.tool_type = "scraper"

        async def execute(self, args: dict[str, Any]) -> Any:
            self.call_count += 1
            if self.should_fail:
                raise Exception(f"{self.provider_id} failed")
            return f"Content from {self.provider_id}"

        def openai_function_def(self):
            return {"type": "function", "function": {"name": "fetch_webpage"}}

    scraper1 = MockScraper("scraper1", should_fail=True)
    scraper2 = MockScraper("scraper2", should_fail=False)

    fallback = FallbackToolProvider.__new__(FallbackToolProvider)
    fallback.providers = [scraper1, scraper2]
    fallback.primary = scraper1
    fallback.tool_type = "scraper"
    fallback.quality_assessor = _assess_search_quality  # Should not be used for scrapers
    fallback.quality_threshold = SEARCH_QUALITY_THRESHOLD

    result = await fallback.execute({"url": "http://example.com"})

    assert scraper1.call_count == 1
    assert scraper2.call_count == 1
    assert result == "Content from scraper2"