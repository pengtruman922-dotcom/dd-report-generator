"""AkShare 数据源 — 查询上市公司财务数据、行情等（免费，无需API Key）."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from tools.base import ToolProvider
from tools.registry import register

log = logging.getLogger(__name__)


def _run_sync(fn, *args):
    """Run a sync function in a thread executor."""
    import asyncio
    loop = asyncio.get_event_loop()
    return loop.run_in_executor(None, fn, *args)


def _query_financial(stock_code: str, report_type: str, max_results: int) -> list[dict]:
    """Query financial data via akshare (runs in thread)."""
    try:
        import akshare as ak
        import pandas as pd
    except ImportError:
        return [{"error": "akshare 未安装，请运行 pip install akshare"}]

    results = []
    code = stock_code.strip()

    try:
        if report_type in ("利润表", "income"):
            df = ak.stock_profit_sheet_by_report_em(symbol=code)
            if df is not None and not df.empty:
                for _, row in df.head(max_results).iterrows():
                    results.append({
                        "报告期": str(row.get("REPORT_DATE_NAME", "")),
                        "营业总收入": str(row.get("TOTAL_OPERATE_INCOME", "")),
                        "营业总成本": str(row.get("TOTAL_OPERATE_COST", "")),
                        "净利润": str(row.get("NETPROFIT", "")),
                    })
        elif report_type in ("资产负债表", "balance"):
            df = ak.stock_balance_sheet_by_report_em(symbol=code)
            if df is not None and not df.empty:
                for _, row in df.head(max_results).iterrows():
                    results.append({
                        "报告期": str(row.get("REPORT_DATE_NAME", "")),
                        "总资产": str(row.get("TOTAL_ASSETS", "")),
                        "总负债": str(row.get("TOTAL_LIABILITIES", "")),
                        "净资产": str(row.get("TOTAL_EQUITY", "")),
                    })
        elif report_type in ("现金流量表", "cashflow"):
            df = ak.stock_cash_flow_sheet_by_report_em(symbol=code)
            if df is not None and not df.empty:
                for _, row in df.head(max_results).iterrows():
                    results.append({
                        "报告期": str(row.get("REPORT_DATE_NAME", "")),
                        "经营活动现金流": str(row.get("NETCASH_OPERATE", "")),
                        "投资活动现金流": str(row.get("NETCASH_INVEST", "")),
                        "筹资活动现金流": str(row.get("NETCASH_FINANCE", "")),
                    })
        else:
            # Default: key financial indicators
            df = ak.stock_financial_abstract_ths(symbol=code)
            if df is not None and not df.empty:
                for _, row in df.head(max_results).iterrows():
                    results.append(row.to_dict())
    except Exception as e:
        log.warning("akshare query failed for %s/%s: %s", code, report_type, e)
        results.append({"error": f"查询失败: {e}"})

    return results


def _query_stock_info(stock_code: str) -> dict:
    """Query basic stock info via akshare."""
    try:
        import akshare as ak
    except ImportError:
        return {"error": "akshare 未安装"}

    try:
        df = ak.stock_individual_info_em(symbol=stock_code.strip())
        if df is not None and not df.empty:
            info = {}
            for _, row in df.iterrows():
                info[str(row.iloc[0])] = str(row.iloc[1])
            return info
    except Exception as e:
        log.warning("akshare stock_info failed for %s: %s", stock_code, e)
        return {"error": str(e)}
    return {}


@register
class AkShareProvider(ToolProvider):
    tool_type = "datasource"
    provider_id = "akshare"
    display_name = "AkShare 财务数据"
    description = "查询A股上市公司财务报表、个股信息等，免费无需API Key"
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
                    "Query financial data of Chinese A-share listed companies via AkShare. "
                    "Can retrieve income statements, balance sheets, cash flow statements, "
                    "and basic stock information. Free, no API key needed."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "stock_code": {
                            "type": "string",
                            "description": "Stock code, e.g. '000001' or '600519'.",
                        },
                        "query_type": {
                            "type": "string",
                            "description": (
                                "Type of query: '利润表' (income statement), "
                                "'资产负债表' (balance sheet), '现金流量表' (cash flow), "
                                "'个股信息' (stock info). Default: '利润表'."
                            ),
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Max rows to return (default 4, i.e. recent 4 periods).",
                            "default": 4,
                        },
                    },
                    "required": ["stock_code"],
                },
            },
        }

    async def execute(self, args: dict[str, Any]) -> Any:
        stock_code = args["stock_code"]
        query_type = args.get("query_type", "利润表")
        max_results = args.get("max_results", 4)

        if query_type in ("个股信息", "stock_info"):
            return await _run_sync(_query_stock_info, stock_code)
        return await _run_sync(_query_financial, stock_code, query_type, max_results)
