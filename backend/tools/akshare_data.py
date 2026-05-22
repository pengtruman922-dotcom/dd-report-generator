"""AkShare 数据源 — 查询上市公司历史行情数据（免费，无需API Key）.

注意：AkShare 依赖第三方网站接口，数据源不稳定，部分功能可能失效。
当前仅提供历史行情查询功能。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from datetime import datetime, timedelta

from tools.base import ToolProvider
from tools.registry import register

log = logging.getLogger(__name__)


def _run_sync(fn, *args, timeout=30):
    """Run a sync function in a thread executor with timeout."""
    import asyncio
    loop = asyncio.get_event_loop()
    return asyncio.wait_for(
        loop.run_in_executor(None, fn, *args),
        timeout=timeout
    )


def _query_stock_hist(stock_code: str, days: int = 90) -> list[dict]:
    """Query historical stock price data via akshare (runs in thread)."""
    try:
        import akshare as ak
        import pandas as pd
    except ImportError:
        return [{"error": "akshare 未安装，请运行 pip install akshare"}]

    code = stock_code.strip()

    # Calculate date range
    end_date = datetime.now()
    start_date = end_date - timedelta(days=days)

    try:
        df = ak.stock_zh_a_hist(
            symbol=code,
            period='daily',
            start_date=start_date.strftime('%Y%m%d'),
            end_date=end_date.strftime('%Y%m%d'),
            adjust=''
        )

        if df is None or df.empty:
            return [{"error": "未查询到数据"}]

        # Return recent records (newest first)
        results = []
        for _, row in df.tail(min(30, len(df))).iterrows():
            results.append({
                "日期": str(row.get("日期", "")),
                "股票代码": str(row.get("股票代码", code)),
                "开盘": float(row.get("开盘", 0)) if pd.notna(row.get("开盘")) else None,
                "收盘": float(row.get("收盘", 0)) if pd.notna(row.get("收盘")) else None,
                "最高": float(row.get("最高", 0)) if pd.notna(row.get("最高")) else None,
                "最低": float(row.get("最低", 0)) if pd.notna(row.get("最低")) else None,
                "成交量": int(row.get("成交量", 0)) if pd.notna(row.get("成交量")) else None,
                "成交额": float(row.get("成交额", 0)) if pd.notna(row.get("成交额")) else None,
                "涨跌幅": float(row.get("涨跌幅", 0)) if pd.notna(row.get("涨跌幅")) else None,
            })

        # Reverse to newest first
        results.reverse()
        return results

    except Exception as e:
        log.warning("akshare stock_zh_a_hist failed for %s: %s", code, e)
        return [{"error": f"查询失败: {e}"}]


@register
class AkShareProvider(ToolProvider):
    tool_type = "datasource"
    provider_id = "akshare"
    display_name = "AkShare 行情数据"
    description = "查询A股上市公司历史行情数据（股价、成交量等），免费无需API Key。注意：数据源不稳定，可能失败。"
    target_company_type = "listed"

    @classmethod
    def config_schema(cls) -> list[dict[str, Any]]:
        return []  # No config needed — free library

    def openai_function_def(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": "akshare_query",
                "description": (
                    "Query historical stock price data of Chinese A-share listed companies via AkShare. "
                    "Returns daily OHLC (open/high/low/close) prices, volume, and turnover. "
                    "Free, no API key needed. Note: Data source may be unstable."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "stock_code": {
                            "type": "string",
                            "description": "Stock code, e.g. '000001' or '600519'.",
                        },
                        "days": {
                            "type": "integer",
                            "description": "Number of days to look back (default 90, returns up to 30 most recent records).",
                            "default": 90,
                        },
                    },
                    "required": ["stock_code"],
                },
            },
        }

    async def execute(self, args: dict[str, Any]) -> Any:
        stock_code = args["stock_code"]
        days = args.get("days", 90)

        try:
            return await _run_sync(_query_stock_hist, stock_code, days, timeout=20)
        except asyncio.TimeoutError:
            log.warning("akshare query timeout for %s", stock_code)
            return [{"error": "查询超时（20秒），数据源可能不可用"}]
        except Exception as e:
            log.warning("akshare query failed for %s: %s", stock_code, e)
            return [{"error": f"查询失败: {e}"}]
