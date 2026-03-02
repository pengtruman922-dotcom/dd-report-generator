"""Global configuration for DD Report Generator backend."""

import json
import os
from pathlib import Path

# Base paths
BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
DATA_DIR = BASE_DIR / "data"
SETTINGS_FILE = BASE_DIR / "settings.json"

UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

# Default AI config (per-step, using DashScope Qwen)
DEFAULT_AI_CONFIG = {
    "extractor": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key": "",
        "model": "qwen3-max",
    },
    "researcher": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key": "",
        "model": "qwen3-max",
    },
    "writer": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key": "",
        "model": "qwen3-max",
    },
    "field_extractor": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key": "",
        "model": "qwen3-max",
    },
    "chunker": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key": "",
        "model": "qwen3-max",
    },
}

# Default FastGPT config (no hardcoded keys)
DEFAULT_FASTGPT_CONFIG = {
    "enabled": True,
    "api_url": "",
    "api_key": "",
    "dataset_id": "",
}

# Default tools config
DEFAULT_TOOLS_CONFIG = {
    "search": {
        "active_provider": "bocha",  # Changed from duckduckgo - better for Chinese content
        # Fallback chain: list of providers to try in order (optional)
        # If not specified, only active_provider is used
        "fallback_chain": ["bocha", "baidu", "bing_china", "duckduckgo"],
        "providers": {
            "duckduckgo": {},
            "bing_china": {"api_key": ""},
            "baidu": {"api_key": "", "secret_key": ""},
            "bocha": {"api_key": ""},
        },
    },
    "scraper": {
        "active_provider": "jina_reader",
        # Fallback chain for scrapers
        "fallback_chain": ["jina_reader", "local_scraper"],
        "providers": {
            "jina_reader": {},
            "local_scraper": {"timeout": 30, "content_limit": 8000},
        },
    },
    "datasource": {
        "active_providers": [],
        "providers": {
            "cninfo": {},
            "akshare": {},
            "tianyancha": {"api_key": ""},
            "gsxt": {"timeout": 30},
        },
    },
}

# Researcher agent limits
MAX_TOOL_ITERATIONS = 15
RESEARCH_ITERATIONS = {
    "listed": 10,      # Listed companies: less research needed (public data available)
    "unlisted": 18,    # Unlisted companies: more research needed (less public data)
    "default": 15,     # Unknown company type
}
JINA_CONTENT_LIMIT = 8000  # chars

# Search quality thresholds
SEARCH_QUALITY_THRESHOLD = 0.3  # Trigger fallback if quality score < 0.3
MIN_SEARCH_RESULTS = 3  # Minimum number of results for acceptable quality

# CORS origins (from env or default)
CORS_ORIGINS = os.environ.get(
    "CORS_ORIGINS", "http://localhost:5173"
).split(",")


def load_settings() -> dict:
    """Load saved settings or return defaults."""
    if SETTINGS_FILE.exists():
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"ai_config": DEFAULT_AI_CONFIG}


def save_settings(settings: dict) -> None:
    """Persist settings to disk."""
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)
