"""AI configuration settings endpoints."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from auth import require_admin
from config import load_settings, save_settings, DEFAULT_AI_CONFIG, DEFAULT_FASTGPT_CONFIG

router = APIRouter()


class StepConfig(BaseModel):
    base_url: str = ""
    api_key: str = ""
    model: str = ""


class FastGPTConfig(BaseModel):
    enabled: bool = True
    api_url: str = ""
    api_key: str = ""
    dataset_id: str = ""


class AISettings(BaseModel):
    extractor: StepConfig = StepConfig()
    researcher: StepConfig = StepConfig()
    writer: StepConfig = StepConfig()
    field_extractor: StepConfig = StepConfig()
    chunker: StepConfig = StepConfig()
    fastgpt: Optional[FastGPTConfig] = None


@router.get("")
async def get_settings(admin: dict = Depends(require_admin)):
    """Return current AI + FastGPT configuration, merged with defaults."""
    settings = load_settings()
    stored = settings.get("ai_config", {})
    # Merge stored config on top of defaults so newly added steps always appear
    merged = {}
    for key, default_val in DEFAULT_AI_CONFIG.items():
        merged[key] = {**default_val, **(stored.get(key, {}))}
    # Include FastGPT config
    fastgpt_stored = settings.get("fastgpt", {})
    merged["fastgpt"] = {**DEFAULT_FASTGPT_CONFIG, **fastgpt_stored}
    return merged


@router.put("")
async def update_settings(cfg: AISettings, admin: dict = Depends(require_admin)):
    """Save AI + FastGPT configuration."""
    settings = load_settings()
    data = cfg.model_dump()
    # Extract fastgpt and save separately
    fastgpt = data.pop("fastgpt", None)
    settings["ai_config"] = data
    if fastgpt is not None:
        settings["fastgpt"] = fastgpt
    save_settings(settings)
    return {"status": "ok"}
