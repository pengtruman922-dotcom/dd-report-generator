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

# Default FastGPT config
DEFAULT_FASTGPT_CONFIG = {
    "enabled": True,
    "api_url": "https://ai.mpgroup.cn:3100/api/core/dataset",
    "api_key": "Bearer openapi-o7LmYAiqfKyHLMRTsIPb7jk18jxZkW4rrswNdBSaZzG16tOdo0UQu6kanU5a",
    "dataset_id": "695dd01cbe98e4bfdd29bd92",
}

# Researcher agent limits
MAX_TOOL_ITERATIONS = 15
JINA_CONTENT_LIMIT = 8000  # chars


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
