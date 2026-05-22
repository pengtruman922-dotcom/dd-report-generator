"""Shared intake/update log writer."""

from __future__ import annotations

import json

from db import get_db


def write_intake_log(
    report_id: str,
    log_type: str,
    trigger_reason: str,
    input_sources: list[str],
    changed_fields: dict,
    steps_executed: list[str],
    steps_skipped: list[dict],
    research_data_age_days: int | None,
    operator: str | None,
) -> None:
    """Persist an intake/update log entry."""
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO intake_logs
               (report_id, log_type, trigger_reason, input_sources, changed_fields,
                steps_executed, steps_skipped, research_data_age_days, operator)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                report_id,
                log_type,
                trigger_reason,
                json.dumps(input_sources, ensure_ascii=False),
                json.dumps(changed_fields, ensure_ascii=False),
                json.dumps(steps_executed, ensure_ascii=False),
                json.dumps(steps_skipped, ensure_ascii=False),
                research_data_age_days,
                operator,
            ),
        )
        conn.commit()
    finally:
        conn.close()
