# Test Suite Documentation

## Overview

The DD Report Generator has comprehensive test coverage with **83 automated tests** covering Phase 2 (Reliability) and Phase 3 (Persistence & Streaming) features.

## Test Statistics

- **Total Tests**: 83
- **Phase 2 Tests**: 37 (Reliability features)
- **Phase 3 Tests**: 46 (Persistence & Streaming)
- **Test Framework**: pytest + pytest-asyncio
- **Coverage**: Core reliability and persistence features

## Quick Start

### Installation

```bash
cd backend
pip install pytest pytest-asyncio
```

### Run All Tests

```bash
pytest
```

### Run Specific Phase

```bash
# Phase 2 only
pytest tests/test_search_fallback.py tests/test_search_quality.py tests/test_adaptive_iterations.py tests/test_reliability_integration.py

# Phase 3 only
pytest tests/test_task_persistence.py tests/test_streaming_output.py tests/test_phase3_integration.py
```

### Run with Verbose Output

```bash
pytest -v
```

### Run with Coverage

```bash
pytest --cov=agents --cov=tools --cov=services --cov=config
```

---

## Phase 2: Reliability Tests (37 tests)

### test_search_fallback.py (5 tests)

Tests the search engine fallback chain functionality.

**Test Cases:**
- `test_fallback_on_provider_failure` - Verifies fallback when provider raises exception
- `test_fallback_on_empty_results` - Verifies fallback when provider returns empty list
- `test_all_providers_fail` - Verifies error handling when all providers fail
- `test_fallback_chain_order` - Verifies providers are tried in correct order
- `test_no_fallback_on_success` - Verifies no unnecessary fallback when first provider succeeds

**Key Assertions:**
```python
assert provider1.call_count == 1  # First provider called
assert provider2.call_count == 1  # Second provider called after failure
assert result[0]["title"] == "Result from provider2"  # Correct result returned
```

### test_search_quality.py (11 tests)

Tests the search quality assessment algorithm.

**Test Cases:**
- `test_quality_empty_results` - Empty results score 0.0
- `test_quality_none_results` - None results score 0.0
- `test_quality_string_error` - Error strings score 0.0
- `test_quality_high_count_high_relevance` - Many relevant results score > 0.7
- `test_quality_low_relevance` - Irrelevant results score < 0.5
- `test_quality_with_recency` - Recent years boost score
- `test_quality_threshold_trigger` - Poor results score < 0.3
- `test_quality_chinese_keywords` - Chinese keyword matching works
- `test_quality_mixed_results` - Mixed quality scores moderately
- `test_quality_stop_words_filtered` - Stop words don't crash system
- `test_quality_malformed_results` - Malformed data handled gracefully

**Quality Scoring Formula:**
```python
quality_score = (count_score * 0.4) + (relevance_score * 0.4) + (recency_score * 0.2)
```

### test_adaptive_iterations.py (13 tests)

Tests adaptive research iteration logic.

**Test Cases:**
- Company type detection (是/否/yes/no/true/false/1/0)
- Stock code presence detection
- Unknown company type handling
- Configuration validation
- Case-insensitive matching
- Whitespace handling

**Key Assertions:**
```python
assert _is_company_listed({"is_listed": "是"}) is True
assert _is_company_listed({"is_listed": "否"}) is False
assert _is_company_listed({"stock_code": "600000"}) is True
assert RESEARCH_ITERATIONS["listed"] == 10
assert RESEARCH_ITERATIONS["unlisted"] == 18
```

### test_reliability_integration.py (8 tests)

Integration tests combining multiple reliability features.

**Test Cases:**
- `test_quality_based_fallback_integration` - Low quality triggers fallback
- `test_no_fallback_on_high_quality` - High quality prevents fallback
- `test_fallback_chain_exhaustion` - All providers return low quality
- `test_empty_results_trigger_fallback` - Empty results trigger fallback
- `test_adaptive_iterations_integration` - Company type determines iterations
- `test_quality_threshold_configuration` - Threshold properly configured
- `test_scraper_fallback_no_quality_check` - Scrapers don't use quality check

---

## Phase 3: Persistence & Streaming Tests (46 tests)

### test_task_persistence.py (16 tests)

Tests task persistence and recovery functionality.

**Test Cases:**
- `test_task_creation` - Create and store task
- `test_task_status_update` - Update status and progress
- `test_task_failure_with_error` - Record failure with error message
- `test_list_tasks_with_filters` - Filter by status and owner
- `test_get_pending_tasks` - Retrieve pending/running tasks
- `test_start_task_success` - Task completes successfully
- `test_start_task_failure` - Task fails with exception
- `test_cancel_running_task` - Cancel in-progress task
- `test_cancel_nonexistent_task` - Handle non-existent task
- `test_task_recovery` - Recover tasks after restart
- `test_cleanup_old_tasks` - Delete old completed tasks
- `test_concurrent_task_execution` - Multiple tasks run concurrently
- `test_task_state_consistency` - State remains consistent

**Task Lifecycle:**
```
PENDING → RUNNING → COMPLETED/FAILED/CANCELLED
         ↓ (crash)
      RECOVERY
```

### test_streaming_output.py (20 tests)

Tests SSE streaming functionality.

**Test Cases:**
- `test_subscribe_creates_queue` - Subscription creates queue
- `test_multiple_subscribers` - Multiple subscribers per task
- `test_unsubscribe_removes_queue` - Unsubscribe cleanup
- `test_send_event_to_subscribers` - Event broadcasting
- `test_send_progress_event` - Progress events
- `test_send_stream_chunk` - Content streaming
- `test_send_complete_event` - Completion events
- `test_send_error_event` - Error events
- `test_event_ordering` - Events received in order
- `test_concurrent_sends` - Concurrent event sending
- `test_queue_isolation` - Tasks don't leak events
- `test_late_subscriber` - Late subscribers don't get past events
- `test_streaming_large_chunks` - Handle 10KB+ chunks
- `test_rapid_event_sending` - Handle 100+ rapid events

**Event Types:**
```python
# Progress event
{"event": "progress", "data": {"step": 3, "total": 6, "message": "..."}}

# Stream chunk
{"event": "stream", "data": {"chunk": "report content..."}}

# Complete event
{"event": "complete", "data": {"report_id": "..."}}

# Error event
{"event": "error", "data": {"error": "error message"}}
```

### test_phase3_integration.py (10 tests)

Integration tests for persistence + streaming.

**Test Cases:**
- `test_task_with_streaming_progress` - Task execution with progress updates
- `test_task_failure_with_error_event` - Failures send error events
- `test_service_restart_recovery_with_streaming` - Recovery with streaming
- `test_concurrent_tasks_with_isolated_streams` - 3 concurrent tasks
- `test_streaming_interruption_recovery` - Handle connection drops
- `test_task_cancellation_with_cleanup` - Cancel with cleanup
- `test_full_pipeline_with_persistence_and_streaming` - Complete flow
- `test_error_propagation_through_streaming` - Errors propagate correctly
- `test_performance_under_load` - 10 concurrent tasks

---

## Test Patterns and Best Practices

### Mocking External Dependencies

```python
from unittest.mock import AsyncMock, patch

@pytest.fixture
def temp_db():
    """Create temporary database for testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    with patch('services.task_manager.get_db') as mock_get_db:
        conn = sqlite3.connect(path)
        mock_get_db.return_value = conn
        yield path, mock_get_db
    os.unlink(path)
```

### Async Test Pattern

```python
@pytest.mark.asyncio
async def test_async_function():
    result = await some_async_function()
    assert result == expected_value
```

### Testing Fallback Behavior

```python
class MockProvider:
    def __init__(self, should_fail=False):
        self.should_fail = should_fail
        self.call_count = 0

    async def execute(self, args):
        self.call_count += 1
        if self.should_fail:
            raise Exception("Provider failed")
        return {"result": "success"}
```

---

## CI/CD Integration

### GitHub Actions Example

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - uses: actions/setup-python@v2
        with:
          python-version: '3.10'
      - name: Install dependencies
        run: |
          cd backend
          pip install -r requirements.txt
          pip install pytest pytest-asyncio pytest-cov
      - name: Run tests
        run: |
          cd backend
          pytest --cov=agents --cov=tools --cov=services --cov-report=xml
      - name: Upload coverage
        uses: codecov/codecov-action@v2
```

### GitLab CI Example

```yaml
test:
  image: python:3.10
  script:
    - cd backend
    - pip install -r requirements.txt
    - pip install pytest pytest-asyncio pytest-cov
    - pytest --cov=agents --cov=tools --cov=services --cov-report=term
  coverage: '/TOTAL.*\s+(\d+%)$/'
```

---

## Writing New Tests

### Test File Structure

```python
"""Tests for [feature name]."""

import pytest
from unittest.mock import AsyncMock

# Test fixtures
@pytest.fixture
def setup_data():
    return {"key": "value"}

# Unit tests
def test_basic_functionality():
    assert True

# Async tests
@pytest.mark.asyncio
async def test_async_functionality():
    result = await async_function()
    assert result is not None

# Integration tests
@pytest.mark.asyncio
async def test_integration_scenario():
    # Test multiple components together
    pass
```

### Naming Conventions

- Test files: `test_*.py`
- Test functions: `test_*`
- Fixtures: descriptive names (e.g., `temp_db`, `mock_provider`)
- Classes: `Test*` (optional, for grouping)

### Assertion Best Practices

```python
# Good: Specific assertions
assert result["status"] == "completed"
assert len(results) == 5
assert "error" in response

# Good: Descriptive messages
assert value > 0, f"Expected positive value, got {value}"

# Avoid: Generic assertions
assert result  # Too vague
```

---

## Test Coverage Goals

### Current Coverage

- **Reliability Features**: 100% (all scenarios covered)
- **Task Persistence**: 95% (edge cases covered)
- **SSE Streaming**: 100% (all event types covered)
- **Integration Flows**: 90% (major scenarios covered)

### Coverage Gaps

- Frontend components (not in scope)
- External API integrations (mocked)
- UI/UX flows (manual testing)

---

## Troubleshooting Tests

### Common Issues

#### Tests Hanging

**Cause**: Async operations not completing

**Solution**:
```python
# Add timeout
event = await asyncio.wait_for(queue.get(), timeout=1.0)

# Check for infinite loops
for i in range(MAX_ITERATIONS):
    if condition:
        break
```

#### Database Conflicts

**Cause**: Tests sharing database state

**Solution**:
```python
# Use temporary databases
@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    # ... setup
    yield path
    os.unlink(path)  # Cleanup
```

#### Flaky Tests

**Cause**: Race conditions, timing issues

**Solution**:
```python
# Add small delays
await asyncio.sleep(0.05)

# Use events for synchronization
completed = asyncio.Event()
# ... do work
completed.set()
await completed.wait()
```

---

## Performance Benchmarks

### Test Execution Times

- Phase 2 tests: ~5 seconds
- Phase 3 tests: ~8 seconds
- Total suite: ~13 seconds

### Load Test Results

- 10 concurrent tasks: ✓ Pass
- 100 rapid events: ✓ Pass
- 10KB chunks: ✓ Pass

---

## Related Documentation

- `README_OPTIMIZATIONS.md` - Project overview
- `docs/reliability.md` - Reliability features
- `docs/deployment.md` - Production deployment
- `backend/tests/README.md` - Test suite overview