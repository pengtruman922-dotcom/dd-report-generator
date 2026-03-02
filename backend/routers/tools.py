"""Tool configuration API endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from auth import require_admin
from config import load_settings, save_settings
from tools import registry

router = APIRouter()


class ToolsConfigPayload(BaseModel):
    tools: dict[str, Any]


@router.get("/providers")
async def list_providers(admin: dict = Depends(require_admin)):
    """List all registered tool providers with their config schemas."""
    return {
        "search": registry.list_providers("search"),
        "scraper": registry.list_providers("scraper"),
        "datasource": registry.list_providers("datasource"),
    }


@router.get("")
async def get_tools_config(admin: dict = Depends(require_admin)):
    """Return the current tools configuration."""
    settings = load_settings()
    return settings.get("tools", {})


@router.put("")
async def save_tools_config(payload: ToolsConfigPayload, admin: dict = Depends(require_admin)):
    """Save tools configuration (admin only)."""
    settings = load_settings()
    settings["tools"] = payload.tools
    save_settings(settings)
    return {"status": "ok"}
