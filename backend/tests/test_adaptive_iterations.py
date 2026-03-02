"""Tests for adaptive research iterations functionality."""

import pytest
from agents.researcher import _is_company_listed
from config import RESEARCH_ITERATIONS


def test_is_company_listed_true_string():
    """Test company identified as listed with string 'yes'."""
    profile = {"is_listed": "是"}
    assert _is_company_listed(profile) is True

    profile = {"is_listed": "yes"}
    assert _is_company_listed(profile) is True

    profile = {"is_listed": "true"}
    assert _is_company_listed(profile) is True

    profile = {"is_listed": "1"}
    assert _is_company_listed(profile) is True


def test_is_company_listed_true_boolean():
    """Test company identified as listed with boolean True."""
    profile = {"is_listed": True}
    assert _is_company_listed(profile) is True


def test_is_company_listed_false_string():
    """Test company identified as unlisted with string 'no'."""
    profile = {"is_listed": "否"}
    assert _is_company_listed(profile) is False

    profile = {"is_listed": "no"}
    assert _is_company_listed(profile) is False

    profile = {"is_listed": "false"}
    assert _is_company_listed(profile) is False

    profile = {"is_listed": "0"}
    assert _is_company_listed(profile) is False


def test_is_company_listed_false_boolean():
    """Test company identified as unlisted with boolean False."""
    profile = {"is_listed": False}
    assert _is_company_listed(profile) is False


def test_is_company_listed_with_stock_code():
    """Test company identified as listed when stock_code is present."""
    profile = {"stock_code": "600000"}
    assert _is_company_listed(profile) is True

    profile = {"stock_code": "000001", "is_listed": ""}
    assert _is_company_listed(profile) is True


def test_is_company_listed_unknown():
    """Test company type unknown when no clear indicators."""
    profile = {"is_listed": ""}
    assert _is_company_listed(profile) is None

    profile = {"is_listed": "unknown"}
    assert _is_company_listed(profile) is None

    profile = {}
    assert _is_company_listed(profile) is None

    profile = {"company_name": "Test Company"}
    assert _is_company_listed(profile) is None


def test_is_company_listed_none_profile():
    """Test handling of None profile."""
    assert _is_company_listed(None) is None


def test_research_iterations_config():
    """Test that research iterations config is properly defined."""
    assert "listed" in RESEARCH_ITERATIONS
    assert "unlisted" in RESEARCH_ITERATIONS
    assert "default" in RESEARCH_ITERATIONS

    assert RESEARCH_ITERATIONS["listed"] == 10
    assert RESEARCH_ITERATIONS["unlisted"] == 18
    assert RESEARCH_ITERATIONS["default"] == 15


def test_listed_company_gets_fewer_iterations():
    """Test that listed companies get fewer iterations."""
    listed_iterations = RESEARCH_ITERATIONS["listed"]
    unlisted_iterations = RESEARCH_ITERATIONS["unlisted"]

    assert listed_iterations < unlisted_iterations, \
        "Listed companies should get fewer iterations (more public data available)"


def test_unlisted_company_gets_more_iterations():
    """Test that unlisted companies get more iterations."""
    unlisted_iterations = RESEARCH_ITERATIONS["unlisted"]
    default_iterations = RESEARCH_ITERATIONS["default"]

    assert unlisted_iterations > default_iterations, \
        "Unlisted companies should get more iterations (less public data)"


def test_iteration_counts_reasonable():
    """Test that iteration counts are within reasonable ranges."""
    for key, value in RESEARCH_ITERATIONS.items():
        assert 5 <= value <= 25, f"Iteration count for {key} should be between 5 and 25"


def test_is_company_listed_case_insensitive():
    """Test that string matching is case-insensitive."""
    profile = {"is_listed": "YES"}
    assert _is_company_listed(profile) is True

    profile = {"is_listed": "NO"}
    assert _is_company_listed(profile) is False

    profile = {"is_listed": "True"}
    assert _is_company_listed(profile) is True

    profile = {"is_listed": "False"}
    assert _is_company_listed(profile) is False


def test_is_company_listed_whitespace_handling():
    """Test that whitespace is properly handled."""
    profile = {"is_listed": "  是  "}
    assert _is_company_listed(profile) is True

    profile = {"is_listed": "  否  "}
    assert _is_company_listed(profile) is False

    profile = {"is_listed": " yes "}
    assert _is_company_listed(profile) is True


def test_stock_code_priority():
    """Test that stock_code takes priority when is_listed is ambiguous."""
    # Even with empty is_listed, stock_code indicates listed
    profile = {"is_listed": "", "stock_code": "600000"}
    assert _is_company_listed(profile) is True

    # Stock code present but is_listed explicitly says no - stock code wins
    profile = {"is_listed": "unknown", "stock_code": "000001"}
    assert _is_company_listed(profile) is True