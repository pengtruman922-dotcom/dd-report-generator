"""Tests for v4 pipeline helper behavior."""

from __future__ import annotations

import json
import sqlite3
import sys
import types
from pathlib import Path


class _FakeAsyncOpenAI:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


sys.modules.setdefault("openai", types.SimpleNamespace(AsyncOpenAI=_FakeAsyncOpenAI))

from services import pipeline_v3 as pipeline  # noqa: E402
from services import attachment_update_pipeline as attachment_pipeline  # noqa: E402


def test_coerce_to_v4_chunk_state_from_legacy_chunks():
    legacy_chunks = {
        "chunk0": {"summary": "身份", "content": "身份正文", "index_tags": ["主体"]},
        "chunk1": {"summary": "财务", "content": "财务正文", "index_tags": ["营收"]},
        "chunk7": {"summary": "动态", "content": "动态正文", "index_tags": ["推进"]},
    }

    result = pipeline._coerce_to_v4_chunk_state(legacy_chunks)

    assert "info" in result
    assert "tracking" in result
    assert "身份正文" in result["info"]["content"]
    assert "财务正文" in result["info"]["content"]
    assert result["tracking"]["content"] == "动态正文"


def test_first_usable_ai_config_skips_empty_api_key():
    fallback = {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key": "sk-valid",
        "model": "qwen3-plus",
    }

    result = pipeline._first_usable_ai_config(
        {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "api_key": "", "model": "qwen3-max"},
        {},
        fallback,
    )

    assert result is fallback


def test_update_pipeline_skips_info_rewrite_when_snapshot_unchanged(tmp_path, monkeypatch):
    db_path = tmp_path / "v4_pipeline.sqlite"
    _init_pipeline_db(db_path)
    _seed_existing_report(db_path)

    def fake_get_db():
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(pipeline, "get_db", fake_get_db)

    write_info_calls = []

    async def fake_process_tracking(**kwargs):
        return {
            "tracking_chunk": {
                "summary": "最新动态",
                "content": "2026-04-24 卖方维持 10 亿元报价，继续推进。",
                "index_tags": ["动态"],
            },
            "seller_fact_snapshot": {
                "offer_yuan": "1000000000",
                "offer_date": "2026-04-24",
                "valuation_yuan": None,
                "valuation_date": None,
                "deal_path": "股权转让",
                "willingness": "继续推进",
                "transaction_status": "推进中",
                "transfer_ratio": None,
                "blockers": [],
                "nonpublic_risks": [],
            },
            "excluded_context": [],
            "extracted_fields": {
                "referral_status": "2026-04-24 卖方维持 10 亿元报价，继续推进。",
                "is_traded": "推进中",
            },
        }

    async def fake_write_info_chunk(**kwargs):
        write_info_calls.append(kwargs)
        return {
            "summary": "不应该被调用",
            "content": "不应该被调用",
            "extracted_fields": {},
            "index_tags": [],
        }

    async def fake_run_rating_agent(**kwargs):
        return {"rating": "B"}

    async def fake_research(**kwargs):
        raise AssertionError("research should not run for pure tracking update")

    monkeypatch.setattr("agents.tracking_processor.process_tracking", fake_process_tracking)
    monkeypatch.setattr("agents.info_chunk_writer.write_info_chunk", fake_write_info_chunk)
    monkeypatch.setattr("agents.researcher.research", fake_research)
    monkeypatch.setattr("agents.rating_agent.should_rate_on_update", lambda *args, **kwargs: (False, "skip"))
    monkeypatch.setattr("agents.rating_agent.run_rating_agent", fake_run_rating_agent)

    result = _run_async(
        pipeline.run_pipeline_v3(
            task_id="rpt_existing",
            action="update",
            company_name="测试公司",
            bd_code="BD00001",
            fields={},
            material_summary="2026-04-24 电话沟通，对方维持原报价，继续推进。",
            attachment_filenames=[],
            attachments_info=[],
            settings={"ai_config": {}, "tools": {}, "fastgpt": {"enabled": False}},
            owner="tester",
            on_progress=None,
        )
    )

    assert result["chunks_written"] == ["tracking"]
    assert write_info_calls == []

    conn = fake_get_db()
    try:
        report_row = conn.execute(
            "SELECT referral_status, report_format, metadata_json FROM reports WHERE report_id = 'rpt_existing'"
        ).fetchone()
        chunk_rows = conn.execute(
            "SELECT chunk_id, content FROM report_chunks WHERE report_id = 'rpt_existing' ORDER BY chunk_id"
        ).fetchall()
    finally:
        conn.close()

    metadata = json.loads(report_row["metadata_json"])
    chunks = {row["chunk_id"]: row["content"] for row in chunk_rows}

    assert report_row["report_format"] == "v4"
    assert "继续推进" in report_row["referral_status"]
    assert chunks["info"] == "旧 info 正文"
    assert "继续推进" in chunks["tracking"]
    assert metadata["seller_fact_snapshot_json"]["offer_yuan"] == "1000000000"


def test_attachment_update_rewrites_info_when_snapshot_changes(tmp_path, monkeypatch):
    db_path = tmp_path / "v4_attachment.sqlite"
    _init_pipeline_db(db_path)
    _seed_existing_report(db_path)

    def fake_get_db():
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(pipeline, "get_db", fake_get_db)
    monkeypatch.setattr(attachment_pipeline, "get_db", fake_get_db)

    write_info_calls = []

    monkeypatch.setattr(
        attachment_pipeline,
        "_parse_selected_attachments",
        lambda report_id, filenames: [
            {
                "filename": "update.txt",
                "file_type": "txt",
                "text": "卖方最新报价 12 亿元，股权转让继续推进。",
            }
        ],
    )

    async def fake_process_tracking(**kwargs):
        return {
            "tracking_chunk": {
                "summary": "最新动态",
                "content": "2026-04-25 卖方更新报价至 12 亿元。",
                "index_tags": ["动态"],
            },
            "seller_fact_snapshot": {
                "offer_yuan": "1200000000",
                "offer_date": "2026-04-25",
                "valuation_yuan": None,
                "valuation_date": None,
                "deal_path": "股权转让",
                "willingness": "继续推进",
                "transaction_status": "推进中",
                "transfer_ratio": None,
                "blockers": [],
                "nonpublic_risks": [],
            },
            "excluded_context": ["我方建议继续跟进"],
            "extracted_fields": {
                "referral_status": "2026-04-25 卖方更新报价至 12 亿元。",
                "offer_yuan": "1200000000",
                "offer_date": "2026-04-25",
                "is_traded": "推进中",
            },
        }

    async def fake_write_info_chunk(**kwargs):
        write_info_calls.append(kwargs)
        return {
            "summary": "新的 info",
            "content": "当前有效报价 12 亿元。",
            "extracted_fields": {
                "offer_yuan": "1200000000",
                "offer_date": "2026-04-25",
            },
            "index_tags": ["并购"],
        }

    async def fake_run_rating_agent(**kwargs):
        return {"rating": "B"}

    async def fake_auto_push(**kwargs):
        return {"status": "skipped"}

    monkeypatch.setattr("agents.tracking_processor.process_tracking", fake_process_tracking)
    monkeypatch.setattr("agents.info_chunk_writer.write_info_chunk", fake_write_info_chunk)
    monkeypatch.setattr("agents.rating_agent.run_rating_agent", fake_run_rating_agent)
    monkeypatch.setattr(
        attachment_pipeline,
        "build_index_bundle",
        lambda **kwargs: {
            "info_summary": "统一摘要",
            "tracking_summary": "动态摘要",
            "info_index_tags": ["并购", "报价"],
        },
    )
    monkeypatch.setattr(attachment_pipeline, "_maybe_auto_push_to_fastgpt", fake_auto_push)

    result = _run_async(
        attachment_pipeline.run_attachment_update_pipeline(
            report_id="rpt_existing",
            attachment_filenames=["update.txt"],
            settings={"ai_config": {}, "fastgpt": {"enabled": False}},
            owner="tester",
        )
    )

    assert result["updated_chunks"] == ["tracking", "info"]
    assert write_info_calls and write_info_calls[0]["seller_fact_snapshot"]["offer_yuan"] == "1200000000"

    conn = fake_get_db()
    try:
        report_row = conn.execute(
            "SELECT referral_status, offer_yuan, offer_date, report_format, metadata_json "
            "FROM reports WHERE report_id = 'rpt_existing'"
        ).fetchone()
        chunk_rows = conn.execute(
            "SELECT chunk_id, summary, content, index_tags FROM report_chunks "
            "WHERE report_id = 'rpt_existing' ORDER BY chunk_id"
        ).fetchall()
    finally:
        conn.close()

    metadata = json.loads(report_row["metadata_json"])
    chunks = {row["chunk_id"]: dict(row) for row in chunk_rows}

    assert report_row["report_format"] == "v4"
    assert report_row["offer_yuan"] == "1200000000"
    assert report_row["offer_date"] == "2026-04-25"
    assert "12 亿元" in report_row["referral_status"]
    assert chunks["info"]["summary"] == "统一摘要"
    assert chunks["info"]["content"] == "当前有效报价 12 亿元。"
    assert chunks["info"]["index_tags"] == '["并购", "报价"]'
    assert chunks["tracking"]["summary"] == "动态摘要"
    assert metadata["seller_fact_snapshot_json"]["offer_yuan"] == "1200000000"
    assert metadata["excluded_context"] == ["我方建议继续跟进"]


def _run_async(awaitable):
    import asyncio

    return asyncio.run(awaitable)


def _init_pipeline_db(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE reports (
            report_id TEXT PRIMARY KEY,
            bd_code TEXT,
            company_name TEXT,
            project_name TEXT,
            industry TEXT,
            province TEXT,
            city TEXT,
            district TEXT,
            is_listed TEXT,
            stock_code TEXT,
            website TEXT,
            revenue TEXT,
            net_profit TEXT,
            revenue_yuan TEXT,
            net_profit_yuan TEXT,
            valuation_yuan TEXT,
            valuation_date TEXT,
            description TEXT,
            company_intro TEXT,
            industry_tags TEXT,
            referral_status TEXT,
            is_traded TEXT,
            dept_primary TEXT,
            dept_owner TEXT,
            annual_report_attachment TEXT,
            remarks TEXT,
            score REAL,
            rating TEXT,
            manual_rating TEXT,
            manual_rating_note TEXT,
            status TEXT,
            owner TEXT,
            created_at TEXT,
            updated_at TEXT,
            file_size INTEGER,
            intro_attachment TEXT,
            metadata_json TEXT,
            locked_fields TEXT,
            push_records TEXT,
            attachments TEXT,
            md_path TEXT,
            chunks_path TEXT,
            debug_dir TEXT,
            attachments_dir TEXT,
            token_usage_json TEXT,
            estimated_cost REAL,
            report_format TEXT,
            feasibility_rating TEXT,
            feasibility_rating_detail TEXT,
            feasibility_rating_at TEXT,
            pending_rating_change TEXT,
            offer_yuan TEXT,
            offer_date TEXT
        );
        CREATE TABLE report_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id TEXT NOT NULL,
            chunk_id TEXT NOT NULL,
            label TEXT NOT NULL,
            summary TEXT,
            content TEXT NOT NULL,
            index_tags TEXT,
            updated_at TEXT,
            UNIQUE(report_id, chunk_id)
        );
        """
    )
    conn.commit()
    conn.close()


def _seed_existing_report(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    metadata_json = json.dumps(
        {
            "report_schema_version": "v4",
            "seller_fact_snapshot_json": {
                "offer_yuan": "1000000000",
                "offer_date": "2026-04-24",
                "valuation_yuan": None,
                "valuation_date": None,
                "deal_path": "股权转让",
                "willingness": "继续推进",
                "transaction_status": "推进中",
                "transfer_ratio": None,
                "blockers": [],
                "nonpublic_risks": [],
            },
        },
        ensure_ascii=False,
    )
    conn.execute(
        """
        INSERT INTO reports (
            report_id, bd_code, company_name, project_name, referral_status,
            report_format, metadata_json, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "rpt_existing",
            "BD00001",
            "测试公司",
            "测试项目",
            "旧跟进",
            "v4",
            metadata_json,
            "completed",
            "2026-04-24T00:00:00",
            "2026-04-24T00:00:00",
        ),
    )
    conn.execute(
        """
        INSERT INTO report_chunks (report_id, chunk_id, label, summary, content, index_tags, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "rpt_existing",
            "info",
            "标的信息",
            "旧摘要",
            "旧 info 正文",
            json.dumps(["旧标签"], ensure_ascii=False),
            "2026-04-24T00:00:00",
        ),
    )
    conn.execute(
        """
        INSERT INTO report_chunks (report_id, chunk_id, label, summary, content, index_tags, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "rpt_existing",
            "tracking",
            "跟进动态",
            "旧动态摘要",
            "旧 tracking 正文",
            json.dumps(["旧动态"], ensure_ascii=False),
            "2026-04-24T00:00:00",
        ),
    )
    conn.commit()
    conn.close()
