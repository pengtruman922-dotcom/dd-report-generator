"""Abstract base class for tool providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ToolProvider(ABC):
    """Base class that every search / scraper / datasource provider must extend."""

    tool_type: str  # "search" | "scraper" | "datasource"
    provider_id: str
    display_name: str
    description: str = ""
    # For datasource providers: which company types this source applies to.
    # "all" = any company, "listed" = listed companies only, "unlisted" = unlisted only.
    target_company_type: str = "all"

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}

    # ── Must implement ──────────────────────────────────────────

    @classmethod
    @abstractmethod
    def config_schema(cls) -> list[dict[str, Any]]:
        """Return a list of config field definitions.

        Each item: {"key": str, "label": str, "type": "text"|"password"|"number",
                     "required": bool, "default": Any, "description": str}
        """

    @abstractmethod
    async def execute(self, args: dict[str, Any]) -> Any:
        """Execute the tool with the given arguments."""

    @abstractmethod
    def openai_function_def(self) -> dict[str, Any]:
        """Return an OpenAI function-calling tool definition dict."""

    # ── Optional ────────────────────────────────────────────────

    def validate_config(self) -> list[str]:
        """Return a list of validation error messages (empty = valid)."""
        errors = []
        for field in self.config_schema():
            if field.get("required") and not self.config.get(field["key"]):
                errors.append(f"{field['label']} is required")
        return errors
