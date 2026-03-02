"""Tests for search quality assessment functionality."""

import pytest
from agents.researcher import _assess_search_quality


def test_quality_empty_results():
    """Test quality score for empty results."""
    score = _assess_search_quality([], "test query")
    assert score == 0.0, "Empty results should have 0.0 quality score"


def test_quality_none_results():
    """Test quality score for None results."""
    score = _assess_search_quality(None, "test query")
    assert score == 0.0, "None results should have 0.0 quality score"


def test_quality_string_error():
    """Test quality score for error string."""
    score = _assess_search_quality("Error: connection failed", "test query")
    assert score == 0.0, "Error string should have 0.0 quality score"


def test_quality_high_count_high_relevance():
    """Test quality score with many relevant results."""
    results = [
        {"title": "Test Company Information", "snippet": "Test company details and query results", "url": "http://example.com/1"},
        {"title": "Query Results for Test", "snippet": "More information about test query", "url": "http://example.com/2"},
        {"title": "Test Query Analysis", "snippet": "Detailed analysis of test company", "url": "http://example.com/3"},
        {"title": "Company Test Data", "snippet": "Test query company information", "url": "http://example.com/4"},
        {"title": "Test Information 2024", "snippet": "Recent test query data from 2024", "url": "http://example.com/5"},
        {"title": "Test Company 2025", "snippet": "Latest test information for 2025", "url": "http://example.com/6"},
        {"title": "Query Test Results", "snippet": "Test company query analysis", "url": "http://example.com/7"},
        {"title": "Test Data 2026", "snippet": "Future test query projections 2026", "url": "http://example.com/8"},
    ]

    score = _assess_search_quality(results, "test query company")
    assert score > 0.7, f"High quality results should score > 0.7, got {score}"


def test_quality_low_relevance():
    """Test quality score with irrelevant results."""
    results = [
        {"title": "Unrelated Article", "snippet": "This has nothing to do with the search", "url": "http://example.com/1"},
        {"title": "Random Content", "snippet": "Some random information here", "url": "http://example.com/2"},
        {"title": "Different Topic", "snippet": "Completely different subject matter", "url": "http://example.com/3"},
    ]

    score = _assess_search_quality(results, "specific company name")
    assert score < 0.5, f"Low relevance results should score < 0.5, got {score}"


def test_quality_with_recency():
    """Test that recent years boost quality score."""
    results_without_recency = [
        {"title": "Company Info", "snippet": "General company information", "url": "http://example.com/1"},
        {"title": "Company Data", "snippet": "More company details", "url": "http://example.com/2"},
        {"title": "Company Analysis", "snippet": "Company analysis report", "url": "http://example.com/3"},
    ]

    results_with_recency = [
        {"title": "Company Info 2024", "snippet": "General company information from 2024", "url": "http://example.com/1"},
        {"title": "Company Data 2025", "snippet": "More company details for 2025", "url": "http://example.com/2"},
        {"title": "Company Analysis 2026", "snippet": "Company analysis report 2026", "url": "http://example.com/3"},
    ]

    score_without = _assess_search_quality(results_without_recency, "company")
    score_with = _assess_search_quality(results_with_recency, "company")

    assert score_with > score_without, "Results with recent years should score higher"


def test_quality_threshold_trigger():
    """Test that low quality results are below threshold."""
    # Very poor results: few, irrelevant, old
    poor_results = [
        {"title": "Old Article", "snippet": "Something from 2010", "url": "http://example.com/1"},
    ]

    score = _assess_search_quality(poor_results, "specific technical query")
    assert score < 0.3, f"Poor results should be below 0.3 threshold, got {score}"


def test_quality_chinese_keywords():
    """Test quality assessment with Chinese keywords."""
    results = [
        {"title": "测试公司信息", "snippet": "测试公司的详细信息和数据", "url": "http://example.com/1"},
        {"title": "公司测试报告", "snippet": "关于测试公司的最新报告", "url": "http://example.com/2"},
        {"title": "测试企业分析", "snippet": "测试企业的市场分析", "url": "http://example.com/3"},
    ]

    score = _assess_search_quality(results, "测试公司")
    assert score > 0.5, f"Chinese keyword matching should work, got {score}"


def test_quality_mixed_results():
    """Test quality with mix of relevant and irrelevant results."""
    results = [
        {"title": "Target Company Info", "snippet": "Information about target company", "url": "http://example.com/1"},
        {"title": "Unrelated Article", "snippet": "Something completely different", "url": "http://example.com/2"},
        {"title": "Target Analysis 2025", "snippet": "Analysis of target company in 2025", "url": "http://example.com/3"},
        {"title": "Random Content", "snippet": "Random unrelated content", "url": "http://example.com/4"},
        {"title": "Company Target Data", "snippet": "Data about the target company", "url": "http://example.com/5"},
    ]

    score = _assess_search_quality(results, "target company")
    assert 0.3 < score < 0.8, f"Mixed results should have moderate score, got {score}"


def test_quality_stop_words_filtered():
    """Test that Chinese stop words are filtered from relevance check."""
    results = [
        {"title": "的了在是", "snippet": "只有停用词的结果", "url": "http://example.com/1"},
        {"title": "公司信息", "snippet": "有意义的公司信息", "url": "http://example.com/2"},
    ]

    # Query with only stop words should still get neutral relevance score
    score = _assess_search_quality(results, "的 了 在 是")
    assert score >= 0.0, "Stop words query should not crash"


def test_quality_malformed_results():
    """Test quality assessment with malformed result objects."""
    results = [
        {"title": "Good Result", "snippet": "Valid snippet", "url": "http://example.com/1"},
        {"no_title": "Missing title"},  # Malformed
        "string_instead_of_dict",  # Wrong type
        {"title": "Another Good", "snippet": "Valid", "url": "http://example.com/2"},
    ]

    score = _assess_search_quality(results, "test")
    assert score >= 0.0, "Should handle malformed results gracefully"