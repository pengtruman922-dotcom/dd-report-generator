"""Tests for v4 FastGPT payload behavior."""

from __future__ import annotations

from services import fastgpt_uploader as uploader
from services.fastgpt_uploader import compute_chunks_hash
from utils.fastgpt_adapter import build_fastgpt_chunks_v4


def test_build_fastgpt_chunks_v4_only_pushes_info_chunk():
    chunks = {
        "info": {
            "summary": "这是一份 info 摘要",
            "content": "这是 info 正文",
            "index_tags": ["新能源", "储能"],
        },
        "tracking": {
            "summary": "这是一份 tracking 摘要",
            "content": "这是 tracking 正文",
            "index_tags": ["内部时间线"],
        },
    }

    payload = build_fastgpt_chunks_v4(
        report_id="rpt_v4",
        chunks=chunks,
        company_name="测试公司",
        bd_code="BD00001",
        info_summary="统一摘要",
        info_index_tags=["新能源", "储能", "并购"],
    )

    assert len(payload) == 1
    assert payload[0]["q"] == "这是 info 正文"
    assert {"text": "测试公司"} in payload[0]["indexes"]
    assert {"text": "BD00001"} in payload[0]["indexes"]
    assert {"text": "统一摘要"} in payload[0]["indexes"]
    assert {"text": "并购"} in payload[0]["indexes"]
    assert {"text": "内部时间线"} not in payload[0]["indexes"]


def test_compute_chunks_hash_ignores_tracking_changes(monkeypatch):
    base_chunks = {
        "info": {
            "summary": "统一摘要",
            "content": "这是 info 正文",
            "index_tags": ["并购", "新能源"],
        },
        "tracking": {
            "summary": "动态 1",
            "content": "tracking 正文 1",
            "index_tags": ["内部"],
        },
    }
    changed_tracking_chunks = {
        "info": {
            "summary": "统一摘要",
            "content": "这是 info 正文",
            "index_tags": ["并购", "新能源"],
        },
        "tracking": {
            "summary": "动态 2",
            "content": "tracking 正文 2",
            "index_tags": ["内部", "新增"],
        },
    }

    monkeypatch.setattr(
        "utils.fastgpt_adapter.load_chunks_v3",
        lambda report_id: base_chunks if report_id == "r1" else changed_tracking_chunks,
    )

    assert compute_chunks_hash("r1") == compute_chunks_hash("r2")


def test_build_fastgpt_payload_uses_v4_builder_when_info_exists(monkeypatch):
    calls = {}

    monkeypatch.setattr(
        uploader,
        "_load_report_push_context",
        lambda report_id: {
            "company_name": "测试公司",
            "bd_code": "BD00001",
            "push_records": {},
            "final_rating": "推荐",
            "feasibility_rating": "A",
            "report_format": "v3",
            "metadata_json": {
                "info_summary": "统一摘要",
                "info_index_tags": ["并购", "新能源"],
            },
        },
    )
    monkeypatch.setattr(
        "utils.fastgpt_adapter.load_chunks_v3",
        lambda report_id: {
            "info": {"summary": "info 摘要", "content": "info 正文", "index_tags": ["旧标签"]},
            "tracking": {"summary": "tracking 摘要", "content": "tracking 正文", "index_tags": ["内部"]},
        },
    )

    def fake_build_v4(report_id, chunks, company_name, bd_code, info_summary=None, info_index_tags=None):
        calls["report_id"] = report_id
        calls["company_name"] = company_name
        calls["bd_code"] = bd_code
        calls["info_summary"] = info_summary
        calls["info_index_tags"] = info_index_tags
        return [{"q": "info 正文", "a": "", "indexes": [{"text": "并购"}]}]

    monkeypatch.setattr("utils.fastgpt_adapter.build_fastgpt_chunks_v4", fake_build_v4)
    monkeypatch.setattr(
        "utils.fastgpt_adapter.build_fastgpt_chunks_v3",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("v3 builder should not be used")),
    )

    payload = uploader.build_fastgpt_payload("rpt_v4")

    assert payload["report_format"] == "v4"
    assert payload["collection_name"] == "测试公司-BD00001"
    assert "v4" in payload["tags"]
    assert "推荐" in payload["tags"]
    assert "可行性A" in payload["tags"]
    assert payload["chunks"] == [{"q": "info 正文", "a": "", "indexes": [{"text": "并购"}]}]
    assert calls == {
        "report_id": "rpt_v4",
        "company_name": "测试公司",
        "bd_code": "BD00001",
        "info_summary": "统一摘要",
        "info_index_tags": ["并购", "新能源"],
    }
