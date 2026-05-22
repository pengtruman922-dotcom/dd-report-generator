"""AI configuration settings endpoints."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from openai import AsyncOpenAI
from pydantic import BaseModel

from auth import require_admin
from config import load_settings, save_settings, DEFAULT_AI_CONFIG, DEFAULT_FASTGPT_CONFIG
from services.model_workbench import (
    build_workbench,
    get_node_definition,
    resolve_node_provider_config,
)

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
    researcher: StepConfig = StepConfig()
    matcher_agent: Optional[StepConfig] = None
    tracking_processor: Optional[StepConfig] = None
    info_chunk_writer: Optional[StepConfig] = None
    index_builder: Optional[StepConfig] = None
    rating_agent: Optional[StepConfig] = None
    fastgpt: Optional[FastGPTConfig] = None
    intake_agent: Optional[IntakeAgentConfig] = None


class ModelWorkbenchUpdate(BaseModel):
    ai_config: dict[str, Any]
    prompt_overrides: dict[str, str] = {}


class ModelConnectionTestRequest(BaseModel):
    node_id: str
    ai_config: dict[str, Any]


@router.get("")
async def get_settings(admin: dict = Depends(require_admin)):
    """Return current AI + FastGPT + intake_agent configuration, merged with defaults."""
    settings = load_settings()
    stored = settings.get("ai_config", {}) or {}
    merged = {key: {**default_val, **(stored.get(key, {}) or {})} for key, default_val in DEFAULT_AI_CONFIG.items()}
    merged["fastgpt"] = {**DEFAULT_FASTGPT_CONFIG, **(settings.get("fastgpt", {}) or {})}
    merged["intake_agent"] = merged.pop("intake_agent")
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


@router.get("/model-workbench")
async def get_model_workbench(admin: dict = Depends(require_admin)):
    settings = load_settings()
    return build_workbench(settings)


@router.put("/model-workbench")
async def update_model_workbench(payload: ModelWorkbenchUpdate, admin: dict = Depends(require_admin)):
    settings = load_settings()
    settings["ai_config"] = payload.ai_config
    settings["prompt_overrides"] = {
        key: value
        for key, value in payload.prompt_overrides.items()
        if isinstance(value, str) and value.strip()
    }
    save_settings(settings)
    return {"status": "ok"}


@router.post("/model-workbench/test-node")
async def test_model_workbench_node(
    payload: ModelConnectionTestRequest,
    admin: dict = Depends(require_admin),
):
    node_def = get_node_definition(payload.node_id)
    if not node_def:
        raise HTTPException(status_code=404, detail="Node not found")

    try:
        resolved = resolve_node_provider_config(payload.node_id, payload.ai_config)
    except KeyError:
        raise HTTPException(status_code=404, detail="Node not found")

    base_url = str(resolved.get("base_url") or "").strip()
    api_key = str(resolved.get("api_key") or "").strip()
    model = str(resolved.get("model") or "").strip()

    if not base_url:
        raise HTTPException(status_code=400, detail="Base URL 未配置")
    if not model:
        raise HTTPException(status_code=400, detail="模型名称未配置")
    if not api_key:
        raise HTTPException(status_code=400, detail="API Key 未配置")

    client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=20.0)

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "ping"}],
            temperature=0,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"连接失败: {exc}")

    usage = getattr(response, "usage", None)
    return {
        "ok": True,
        "node_id": payload.node_id,
        "node_label": node_def["label"],
        "message": "连接测试成功",
        "provider": {
            "base_url": base_url,
            "model": model,
            "base_url_source": resolved.get("base_url_source"),
            "model_source": resolved.get("model_source"),
            "api_key_source": resolved.get("api_key_source"),
        },
        "usage": {
            "prompt_tokens": getattr(usage, "prompt_tokens", 0) if usage else 0,
            "completion_tokens": getattr(usage, "completion_tokens", 0) if usage else 0,
            "total_tokens": getattr(usage, "total_tokens", 0) if usage else 0,
        },
    }
