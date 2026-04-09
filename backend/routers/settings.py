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


class IntakeAgentConfig(BaseModel):
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    api_key: str = ""
    model: str = "qwen3.5-plus"
    max_crawl_depth: int = 3
    default_mode: str = "auto"
    core_fields_trigger_research: list[str] = ["description", "company_intro"]
    research_data_expire_days: int = 90


class AISettings(BaseModel):
    extractor: StepConfig = StepConfig()
    researcher: StepConfig = StepConfig()
    writer: StepConfig = StepConfig()
    field_extractor: StepConfig = StepConfig()
    chunker: StepConfig = StepConfig()
    fastgpt: Optional[FastGPTConfig] = None
    intake_agent: Optional[IntakeAgentConfig] = None


@router.get("")
async def get_settings(admin: dict = Depends(require_admin)):
    """Return current AI + FastGPT + intake_agent configuration, merged with defaults."""
    settings = load_settings()
    stored = settings.get("ai_config", {})
    # Merge stored config on top of defaults so newly added steps always appear
    merged = {}
    for key, default_val in DEFAULT_AI_CONFIG.items():
        if key == "intake_agent":
            # intake_agent returned as a top-level key matching frontend expectation
            merged["intake_agent"] = {**default_val, **(stored.get("intake_agent", {}))}
        else:
            merged[key] = {**default_val, **(stored.get(key, {}))}
    # Include FastGPT config
    fastgpt_stored = settings.get("fastgpt", {})
    merged["fastgpt"] = {**DEFAULT_FASTGPT_CONFIG, **fastgpt_stored}
    return merged


@router.put("")
async def update_settings(cfg: AISettings, admin: dict = Depends(require_admin)):
    """Save AI + FastGPT + intake_agent configuration."""
    settings = load_settings()
    data = cfg.model_dump()
    # Extract fastgpt and intake_agent and save separately
    fastgpt = data.pop("fastgpt", None)
    intake_agent = data.pop("intake_agent", None)
    settings["ai_config"] = data
    if fastgpt is not None:
        settings["fastgpt"] = fastgpt
    if intake_agent is not None:
        # Store intake_agent inside ai_config to align with load_settings structure
        settings["ai_config"]["intake_agent"] = intake_agent
    save_settings(settings)
    return {"status": "ok"}
