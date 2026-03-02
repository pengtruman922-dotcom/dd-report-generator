# Reliability Features Documentation

## Overview

This document provides a technical deep dive into the Phase 2 reliability features implemented in the DD Report Generator. These features ensure robust operation even when external services fail or return poor quality results.

## Table of Contents

1. [Fallback Chain Architecture](#fallback-chain-architecture)
2. [Search Quality Assessment](#search-quality-assessment)
3. [Adaptive Research Iterations](#adaptive-research-iterations)
4. [Configuration Guide](#configuration-guide)
5. [Troubleshooting](#troubleshooting)

---

## Fallback Chain Architecture

### Concept

The fallback chain provides automatic failover between multiple service providers. When one provider fails or returns poor results, the system automatically tries the next provider in the chain.

### Key Features

- **Transparent to agents**: The AI agent sees a single tool, unaware of the fallback logic
- **Quality-based triggering**: Fallback occurs on failure OR poor quality results
- **Configurable order**: Customize the fallback sequence per deployment
- **Automatic retry**: No manual intervention required

### Architecture Diagram

```
Agent calls web_search("company name")
         ↓
   FallbackToolProvider
         ↓
    Try Provider 1 (Bocha)
         ↓
    ┌────┴────┐
    │ Success │
    └────┬────┘
         ↓
    Assess Quality
         ↓
    ┌────┴────┐
    │ Good?   │
    └────┬────┘
      Yes│  No
         │   ↓
         │  Try Provider 2 (Baidu)
         │   ↓
         │  ┌────┴────┐
         │  │ Success │
         │  └────┬────┘
         │       ↓
         │  Assess Quality
         │       ↓
         │  ┌────┴────┐
         │  │ Good?   │
         │  └────┬────┘
         │    Yes│  No
         │       │   ↓
         │       │  Try Provider 3...
         │       │
         └───────┴──→ Return Results
```

### Implementation

#### FallbackToolProvider Class

Located in `backend/tools/fallback.py`:

```python
class FallbackToolProvider(ToolProvider):
    def __init__(
        self,
        tool_type: str,
        provider_ids: list[str],
        provider_configs: dict[str, dict[str, Any]],
        primary_provider_id: str,
        quality_assessor: Callable[[Any, str], float] | None = None,
        quality_threshold: float = 0.3,
    ):
        # Initialize multiple providers
        self.providers = [
            registry.create_instance(pid, provider_configs.get(pid, {}))
            for pid in provider_ids
        ]
        self.quality_assessor = quality_assessor
        self.quality_threshold = quality_threshold

    async def execute(self, args: dict[str, Any]) -> Any:
        for provider in self.providers:
            try:
                result = await provider.execute(args)

                # Check validity
                if not self._is_valid_result(result):
                    continue

                # Assess quality (for search only)
                if self.quality_assessor and self.tool_type == "search":
                    quality = self.quality_assessor(result, args.get("query", ""))
                    if quality < self.quality_threshold:
                        continue

                return result  # Success!
            except Exception:
                continue  # Try next provider

        raise Exception("All providers failed")
```

#### Integration with Researcher

In `backend/agents/researcher.py`:

```python
# Build search tool with fallback
if fallback_chain and len(fallback_chain) > 1:
    search_instance = FallbackToolProvider(
        tool_type="search",
        provider_ids=fallback_chain,
        provider_configs=provider_configs,
        primary_provider_id=fallback_chain[0],
        quality_assessor=_assess_search_quality,
        quality_threshold=SEARCH_QUALITY_THRESHOLD,
    )
else:
    search_instance = registry.create_instance(active_search, config)
```

### Supported Providers

#### Search Engines
- **bocha** - Bocha search (good for Chinese content)
- **baidu** - Baidu search (requires API key)
- **bing_china** - Bing China (requires API key)
- **duckduckgo** - DuckDuckGo (free, no API key)

#### Web Scrapers
- **jina_reader** - Jina AI Reader (free, may be blocked in China)
- **local_scraper** - Local scraping with requests/BeautifulSoup

---

## Search Quality Assessment

### Purpose

Proactively detect poor quality search results and trigger fallback, even when the search technically succeeds.

### Quality Scoring Algorithm

Quality score is calculated as a weighted average of three metrics:

```python
quality_score = (count_score * 0.4) + (relevance_score * 0.4) + (recency_score * 0.2)
```

#### 1. Count Score (40% weight)

Measures the number of results returned:

```python
count_score = min(result_count / 10.0, 1.0)
```

- 0 results = 0.0
- 5 results = 0.5
- 10+ results = 1.0

#### 2. Relevance Score (40% weight)

Measures how many results contain query keywords:

```python
query_keywords = set(query.lower().split()) - stop_words
relevant_count = sum(1 for r in results if any(kw in r["title"] + r["snippet"] for kw in query_keywords))
relevance_score = relevant_count / result_count
```

**Chinese Stop Words Filtered:**
- 的, 了, 在, 是, 我, 有, 和, 就, 不, 人, 都, 一, 一个

#### 3. Recency Score (20% weight)

Measures presence of recent years (2024, 2025, 2026):

```python
recent_years = {"2024", "2025", "2026"}
recent_count = sum(1 for r in results if any(year in r["title"] + r["snippet"] for year in recent_years))
recency_score = min(recent_count / 3.0, 1.0)
```

### Quality Threshold

**Default: 0.3**

Results with quality score < 0.3 trigger fallback to the next provider.

### Example Scenarios

#### High Quality (Score: 0.85)
```python
results = [
    {"title": "Test Company 2025 Report", "snippet": "Latest test company data"},
    {"title": "Test Company Analysis 2024", "snippet": "Detailed test analysis"},
    {"title": "Test Company Overview", "snippet": "Complete test information"},
    # ... 7 more relevant results
]
# Count: 1.0, Relevance: 0.9, Recency: 0.67
# Score: 0.4 + 0.36 + 0.13 = 0.89
```

#### Low Quality (Score: 0.15)
```python
results = [
    {"title": "Unrelated Article", "snippet": "Something from 2010"}
]
# Count: 0.1, Relevance: 0.0, Recency: 0.0
# Score: 0.04 + 0.0 + 0.0 = 0.04
```

### Implementation

Located in `backend/agents/researcher.py`:

```python
def _assess_search_quality(results: Any, query: str) -> float:
    if not results or not isinstance(results, list):
        return 0.0

    result_count = len(results)
    count_score = min(result_count / 10.0, 1.0)

    # Relevance scoring
    query_keywords = set(query.lower().split()) - stop_words
    relevant_count = sum(
        1 for r in results
        if isinstance(r, dict) and any(
            kw in (r.get("title", "") + r.get("snippet", "")).lower()
            for kw in query_keywords
        )
    )
    relevance_score = relevant_count / result_count if result_count > 0 else 0.0

    # Recency scoring
    recent_years = {"2024", "2025", "2026"}
    recent_count = sum(
        1 for r in results
        if isinstance(r, dict) and any(
            year in (r.get("title", "") + r.get("snippet", ""))
            for year in recent_years
        )
    )
    recency_score = min(recent_count / 3.0, 1.0)

    return (count_score * 0.4) + (relevance_score * 0.4) + (recency_score * 0.2)
```

---

## Adaptive Research Iterations

### Purpose

Optimize token usage and research time by adjusting iteration count based on company type.

### Iteration Counts

```python
RESEARCH_ITERATIONS = {
    "listed": 10,      # Listed companies (public data readily available)
    "unlisted": 18,    # Unlisted companies (need more research)
    "default": 15,     # Unknown company type
}
```

### Company Type Detection

Located in `backend/agents/researcher.py`:

```python
def _is_company_listed(company_profile: dict[str, Any] | None) -> bool | None:
    if not company_profile:
        return None

    # Check is_listed field
    is_listed = company_profile.get("is_listed", "")
    if isinstance(is_listed, str):
        is_listed = is_listed.strip().lower()

    if is_listed in ("是", "yes", "true", "1", True):
        return True
    if is_listed in ("否", "no", "false", "0", False):
        return False

    # Check for stock code (indicates listed)
    if company_profile.get("stock_code"):
        return True

    return None  # Unknown
```

### Usage in Research Flow

```python
async def research(company_profile, ai_config, ...):
    # Determine iteration count
    is_listed = _is_company_listed(company_profile)
    if is_listed is True:
        max_iterations = RESEARCH_ITERATIONS["listed"]  # 10
    elif is_listed is False:
        max_iterations = RESEARCH_ITERATIONS["unlisted"]  # 18
    else:
        max_iterations = RESEARCH_ITERATIONS["default"]  # 15

    # Run research loop
    for iteration in range(max_iterations):
        # ... research logic
```

### Benefits

- **Listed companies**: Faster (10 iterations), lower cost
  - Public financial data available
  - Annual reports accessible
  - News coverage abundant

- **Unlisted companies**: Thorough (18 iterations), higher quality
  - Limited public information
  - Need multiple search angles
  - Indirect inference required

---

## Configuration Guide

### Basic Configuration

Edit `backend/config.py`:

```python
# Search fallback chain
DEFAULT_TOOLS_CONFIG = {
    "search": {
        "active_provider": "bocha",
        "fallback_chain": ["bocha", "baidu", "bing_china", "duckduckgo"],
        "providers": {
            "bocha": {"api_key": "your-key"},
            "baidu": {"api_key": "your-key", "secret_key": "your-secret"},
            "bing_china": {"api_key": "your-key"},
            "duckduckgo": {}  # No key required
        }
    },
    "scraper": {
        "active_provider": "jina_reader",
        "fallback_chain": ["jina_reader", "local_scraper"],
        "providers": {
            "jina_reader": {},
            "local_scraper": {"timeout": 30, "content_limit": 8000}
        }
    }
}

# Quality threshold
SEARCH_QUALITY_THRESHOLD = 0.3  # Lower = more strict

# Adaptive iterations
RESEARCH_ITERATIONS = {
    "listed": 10,
    "unlisted": 18,
    "default": 15
}
```

### Advanced Configuration

#### Custom Fallback Order

Prioritize providers based on your needs:

```python
# For China deployments
"fallback_chain": ["baidu", "bocha", "bing_china"]

# For international deployments
"fallback_chain": ["duckduckgo", "bing_china", "baidu"]

# Cost-optimized (free first)
"fallback_chain": ["duckduckgo", "jina_reader", "bocha"]
```

#### Adjust Quality Threshold

```python
# Strict (more fallbacks, higher quality)
SEARCH_QUALITY_THRESHOLD = 0.5

# Lenient (fewer fallbacks, faster)
SEARCH_QUALITY_THRESHOLD = 0.2

# Disable quality-based fallback
SEARCH_QUALITY_THRESHOLD = 0.0
```

#### Custom Iteration Counts

```python
# Faster research (lower cost)
RESEARCH_ITERATIONS = {
    "listed": 8,
    "unlisted": 12,
    "default": 10
}

# More thorough research (higher quality)
RESEARCH_ITERATIONS = {
    "listed": 12,
    "unlisted": 25,
    "default": 18
}
```

---

## Troubleshooting

### Issue: All Providers Failing

**Symptoms:**
- Error: "All X providers failed"
- No search results returned

**Diagnosis:**
```bash
# Check provider configurations
python -c "from agents.researcher import validate_tools_config; print(validate_tools_config())"

# Test individual providers
pytest backend/tests/test_search_fallback.py -v
```

**Solutions:**
1. Verify API keys are correct
2. Check network connectivity
3. Test providers individually
4. Review provider rate limits

### Issue: Poor Search Quality

**Symptoms:**
- Irrelevant search results
- Frequent fallbacks
- Low quality scores in logs

**Diagnosis:**
```python
# Enable debug logging
import logging
logging.getLogger("agents.researcher").setLevel(logging.DEBUG)

# Check quality scores
# Look for: "Search quality: 0.XX (count=..., relevance=..., recency=...)"
```

**Solutions:**
1. Adjust quality threshold
2. Change primary provider
3. Optimize search queries in prompt
4. Add more providers to fallback chain

### Issue: Excessive Token Usage

**Symptoms:**
- High API costs
- Long research times
- Many iterations

**Diagnosis:**
```python
# Check iteration counts
from config import RESEARCH_ITERATIONS
print(RESEARCH_ITERATIONS)

# Review company type detection
from agents.researcher import _is_company_listed
print(_is_company_listed(your_company_profile))
```

**Solutions:**
1. Reduce iteration counts
2. Improve company type detection
3. Optimize research prompt
4. Use quality threshold to skip poor results early

### Issue: Fallback Not Triggering

**Symptoms:**
- Poor results not triggering fallback
- Only first provider used

**Diagnosis:**
```bash
# Check fallback configuration
grep -A 5 "fallback_chain" backend/config.py

# Verify quality assessor is enabled
grep "quality_assessor" backend/agents/researcher.py
```

**Solutions:**
1. Ensure fallback_chain has multiple providers
2. Verify quality_assessor is passed to FallbackToolProvider
3. Check quality threshold is not too low
4. Review logs for quality scores

---

## Monitoring and Logging

### Key Log Messages

```
INFO: Trying provider bocha (1/4)
INFO: Search quality: 0.25 (count=0.30, relevance=0.20, recency=0.00)
WARNING: Provider bocha quality too low: 0.25 < 0.30
INFO: Trying provider baidu (2/4)
INFO: Search quality: 0.75 (count=0.80, relevance=0.70, recency=0.67)
INFO: Fallback succeeded with baidu
```

### Metrics to Track

1. **Fallback Rate**: % of searches requiring fallback
2. **Average Quality Score**: Overall search quality
3. **Provider Success Rate**: Success rate per provider
4. **Iteration Count Distribution**: Listed vs unlisted vs default

---

## Best Practices

1. **Provider Order**: Put most reliable/fastest providers first
2. **API Keys**: Keep backup providers configured even if not primary
3. **Quality Threshold**: Start with 0.3, adjust based on results
4. **Iteration Counts**: Balance cost vs quality for your use case
5. **Testing**: Run test suite after configuration changes
6. **Monitoring**: Track fallback rates and quality scores in production

---

## Related Documentation

- `README_OPTIMIZATIONS.md` - Project overview
- `docs/testing.md` - Test suite guide
- `docs/deployment.md` - Production deployment
- `backend/tests/README.md` - Test documentation