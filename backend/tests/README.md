# Phase 2 Reliability Tests

Comprehensive test suite for DD Report Generator Phase 2 reliability features.

## Test Files

### 1. `test_search_fallback.py`
Tests for search engine fallback chain functionality:
- Provider failure triggers fallback
- Empty results trigger fallback
- All providers fail error handling
- Fallback chain order verification
- No unnecessary fallback on success

### 2. `test_search_quality.py`
Tests for search quality assessment:
- Empty/None/error result handling
- High quality result scoring
- Low relevance detection
- Recency boost (2024/2025/2026)
- Quality threshold triggering
- Chinese keyword support
- Stop word filtering
- Malformed result handling

### 3. `test_adaptive_iterations.py`
Tests for adaptive research iterations:
- Company listing status detection (是/否/yes/no/true/false)
- Stock code presence detection
- Unknown company type handling
- Iteration count configuration
- Listed companies get fewer iterations (10)
- Unlisted companies get more iterations (18)
- Default iterations for unknown (15)

### 4. `test_reliability_integration.py`
Integration tests combining multiple features:
- Quality-based fallback integration
- High quality prevents fallback
- Fallback chain exhaustion
- Empty results with quality check
- Adaptive iterations with company types
- Quality threshold configuration
- Scraper fallback (no quality check)

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

### Run Specific Test File
```bash
pytest tests/test_search_fallback.py
pytest tests/test_search_quality.py
pytest tests/test_adaptive_iterations.py
pytest tests/test_reliability_integration.py
```

### Run with Verbose Output
```bash
pytest -v
```

### Run with Coverage (if pytest-cov installed)
```bash
pytest --cov=agents --cov=tools --cov=config
```

### Run Only Integration Tests
```bash
pytest tests/test_reliability_integration.py
```

## Test Coverage

### Search Fallback Chain
- ✓ Provider failure handling
- ✓ Empty result handling
- ✓ Chain order verification
- ✓ Error propagation
- ✓ Success short-circuit

### Search Quality Assessment
- ✓ Quality scoring algorithm (count 40%, relevance 40%, recency 20%)
- ✓ Threshold-based triggering (< 0.3)
- ✓ Chinese language support
- ✓ Edge case handling
- ✓ Malformed data resilience

### Adaptive Iterations
- ✓ Company type detection
- ✓ Iteration count mapping
- ✓ Configuration validation
- ✓ Edge cases (None, empty, unknown)

### Integration
- ✓ Quality-based fallback flow
- ✓ Multi-provider scenarios
- ✓ Configuration integration
- ✓ Tool type differentiation (search vs scraper)

## Expected Results

All tests should pass with the Phase 2 implementations:
- 5 tests in `test_search_fallback.py`
- 11 tests in `test_search_quality.py`
- 13 tests in `test_adaptive_iterations.py`
- 8 tests in `test_reliability_integration.py`

**Total: 37 tests**

## Notes

- Tests use mocking to avoid external dependencies
- Async tests use pytest-asyncio
- Integration tests verify end-to-end behavior
- All tests are deterministic and repeatable
