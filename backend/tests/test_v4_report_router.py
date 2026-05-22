"""Tests for v4 report router chunk and markdown behavior."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

from routers import report as report_router


def test_build_v4_markdown_prefers_info_then_tracking(tmp_path, monkeypatch):
    db_path = tmp_path / "report_router.sqlite"
    _init_report_db(db_path)
    _seed_v4_report(db_path)

    monkeypatch.setattr(report_router, "get_db", lambda: _connect(db_path))

    built = report_router._build_v3_markdown("rpt_v4")

    assert built is not None
    _, markdown = built
    assert markdown.startswith("# 测试公司 标的信息")
    assert markdown.index("## 标的信息") < markdown.index("## 跟进动态")
    assert "当前有效事实" in markdown
    assert "最新推进" in markdown


def test_get_report_fallback_uses_v4_markdown_builder(tmp_path, monkeypatch):
    db_path = tmp_path / "report_router.sqlite"
    _init_report_db(db_path)
    _seed_v4_report(db_path)

    monkeypatch.setattr(report_router, "get_db", lambda: _connect(db_path))
    monkeypatch.setattr(report_router, "_check_report_access", lambda report_id, user: {"report_id": report_id})
    monkeypatch.setattr(
        report_router,
        "_load_report_meta",
        lambda report_id: {
            "report_id": report_id,
            "company_name": "测试公司",
            "bd_code": "BD00001",
            "report_format": "v4",
            "status": "completed",
        },
    )

    payload = _run_async(
        report_router.get_report(
            "rpt_v4",
            user={"username": "tester", "role": "admin"},
        )
    )

    assert payload["format"] == "v4"
    assert payload["content"].startswith("# 测试公司 标的信息")
    assert payload["content"].index("## 标的信息") < payload["content"].index("## 跟进动态")


def test_save_chunks_and_get_chunks_roundtrip_v4(tmp_path, monkeypatch):
    db_path = tmp_path / "report_router.sqlite"
    _init_report_db(db_path)

    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO reports (report_id, bd_code, company_name, owner, report_format, status, "
            "created_at, updated_at, metadata_json, offer_yuan, offer_date, valuation_yuan, valuation_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "rpt_edit",
                "BD00099",
                "编辑测试公司",
                "tester",
                "v3",
                "completed",
                "2026-04-24T00:00:00",
                "2026-04-24T00:00:00",
                '{"seller_fact_snapshot_json":{"offer_yuan":"800000000","offer_date":"2026-04-20","valuation_yuan":"700000000","valuation_date":"2026-04-18","deal_path":"股权转让","willingness":"继续推进","transaction_status":"推进中","transfer_ratio":null,"blockers":[],"nonpublic_risks":[]}}',
                "800000000",
                "2026-04-20",
                "700000000",
                "2026-04-18",
            ),
        )
        conn.commit()
    finally:
        conn.close()

    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    md_path = artifact_root / "rpt_edit.md"
    json_path = artifact_root / "rpt_edit.json"
    json_path.write_text('{"report_id":"rpt_edit","report_format":"v3","status":"completed"}', encoding="utf-8")

    monkeypatch.setattr(report_router, "get_db", lambda: _connect(db_path))
    monkeypatch.setattr(report_router, "_check_report_access", lambda report_id, user: {"report_id": report_id})
    def fake_load_report_meta(report_id: str):
        report_format = "v3"
        status = "completed"
        if json_path.exists():
            import json

            sidecar = json.loads(json_path.read_text(encoding="utf-8"))
            report_format = sidecar.get("report_format", report_format)
            status = sidecar.get("status", status)
        return {
            "report_id": report_id,
            "company_name": "编辑测试公司",
            "bd_code": "BD00099",
            "report_format": report_format,
            "status": status,
            "offer_yuan": "800000000",
            "offer_date": "2026-04-20",
            "valuation_yuan": "700000000",
            "valuation_date": "2026-04-18",
        }

    monkeypatch.setattr(report_router, "_load_report_meta", fake_load_report_meta)
    monkeypatch.setattr(
        "services.pipeline_v3._load_report_metadata_json",
        lambda report_id: {
            "seller_fact_snapshot_json": {
                "offer_yuan": "800000000",
                "offer_date": "2026-04-20",
                "valuation_yuan": "700000000",
                "valuation_date": "2026-04-18",
                "deal_path": "股权转让",
                "willingness": "继续推进",
                "transaction_status": "推进中",
                "transfer_ratio": None,
                "blockers": [],
                "nonpublic_risks": [],
            }
        },
    )
    monkeypatch.setattr(
        report_router,
        "_get_report_paths",
        lambda report_id: {
            "md": md_path,
            "json": json_path,
            "debug": artifact_root / "debug",
            "attachments": artifact_root / "attachments",
        },
    )

    chunks = [
        report_router.ReportChunk(
            title="标的信息",
            chunk_id="info",
            summary="统一摘要",
            content="当前有效估值 9 亿元，聚焦新能源装备。",
            q="当前有效估值 9 亿元，聚焦新能源装备。",
            indexes=[report_router.ChunkIndex(text="并购"), report_router.ChunkIndex(text="新能源")],
        ),
        report_router.ReportChunk(
            title="跟进动态",
            chunk_id="tracking",
            summary="最新动态",
            content="2026-04-25 卖方最新报价 12 亿元，项目继续推进。",
            q="2026-04-25 卖方最新报价 12 亿元，项目继续推进。",
            indexes=[report_router.ChunkIndex(text="内部动态")],
        ),
    ]

    result = _run_async(
        report_router.save_chunks(
            "rpt_edit",
            chunks=chunks,
            user={"username": "tester", "role": "admin"},
        )
    )
    payload = _run_async(
        report_router.get_chunks(
            "rpt_edit",
            user={"username": "tester", "role": "admin"},
        )
    )

    assert result == {"status": "ok", "count": 2, "format": "v4"}
    assert payload["format"] == "v4"
    assert [chunk["chunk_id"] for chunk in payload["chunks"]] == ["info", "tracking"]
    assert payload["chunks"][0]["summary"] == "统一摘要"
    assert payload["chunks"][1]["content"] == "2026-04-25 卖方最新报价 12 亿元，项目继续推进。"

    conn = _connect(db_path)
    try:
        report_row = conn.execute(
            "SELECT report_format, status, metadata_json, referral_status, is_traded, "
            "offer_yuan, offer_date, valuation_yuan, valuation_date, file_size "
            "FROM reports WHERE report_id = ?",
            ("rpt_edit",),
        ).fetchone()
        chunk_rows = conn.execute(
            "SELECT chunk_id, summary, content, index_tags FROM report_chunks "
            "WHERE report_id = ? ORDER BY chunk_id",
            ("rpt_edit",),
        ).fetchall()
    finally:
        conn.close()

    assert report_row["report_format"] == "v4"
    assert report_row["status"] == "updated"
    assert report_row["offer_yuan"] == "1200000000"
    assert report_row["offer_date"] == "2026-04-25"
    assert report_row["valuation_yuan"] == "900000000"
    assert report_row["is_traded"] == "推进中"
    assert "卖方最新报价 12 亿元" in report_row["referral_status"]
    assert report_row["file_size"] > 0
    assert [row["chunk_id"] for row in chunk_rows] == ["info", "tracking"]
    assert chunk_rows[0]["summary"] == "统一摘要"
    assert chunk_rows[0]["index_tags"] == '["编辑测试公司", "BD00099", "并购", "新能源"]'

    metadata = __import__("json").loads(report_row["metadata_json"])
    assert metadata["info_summary"] == "统一摘要"
    assert metadata["tracking_summary"] == "最新动态"
    assert metadata["info_index_tags"] == ["编辑测试公司", "BD00099", "并购", "新能源"]
    assert metadata["seller_fact_snapshot_json"]["offer_yuan"] == "1200000000"
    assert metadata["seller_fact_snapshot_json"]["valuation_yuan"] == "900000000"

    md_text = md_path.read_text(encoding="utf-8")
    sidecar = __import__("json").loads(json_path.read_text(encoding="utf-8"))
    assert md_text.startswith("# 编辑测试公司 标的信息")
    assert "12 亿元" in md_text
    assert sidecar["report_format"] == "v4"
    assert sidecar["status"] == "updated"
    assert sidecar["offer_yuan"] == "1200000000"
    assert sidecar["metadata_json"]["seller_fact_snapshot_json"]["valuation_yuan"] == "900000000"


def test_update_report_meta_rebuilds_v4_snapshot_and_markdown(tmp_path, monkeypatch):
    db_path = tmp_path / "report_router.sqlite"
    _init_report_db(db_path)
    _seed_v4_report(db_path)

    artifact_root = tmp_path / "meta_artifacts"
    artifact_root.mkdir()
    md_path = artifact_root / "rpt_v4.md"
    json_path = artifact_root / "rpt_v4.json"
    json_path.write_text(
        json.dumps(
            {"report_id": "rpt_v4", "report_format": "v4", "status": "completed", "company_name": "测试公司"},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(report_router, "get_db", lambda: _connect(db_path))
    monkeypatch.setattr("services.pipeline_v3.get_db", lambda: _connect(db_path))
    monkeypatch.setattr(report_router, "_check_report_access", lambda report_id, user: {"report_id": report_id})
    monkeypatch.setattr(
        report_router,
        "_load_report_meta",
        lambda report_id: {
            "report_id": report_id,
            "bd_code": "BD00001",
            "company_name": "测试公司",
            "report_format": "v4",
            "status": "completed",
            "offer_yuan": None,
            "offer_date": None,
            "valuation_yuan": None,
            "valuation_date": None,
            "referral_status": None,
            "is_traded": None,
        },
    )
    monkeypatch.setattr(
        report_router,
        "_get_report_paths",
        lambda report_id: {
            "md": md_path,
            "json": json_path,
            "debug": artifact_root / "debug",
            "attachments": artifact_root / "attachments",
        },
    )

    result = _run_async(
        report_router.update_report_meta(
            "rpt_v4",
            {
                "company_name": "新测试公司",
                "offer_yuan": "1300000000",
                "offer_date": "2026-04-26",
                "valuation_yuan": "950000000",
                "referral_status": "2026-04-26 手工修正：卖方报价 13 亿元，继续推进。",
            },
            user={"username": "tester", "role": "admin"},
        )
    )

    assert result == {"status": "ok", "applied": 5}

    conn = _connect(db_path)
    try:
        report_row = conn.execute(
            "SELECT company_name, report_format, status, metadata_json, referral_status, "
            "offer_yuan, offer_date, valuation_yuan FROM reports WHERE report_id = ?",
            ("rpt_v4",),
        ).fetchone()
        info_row = conn.execute(
            "SELECT summary, index_tags FROM report_chunks WHERE report_id = ? AND chunk_id = ?",
            ("rpt_v4", "info"),
        ).fetchone()
    finally:
        conn.close()

    metadata = json.loads(report_row["metadata_json"])
    sidecar = json.loads(json_path.read_text(encoding="utf-8"))
    markdown = md_path.read_text(encoding="utf-8")

    assert report_row["company_name"] == "新测试公司"
    assert report_row["report_format"] == "v4"
    assert report_row["status"] == "completed"
    assert report_row["offer_yuan"] == "1300000000"
    assert report_row["offer_date"] == "2026-04-26"
    assert report_row["valuation_yuan"] == "950000000"
    assert report_row["referral_status"] == "2026-04-26 手工修正：卖方报价 13 亿元，继续推进。"
    assert info_row["index_tags"] == '["新测试公司", "BD00001", "并购"]'
    assert metadata["info_index_tags"] == ["新测试公司", "BD00001", "并购"]
    assert metadata["seller_fact_snapshot_json"]["offer_yuan"] == "1300000000"
    assert metadata["seller_fact_snapshot_json"]["valuation_yuan"] == "950000000"
    assert sidecar["company_name"] == "新测试公司"
    assert sidecar["offer_yuan"] == "1300000000"
    assert sidecar["metadata_json"]["seller_fact_snapshot_json"]["offer_yuan"] == "1300000000"
    assert markdown.startswith("# 新测试公司 标的信息")


def _run_async(awaitable):
    return asyncio.run(awaitable)


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _init_report_db(db_path: Path) -> None:
    conn = _connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE reports (
                report_id TEXT PRIMARY KEY,
                bd_code TEXT,
                company_name TEXT,
                owner TEXT,
                report_format TEXT,
                status TEXT,
                created_at TEXT,
                updated_at TEXT,
                metadata_json TEXT,
                referral_status TEXT,
                is_traded TEXT,
                offer_yuan TEXT,
                offer_date TEXT,
                valuation_yuan TEXT,
                valuation_date TEXT,
                file_size INTEGER,
                md_path TEXT,
                chunks_path TEXT,
                debug_dir TEXT,
                attachments_dir TEXT
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
    finally:
        conn.close()


def _seed_v4_report(db_path: Path) -> None:
    conn = _connect(db_path)
    try:
        conn.execute(
            "INSERT INTO reports (report_id, bd_code, company_name, owner, report_format, status, "
            "created_at, updated_at, metadata_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "rpt_v4",
                "BD00001",
                "测试公司",
                "tester",
                "v4",
                "completed",
                "2026-04-24T00:00:00",
                "2026-04-24T00:00:00",
                "{}",
            ),
        )
        conn.execute(
            "INSERT INTO report_chunks (report_id, chunk_id, label, summary, content, index_tags, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "rpt_v4",
                "tracking",
                "跟进动态",
                "最新动态",
                "最新推进",
                "[]",
                "2026-04-24T00:00:00",
            ),
        )
        conn.execute(
            "INSERT INTO report_chunks (report_id, chunk_id, label, summary, content, index_tags, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "rpt_v4",
                "info",
                "标的信息",
                "统一摘要",
                "当前有效事实",
                '["并购"]',
                "2026-04-24T00:00:00",
            ),
        )
        conn.commit()
    finally:
        conn.close()
