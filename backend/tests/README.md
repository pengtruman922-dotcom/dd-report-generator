# DD Report Generator Test Suite

Comprehensive test suite for DD Report Generator Phase 2 (Reliability) and Phase 3 (Persistence & Streaming) features.

## Test Files

### Phase 2: Reliability Tests

#### 1. `test_search_fallback.py` (5 tests)
Tests for search engine fallback chain functionality:
- Provider failure triggers fallback
- Empty results trigger fallback
- All providers fail error handling
- Fallback chain order verification
- No unnecessary fallback on success

#### 2. `test_search_quality.py` (11 tests)
Tests for search quality assessment:
- Empty/None/error result handling
- High quality result scoring
- Low relevance detection
- Recency boost (2024/2025/2026)
- Quality threshold triggering
- Chinese keyword support
- Stop word filtering
- Malformed result handling

#### 3. `test_adaptive_iterations.py` (13 tests)
Tests for adaptive research iterations:
- Company listing status detection (是/否/yes/no/true/false)
- Stock code presence detection
- Unknown company type handling
- Iteration count configuration
- Listed companies get fewer iterations (10)
- Unlisted companies get more iterations (18)
- Default iterations for unknown (15)

#### 4. `test_reliability_integration.py` (8 tests)
Integration tests combining multiple features:
- Quality-based fallback integration
- High quality prevents fallback
- Fallback chain exhaustion
- Empty results with quality check
- Adaptive iterations with company types
- Quality threshold configuration
- Scraper fallback (no quality check)

### Phase 3: Persistence & Streaming Tests

#### 5. `test_task_persistence.py` (16 tests)
Tests for task persistence and recovery:
- Task creation and storage
- Status updates and progress tracking
- Task failure with error messages
- Filtering tasks by status and owner
- Pending task retrieval for recovery
- Task execution lifecycle (start, complete, fail)
- Task cancellation
- Service restart recovery
- Old task cleanup
- Concurrent task execution
- State consistency across operations

#### 6. `test_streaming_output.py` (20 tests)
Tests for SSE streaming functionality:
- Subscriber queue management
- Multiple subscribers per task
- Subscribe/unsubscribe operations
- Event broadcasting to subscribers
- Progress event streaming
- Content chunk streaming
- Completion and error events
- Event ordering guarantees
- Concurrent streaming to multiple tasks
- Queue isolation between tasks
- Late subscriber behavior
- Large chunk handling
- Rapid event sending
- Cleanup after unsubscribe

#### 7. `test_phase3_integration.py` (10 tests)
Integration tests for persistence + streaming:
- Task execution with streaming progress
- Task failure with error events
- Service restart recovery with streaming
- Concurrent tasks with isolated streams
- Streaming interruption recovery
- Task cancellation with cleanup
- Full pipeline flow (persistence + streaming)
- Error propagation through streaming
- Performance under load (10 concurrent tasks)

## Running Tests

### Install Dependencies
```bash
cd backend
pip install pytest pytest-asyncio
```

### Run All Tests
```bash
pytest
```

### Run Phase 2 Tests Only
```bash
pytest tests/test_search_fallback.py tests/test_search_quality.py tests/test_adaptive_iterations.py tests/test_reliability_integration.py
```

### Run Phase 3 Tests Only
```bash
pytest tests/test_task_persistence.py tests/test_streaming_output.py tests/test_phase3_integration.py
```

### Run Specific Test File
```bash
pytest tests/test_task_persistence.py
pytest tests/test_streaming_output.py
pytest tests/test_phase3_integration.py
```

### Run with Verbose Output
```bash
pytest -v
```

### Run with Coverage
```bash
pytest --cov=agents --cov=tools --cov=services --cov=config
```

### Run Only Integration Tests
```bash
pytest tests/test_reliability_integration.py tests/test_phase3_integration.py
```

## Test Coverage Summary

### Phase 2: Reliability (37 tests)
- ✓ Search fallback chain (5 tests)
- ✓ Search quality assessment (11 tests)
- ✓ Adaptive iterations (13 tests)
- ✓ Reliability integration (8 tests)

### Phase 3: Persistence & Streaming (46 tests)
- ✓ Task persistence (16 tests)
- ✓ SSE streaming (20 tests)
- ✓ Phase 3 integration (10 tests)

**Total: 83 tests**

## Key Test Scenarios

### Task Persistence
- ✓ Task state serialization/deserialization
- ✓ Resume from interruption (network failure, crash)
- ✓ Partial progress recovery
- ✓ State consistency validation
- ✓ Concurrent task handling
- ✓ Old task cleanup (30+ days)

### Streaming Output
- ✓ SSE connection handling
- ✓ Progress event ordering
- ✓ Partial result streaming
- ✓ Connection interruption recovery
- ✓ Client reconnection behavior
- ✓ Multiple subscribers per task
- ✓ Queue isolation

### Integration
- ✓ Full pipeline with persistence + streaming
- ✓ Multi-step workflow recovery
- ✓ Error propagation through streaming
- ✓ Performance under load (10+ concurrent tasks)
- ✓ Service restart recovery
- ✓ Task cancellation with cleanup

## Notes

- Tests use mocking to avoid external dependencies
- Async tests use pytest-asyncio
- Integration tests verify end-to-end behavior
- All tests are deterministic and repeatable
- Temporary databases used for persistence tests
- No network calls or external services required
