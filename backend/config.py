"""Global configuration for DD Report Generator backend."""

from copy import deepcopy
import json
import os
from pathlib import Path

# Base paths
BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = Path(os.environ.get("APP_UPLOAD_DIR", BASE_DIR / "uploads"))
OUTPUT_DIR = Path(os.environ.get("APP_OUTPUT_DIR", BASE_DIR / "outputs"))
DATA_DIR = Path(os.environ.get("APP_DATA_DIR", BASE_DIR / "data"))
SETTINGS_FILE = Path(os.environ.get("APP_SETTINGS_FILE", BASE_DIR / "settings.json"))

UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)
DATA_DIR.mkdir(exist_ok=True)

# Default AI config (per-step, using DashScope Qwen)
DEFAULT_AI_CONFIG = {
    "researcher": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key": "",
        "model": "qwen3-max",
    },
    "intake_agent": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key": "",
        "model": "qwen3.5-plus",
        "max_crawl_depth": 3,
        "default_mode": "auto",
        "core_fields_trigger_research": ["description", "company_intro"],
        "research_data_expire_days": 90,
    },
    "matcher_agent": {},
    "tracking_processor": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key": "",
        "model": "qwen3-max",
    },
    "info_chunk_writer": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key": "",
        "model": "qwen3-max",
    },
    "index_builder": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key": "",
        "model": "qwen3.5-plus",
    },
    "rating_agent": {},
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
            "multi_search_engine": {
                "enabled_engines_cn": "bing_cn,bing_int,360,sogou,wechat",
                "max_results_per_engine": 5,
                "max_merged_results": 10,
                "request_delay_ms": 1200,
                "timeout": 15,
            },
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


def _merge_dict(defaults: dict, stored: dict | None) -> dict:
    merged = deepcopy(defaults)
    for key, value in (stored or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dict(merged[key], value)
        else:
            merged[key] = value
    return merged


def sanitize_settings(raw_settings: dict | None) -> dict:
    """Normalize settings and actively remove retired legacy keys."""
    settings = deepcopy(raw_settings) if isinstance(raw_settings, dict) else {}

    stored_ai_config = settings.get("ai_config", {}) or {}
    cleaned_ai_config: dict[str, dict] = {}
    for key, default_value in DEFAULT_AI_CONFIG.items():
        cleaned_ai_config[key] = _merge_dict(default_value, stored_ai_config.get(key, {}))
    settings["ai_config"] = cleaned_ai_config

    settings["fastgpt"] = _merge_dict(DEFAULT_FASTGPT_CONFIG, settings.get("fastgpt", {}))
    settings["tools"] = _merge_dict(DEFAULT_TOOLS_CONFIG, settings.get("tools", {}))

    prompt_overrides = settings.get("prompt_overrides", {}) or {}
    settings["prompt_overrides"] = {
        key: value for key, value in prompt_overrides.items() if isinstance(key, str) and isinstance(value, str)
    }

    return settings


def load_settings() -> dict:
    """Load saved settings or return defaults."""
    if SETTINGS_FILE.exists():
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            raw_settings = json.load(f)
        cleaned = sanitize_settings(raw_settings)
        if cleaned != raw_settings:
            save_settings(cleaned)
        return cleaned
    return sanitize_settings({})


def save_settings(settings: dict) -> None:
    """Persist settings to disk."""
    settings = sanitize_settings(settings)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)
