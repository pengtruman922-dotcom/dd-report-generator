"""Parse the 26-column seller Excel into structured company dicts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


# Actual columns in 清洗后卖家表0116.xlsx (26 columns)
# We use substring matching so partial matches work even if headers have extra text.
COLUMN_MAP = {
    "标的编码": "bd_code",
    "标的主体": "company_name",
    "标的项目": "project_name",
    "营业收入（元）": "revenue_yuan",
    "估值（元）": "valuation_yuan",
    "标的介绍材料附件": "intro_attachment",
    "净利润（元）": "net_profit_yuan",
    "行业": "industry",
    "上市编号": "stock_code",
    "估值日期": "valuation_date",
    "官网地址": "website",
    "上市情况": "is_listed",
    "标的描述": "description",
    "标的主体公司简介": "company_intro",
    "省": "province",
    "市": "city",
    "区": "district",
    "营业收入": "revenue",
    "净利润": "net_profit",
    "行业标签": "industry_tags",
    "推介情况": "referral_status",
    "是否已交易": "is_traded",
    "负责人主属部门": "dept_primary",
    "归属部门": "dept_owner",
    "标的公司年度报告摘要附件": "annual_report_attachment",
    "备注": "remarks",
}

# All known English field keys (for manual input validation etc.)
ALL_FIELD_KEYS = list(COLUMN_MAP.values())

# Chinese labels for each field key
FIELD_LABELS = {v: k for k, v in COLUMN_MAP.items()}


def parse_excel(file_path: str | Path) -> list[dict[str, Any]]:
    """Read an Excel file and return a list of company dicts.

    Each dict uses English keys from COLUMN_MAP where possible,
    falling back to the raw Chinese header when unrecognised.
    """
    df = pd.read_excel(file_path, engine="openpyxl")

    # Build rename dict: try exact match first, then substring match.
    # Process longer keys first so "营业收入（元）" matches before "营业收入".
    rename = {}
    used_cols: set[str] = set()
    sorted_map = sorted(COLUMN_MAP.items(), key=lambda x: len(x[0]), reverse=True)
    for cn_col, en_col in sorted_map:
        # Exact match
        if cn_col in df.columns and cn_col not in used_cols:
            rename[cn_col] = en_col
            used_cols.add(cn_col)
            continue
        # Substring match (skip already-used columns)
        for df_col in df.columns:
            if df_col not in used_cols and cn_col in str(df_col):
                rename[df_col] = en_col
                used_cols.add(df_col)
                break

    df = df.rename(columns=rename)

    # Replace NaN with None for JSON serialisation
    df = df.where(pd.notna(df), None)

    records = df.to_dict(orient="records")
    return records


def get_company_list(file_path: str | Path) -> list[dict[str, str]]:
    """Return a lightweight list: [{bd_code, company_name, project_name}, ...]."""
    records = parse_excel(file_path)
    result = []
    for r in records:
        result.append(
            {
                "bd_code": str(r.get("bd_code", "")),
                "company_name": str(r.get("company_name", "")),
                "project_name": str(r.get("project_name", "")),
            }
        )
    return result


def get_company_row(file_path: str | Path, bd_code: str) -> dict[str, Any] | None:
    """Return the full row for a specific BD code."""
    records = parse_excel(file_path)
    for r in records:
        if str(r.get("bd_code", "")) == bd_code:
            return r
    return None
