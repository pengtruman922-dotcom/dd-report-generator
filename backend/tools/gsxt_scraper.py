"""GSXT (国家企业信用信息公示系统) scraper - free company registration data."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from bs4 import BeautifulSoup

from tools.base import ToolProvider
from tools.registry import register

log = logging.getLogger(__name__)

_GSXT_SEARCH_URL = "http://www.gsxt.gov.cn/index.html"


@register
class GSXTScraper(ToolProvider):
    tool_type = "datasource"
    provider_id = "gsxt"
    display_name = "国家企业信用信息公示系统"
    description = "免费查询企业工商注册信息（注册资本、成立日期、法人、经营范围等）"
    target_company_type = "all"  # Works for all companies

    @classmethod
    def config_schema(cls) -> list[dict[str, Any]]:
        return [
            {
                "key": "timeout",
                "label": "请求超时时间（秒）",
                "type": "number",
                "required": False,
                "default": 30,
                "description": "HTTP 请求超时时间",
            },
        ]

    def openai_function_def(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "gsxt_query",
                "description": (
                    "Query the National Enterprise Credit Information Publicity System (GSXT) "
                    "for company registration data. Returns: registered capital, establishment date, "
                    "legal representative, business scope, registration status, etc. "
                    "Free and official source."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "company_name": {
                            "type": "string",
                            "description": "The full company name to query (Chinese name preferred).",
                        },
                    },
                    "required": ["company_name"],
                },
            },
        }

    async def execute(self, args: dict[str, Any]) -> Any:
        """Query GSXT for company registration information.

        Note: GSXT has anti-scraping measures. This is a simplified implementation
        that may need to be enhanced with proper headers, cookies, or API access.
        """
        company_name = args["company_name"]
        timeout = int(self.config.get("timeout", 30))

        try:
            # Note: GSXT requires complex anti-scraping handling in production
            # This is a simplified version that demonstrates the structure
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                # Search for company
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                }

                # GSXT search endpoint (simplified - actual implementation needs more work)
                search_params = {
                    "keyword": company_name,
                }

                # Note: This is a placeholder implementation
                # Real GSXT scraping requires handling:
                # 1. CAPTCHA verification
                # 2. Dynamic JavaScript rendering
                # 3. Session cookies
                # 4. Rate limiting
                log.warning("GSXT scraper is a simplified implementation - may not work in production")

                # For now, return a structured response indicating the limitation
                return {
                    "source": "GSXT",
                    "company_name": company_name,
                    "status": "limited_implementation",
                    "message": (
                        "GSXT scraping requires advanced anti-scraping handling. "
                        "Consider using: 1) Official GSXT API (if available), "
                        "2) Third-party data providers (Tianyancha, Qichacha), "
                        "3) Selenium/Playwright for browser automation."
                    ),
                    "data": {
                        "registered_capital": None,
                        "establishment_date": None,
                        "legal_representative": None,
                        "business_scope": None,
                        "registration_status": None,
                        "unified_social_credit_code": None,
                    },
                }

        except Exception as e:
            log.error(f"GSXT query failed for {company_name}: {e}")
            return {
                "source": "GSXT",
                "company_name": company_name,
                "error": str(e),
                "data": None,
            }
