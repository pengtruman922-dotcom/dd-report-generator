"""Tests for report deletion cleanup helpers."""

import sqlite3
from pathlib import Path

from routers import report as report_router


def test_delete_report_related_rows_removes_all_related_records():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE reports (report_id TEXT PRIMARY KEY);
        CREATE TABLE report_chunks (report_id TEXT, chunk_id TEXT);
        CREATE TABLE intake_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, report_id TEXT);
        CREATE TABLE pipeline_tasks (task_id TEXT, report_id TEXT);
        """
    )
    conn.execute("INSERT INTO reports(report_id) VALUES ('rpt_1')")
    conn.execute("INSERT INTO report_chunks(report_id, chunk_id) VALUES ('rpt_1', 'chunk0')")
    conn.execute("INSERT INTO intake_logs(report_id) VALUES ('rpt_1')")
    conn.execute("INSERT INTO pipeline_tasks(task_id, report_id) VALUES ('rpt_1', 'rpt_1')")
    conn.execute("INSERT INTO pipeline_tasks(task_id, report_id) VALUES ('task_2', 'rpt_1')")

    report_router._delete_report_related_rows(conn, "rpt_1")
    conn.commit()

    assert conn.execute("SELECT 1 FROM reports WHERE report_id='rpt_1'").fetchone() is None
    assert conn.execute("SELECT 1 FROM report_chunks WHERE report_id='rpt_1'").fetchone() is None
    assert conn.execute("SELECT 1 FROM intake_logs WHERE report_id='rpt_1'").fetchone() is None
    assert conn.execute("SELECT 1 FROM pipeline_tasks WHERE report_id='rpt_1'").fetchone() is None


def test_delete_report_artifacts_removes_configured_and_default_paths(tmp_path, monkeypatch):
    report_id = "rpt_cleanup"
    custom_root = tmp_path / "custom"
    default_root = tmp_path / "default"
    custom_root.mkdir()
    default_root.mkdir()

    custom_paths = {
        "md": custom_root / "custom.md",
        "json": custom_root / "custom.json",
        "chunks": custom_root / "custom_chunks.json",
        "debug": custom_root / "custom_debug",
        "attachments": custom_root / "custom_attachments",
    }
    for key in ("md", "json", "chunks"):
        custom_paths[key].write_text("x", encoding="utf-8")
    custom_paths["debug"].mkdir()
    (custom_paths["debug"] / "research.json").write_text("{}", encoding="utf-8")
    custom_paths["attachments"].mkdir()
    (custom_paths["attachments"] / "file.pdf").write_text("x", encoding="utf-8")

    default_files = [
        default_root / f"{report_id}.md",
        default_root / f"{report_id}.json",
        default_root / f"{report_id}_chunks.json",
    ]
    for path in default_files:
        path.write_text("x", encoding="utf-8")
    default_debug = default_root / f"{report_id}_debug"
    default_debug.mkdir()
    (default_debug / "debug.txt").write_text("x", encoding="utf-8")
    default_attachments = default_root / f"{report_id}_attachments"
    default_attachments.mkdir()
    (default_attachments / "old.pdf").write_text("x", encoding="utf-8")

    monkeypatch.setattr(report_router, "_get_report_paths", lambda _report_id: custom_paths)
    monkeypatch.setattr(report_router, "OUTPUT_DIR", default_root)

    report_router._delete_report_artifacts(report_id)

    for path in [*custom_paths.values(), *default_files, default_debug, default_attachments]:
        assert not Path(path).exists()
