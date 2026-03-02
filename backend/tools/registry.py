"""Singleton registry for tool providers."""

from __future__ import annotations

from typing import Any, Type

from tools.base import ToolProvider

_registry: dict[str, Type[ToolProvider]] = {}


def register(cls: Type[ToolProvider]) -> Type[ToolProvider]:
    """Class decorator — registers a ToolProvider subclass."""
    _registry[cls.provider_id] = cls
    return cls


def list_providers(tool_type: str | None = None) -> list[dict[str, Any]]:
    """Return metadata for all registered providers, optionally filtered."""
    result = []
    for pid, cls in _registry.items():
        if tool_type and cls.tool_type != tool_type:
            continue
        result.append({
            "provider_id": pid,
            "tool_type": cls.tool_type,
            "display_name": cls.display_name,
            "description": cls.description,
            "config_schema": cls.config_schema(),
            "target_company_type": cls.target_company_type,
        })
    return result


def create_instance(provider_id: str, config: dict[str, Any] | None = None) -> ToolProvider:
    """Instantiate a registered provider with the given config."""
    cls = _registry.get(provider_id)
    if cls is None:
        raise KeyError(f"Unknown provider: {provider_id}")
    return cls(config)


def get_provider_class(provider_id: str) -> Type[ToolProvider] | None:
    """Return the class for a provider_id, or None."""
    return _registry.get(provider_id)
