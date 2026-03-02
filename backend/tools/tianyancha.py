"""天眼查 API 数据源 — 查询企业工商信息（需要API Key）."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from tools.base import ToolProvider
from tools.registry import register

log = logging.getLogger(__name__)

_TIANYANCHA_API = "http://open.api.tianyancha.com/services/open"


@register
class TianyanchaProvider(ToolProvider):
    tool_type = "datasource"
    provider_id = "tianyancha"
    display_name = "天眼查"
    description = "查询企业工商信息、股东、对外投资等（需API Key，适用所有企业）"
    target_company_type = "all"

    @classmethod
    def config_schema(cls) -> list[dict[str, Any]]:
        return [
            {
                "key": "api_key",
                "label": "API Token",
                "type": "password",
                "required": True,
                "default": "",
                "description": "天眼查开放平台 API Token",
            },
        ]

    def openai_function_def(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "tianyancha_query",
                "description": (
                    "Query Chinese company business registration info via Tianyancha API. "
                    "Returns registration details, shareholders, key personnel, etc. "
                    "Works for both listed and unlisted companies."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "company_name": {
                            "type": "string",
                            "description": "Full company name in Chinese.",
                        },
                        "query_type": {
                            "type": "string",
                            "description": (
                                "Type of query: '基本信息' (basic info), "
                                "'股东' (shareholders), '对外投资' (investments). "
                                "Default: '基本信息'."
                            ),
                        },
                    },
                    "required": ["company_name"],
                },
            },
        }

    async def execute(self, args: dict[str, Any]) -> Any:
        company_name = args["company_name"]
        query_type = args.get("query_type", "基本信息")
        api_key = self.config.get("api_key", "")

        headers = {"Authorization": api_key}

        endpoint_map = {
            "基本信息": "/ic/baseinfo/normal",
            "股东": "/ic/holder/2.0",
            "对外投资": "/ic/inverst/2.0",
        }
        path = endpoint_map.get(query_type, "/ic/baseinfo/normal")

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"{_TIANYANCHA_API}{path}",
                headers=headers,
                params={"keyword": company_name},
            )
            resp.raise_for_status()
            data = resp.json()

        result = data.get("result", {})
        if not result:
            return {"error": data.get("reason", "未找到结果")}
        return result
