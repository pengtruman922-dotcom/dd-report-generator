"""Prompt default/override helpers for the model settings workbench."""

from __future__ import annotations

from typing import Callable

from config import load_settings


def get_prompt_overrides(settings: dict | None = None) -> dict[str, str]:
    payload = settings or load_settings()
    return payload.get("prompt_overrides", {}) or {}


def get_prompt(prompt_id: str, default_prompt: str, settings: dict | None = None) -> str:
    overrides = get_prompt_overrides(settings)
    value = overrides.get(prompt_id)
    if isinstance(value, str) and value.strip():
        return value
    return default_prompt


def get_prompt_override(prompt_id: str, settings: dict | None = None) -> str | None:
    overrides = get_prompt_overrides(settings)
    value = overrides.get(prompt_id)
    if isinstance(value, str) and value.strip():
        return value
    return None


def get_chunk_prompt(chunk_id: str, default_getter: Callable[[str], str], settings: dict | None = None) -> str:
    return get_prompt(chunk_id, default_getter(chunk_id), settings=settings)
