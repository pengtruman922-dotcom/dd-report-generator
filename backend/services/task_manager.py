"""Task persistence and recovery manager for pipeline tasks.

Persists running intake/report tasks to database and supports automatic recovery on service restart.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Callable
from enum import Enum

from db import get_db

log = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    """Task execution status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskManager:
    """Manages task persistence and recovery."""

    def __init__(self):
        self._running_tasks: dict[str, asyncio.Task] = {}
        self._init_db()

    def _init_db(self):
        """Create tasks table if not exists."""
        conn = get_db()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS pipeline_tasks (
                task_id TEXT PRIMARY KEY,
                report_id TEXT NOT NULL,
                status TEXT NOT NULL,
                owner TEXT,
                excel_row TEXT NOT NULL,
                attachment_items TEXT,
                failed_attachments TEXT,
                attachments_info TEXT,
                is_regeneration INTEGER DEFAULT 0,
                runner_type TEXT NOT NULL DEFAULT 'v3',
                task_kind TEXT,
                company_name TEXT,
                bd_code TEXT,
                message TEXT,
                current_step INTEGER DEFAULT 0,
                total_steps INTEGER DEFAULT 6,
                error_message TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                completed_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_tasks_status ON pipeline_tasks(status);
            CREATE INDEX IF NOT EXISTS idx_tasks_owner ON pipeline_tasks(owner);
            CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON pipeline_tasks(created_at DESC);
        """)
        # Lightweight migrations for existing DBs
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(pipeline_tasks)")
        existing_cols = {row[1] for row in cursor.fetchall()}
        for ddl in [
            ("runner_type", "ALTER TABLE pipeline_tasks ADD COLUMN runner_type TEXT NOT NULL DEFAULT 'v3'"),
            ("task_kind", "ALTER TABLE pipeline_tasks ADD COLUMN task_kind TEXT"),
            ("company_name", "ALTER TABLE pipeline_tasks ADD COLUMN company_name TEXT"),
            ("bd_code", "ALTER TABLE pipeline_tasks ADD COLUMN bd_code TEXT"),
            ("message", "ALTER TABLE pipeline_tasks ADD COLUMN message TEXT"),
        ]:
            if ddl[0] not in existing_cols:
                cursor.execute(ddl[1])
        # Normalize historical defaults so new reads no longer carry legacy runner semantics.
        cursor.execute(
            "UPDATE pipeline_tasks SET runner_type = 'v3' WHERE runner_type IS NULL OR runner_type = '' OR runner_type = 'legacy'"
        )
        conn.commit()
        conn.close()
        log.info("Task manager database initialized")

    async def create_task(
        self,
        task_id: str,
        report_id: str,
        excel_row: dict[str, Any],
        attachment_items: list[tuple[str, str]],
        failed_attachments: list[str] | None = None,
        owner: str | None = None,
        attachments_info: list[dict] | None = None,
        is_regeneration: bool = False,
    ) -> None:
        """Backward-compatible helper that persists a generic legacy task record."""
        conn = get_db()
        try:
            conn.execute("""
                INSERT INTO pipeline_tasks (
                    task_id, report_id, status, owner,
                    excel_row, attachment_items, failed_attachments,
                    attachments_info, is_regeneration, runner_type, task_kind
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                task_id,
                report_id,
                TaskStatus.PENDING,
                owner,
                json.dumps(excel_row, ensure_ascii=False),
                json.dumps([(name, text) for name, text in attachment_items], ensure_ascii=False),
                json.dumps(failed_attachments or [], ensure_ascii=False),
                json.dumps(attachments_info or [], ensure_ascii=False),
                1 if is_regeneration else 0,
                "v3",
                "v3_regenerate" if is_regeneration else "v3_create",
            ))
            conn.commit()
            log.info(f"Created task record: {task_id}")
        finally:
            conn.close()

    async def create_v3_task(
        self,
        task_id: str,
        report_id: str,
        owner: str | None,
        company_name: str,
        bd_code: str | None,
        task_kind: str,
        total_steps: int = 3,
        message: str | None = None,
    ) -> None:
        """Create a persisted task record for the legacy-named intake execution path."""
        conn = get_db()
        try:
            conn.execute("""
                INSERT OR REPLACE INTO pipeline_tasks (
                    task_id, report_id, status, owner, excel_row,
                    attachment_items, failed_attachments, attachments_info,
                    is_regeneration, runner_type, task_kind,
                    company_name, bd_code, message, current_step, total_steps
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                task_id,
                report_id,
                TaskStatus.PENDING,
                owner,
                "{}",
                "[]",
                "[]",
                "[]",
                0,
                "v3",
                task_kind,
                company_name,
                bd_code,
                message,
                0,
                total_steps,
            ))
            conn.commit()
        finally:
            conn.close()

    async def update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        current_step: int | None = None,
        error_message: str | None = None,
        message: str | None = None,
    ) -> None:
        """Update task status and progress."""
        conn = get_db()
        try:
            updates = ["status = ?", "updated_at = ?"]
            values = [status, datetime.now().isoformat()]

            if current_step is not None:
                updates.append("current_step = ?")
                values.append(current_step)

            if error_message is not None:
                updates.append("error_message = ?")
                values.append(error_message)

            if message is not None:
                updates.append("message = ?")
                values.append(message)

            if status == TaskStatus.COMPLETED or status == TaskStatus.FAILED:
                updates.append("completed_at = ?")
                values.append(datetime.now().isoformat())

            values.append(task_id)
            query = f"UPDATE pipeline_tasks SET {', '.join(updates)} WHERE task_id = ?"
            if status in (TaskStatus.PENDING, TaskStatus.RUNNING):
                # Do not let late progress callbacks overwrite a terminal status.
                query += " AND status NOT IN (?, ?, ?)"
                values.extend([TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED])

            conn.execute(query, values)
            conn.commit()
            log.debug(f"Updated task {task_id}: status={status}, step={current_step}")
        finally:
            conn.close()

    async def get_task(self, task_id: str) -> dict | None:
        """Get task record from database."""
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT * FROM pipeline_tasks WHERE task_id = ?",
                (task_id,)
            ).fetchone()
            if row:
                return self._normalize_task_row(dict(row))
            return None
        finally:
            conn.close()

    async def list_tasks(
        self,
        status: TaskStatus | None = None,
        owner: str | None = None,
        runner_type: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """List tasks with optional filtering."""
        conn = get_db()
        try:
            query = "SELECT * FROM pipeline_tasks WHERE 1=1"
            params = []

            if status:
                query += " AND status = ?"
                params.append(status)

            if owner:
                query += " AND owner = ?"
                params.append(owner)

            if runner_type:
                query += " AND runner_type = ?"
                params.append(runner_type)

            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, params).fetchall()
            return [self._normalize_task_row(dict(row)) for row in rows]
        finally:
            conn.close()

    async def get_pending_tasks(self) -> list[dict]:
        """Get all pending or running intake tasks stored under the legacy runner type."""
        conn = get_db()
        try:
            rows = conn.execute(
                """
                SELECT * FROM pipeline_tasks
                WHERE status IN (?, ?)
                  AND runner_type = ?
                ORDER BY created_at ASC
                """,
                (TaskStatus.PENDING, TaskStatus.RUNNING, "v3"),
            ).fetchall()
            return [self._normalize_task_row(dict(row)) for row in rows]
        finally:
            conn.close()

    async def start_task(
        self,
        task_id: str,
        task_coro: Callable,
    ) -> None:
        """Start a task and track it in memory."""
        await self.update_task_status(task_id, TaskStatus.RUNNING)

        async def wrapped_task():
            try:
                await task_coro()
                await self.update_task_status(task_id, TaskStatus.COMPLETED)
            except asyncio.CancelledError:
                await self.update_task_status(task_id, TaskStatus.CANCELLED)
                raise
            except Exception as e:
                log.exception(f"Task {task_id} failed")
                await self.update_task_status(
                    task_id,
                    TaskStatus.FAILED,
                    error_message=str(e)
                )
            finally:
                self._running_tasks.pop(task_id, None)

        task = asyncio.create_task(wrapped_task())
        self._running_tasks[task_id] = task

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a running task."""
        task = self._running_tasks.get(task_id)
        if task and not task.done():
            task.cancel()
            await self.update_task_status(task_id, TaskStatus.CANCELLED)
            return True
        return False

    async def recover_tasks(self, pipeline_runner: Callable) -> int:
        """Recover pending/running tasks with the stored generic payload shape."""
        pending_tasks = await self.get_pending_tasks()
        recovered = 0

        for task_data in pending_tasks:
            task_id = task_data["task_id"]
            try:
                excel_row = json.loads(task_data["excel_row"])
                attachment_items_data = json.loads(task_data["attachment_items"])
                attachment_items = [(name, text) for name, text in attachment_items_data]
                failed_attachments = json.loads(task_data["failed_attachments"])
                attachments_info = json.loads(task_data["attachments_info"])
                is_regeneration = bool(task_data["is_regeneration"])
                owner = task_data["owner"]

                async def create_task_coro(
                    tid=task_id,
                    row=excel_row,
                    items=attachment_items,
                    failed=failed_attachments,
                    own=owner,
                    info=attachments_info,
                    regen=is_regeneration,
                ):
                    return await pipeline_runner(
                        task_id=tid,
                        excel_row=row,
                        attachment_items=items,
                        failed_attachments=failed,
                        owner=own,
                        attachments_info=info,
                        is_regeneration=regen,
                    )

                await self.start_task(task_id, create_task_coro)
                recovered += 1
            except Exception as e:
                log.error("Failed to recover task %s: %s", task_id, e)
                await self.update_task_status(
                    task_id,
                    TaskStatus.FAILED,
                    error_message=f"Recovery failed: {e}",
                )

        if recovered > 0:
            log.info("Recovered %s tasks", recovered)

        return recovered

    def is_task_running(self, task_id: str) -> bool:
        """Check if a task is currently running in memory."""
        task = self._running_tasks.get(task_id)
        return task is not None and not task.done()

    async def list_v3_tasks(self, owner: str | None = None, limit: int = 100) -> list[dict]:
        """List persisted legacy-format intake tasks for compatibility."""
        return await self.list_tasks(owner=owner, limit=limit, runner_type="v3")

    async def list_v3_active_tasks(self, owner: str | None = None, limit: int = 100) -> list[dict]:
        """List only active legacy-format intake tasks for compatibility."""
        conn = get_db()
        try:
            query = """
                SELECT *
                FROM pipeline_tasks
                WHERE runner_type = ?
                  AND status IN (?, ?)
                  AND completed_at IS NULL
            """
            params: list[Any] = ["v3", TaskStatus.PENDING, TaskStatus.RUNNING]

            if owner:
                query += " AND owner = ?"
                params.append(owner)

            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, params).fetchall()
            return [self._normalize_task_row(dict(row)) for row in rows]
        finally:
            conn.close()

    async def mark_abandoned_v3_tasks_failed(self) -> int:
        """Mark unrecoverable legacy-format intake tasks as failed after restart."""
        conn = get_db()
        try:
            now = datetime.now().isoformat()
            result = conn.execute(
                """
                UPDATE pipeline_tasks
                SET status = ?,
                    updated_at = ?,
                    completed_at = COALESCE(completed_at, ?),
                    error_message = COALESCE(error_message, ?),
                    message = ?
                WHERE runner_type = ?
                  AND status IN (?, ?)
                """,
                (
                    TaskStatus.FAILED,
                    now,
                    now,
                    "任务因服务重启或状态同步异常中断，请重新发起",
                    "任务已中断，请重新发起",
                    "v3",
                    TaskStatus.PENDING,
                    TaskStatus.RUNNING,
                ),
            )
            conn.commit()
            return result.rowcount
        finally:
            conn.close()

    async def create_intake_task(
        self,
        task_id: str,
        report_id: str,
        owner: str | None,
        company_name: str,
        bd_code: str | None,
        task_kind: str,
        total_steps: int = 3,
        message: str | None = None,
    ) -> None:
        """Create a persisted intake task record.

        This is the v4-facing alias for the legacy-named helper.
        """
        await self.create_v3_task(
            task_id=task_id,
            report_id=report_id,
            owner=owner,
            company_name=company_name,
            bd_code=bd_code,
            task_kind=task_kind,
            total_steps=total_steps,
            message=message,
        )

    async def list_active_intake_tasks(self, owner: str | None = None, limit: int = 100) -> list[dict]:
        """List active intake tasks for homepage/intake live status."""
        return await self.list_v3_active_tasks(owner=owner, limit=limit)

    async def list_recent_intake_tasks(self, owner: str | None = None, limit: int = 100) -> list[dict]:
        """List recent intake tasks, including terminal states for UI reconciliation."""
        return await self.list_tasks(owner=owner, limit=limit, runner_type="v3")

    async def mark_abandoned_intake_tasks_failed(self) -> int:
        """Mark unrecoverable intake tasks as failed after restart."""
        return await self.mark_abandoned_v3_tasks_failed()

    async def cleanup_old_tasks(self, days: int = 30) -> int:
        """Delete completed/failed tasks older than specified days."""
        conn = get_db()
        try:
            result = conn.execute("""
                DELETE FROM pipeline_tasks
                WHERE status IN (?, ?, ?)
                AND datetime(completed_at) < datetime('now', '-' || ? || ' days')
            """, (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED, days))
            conn.commit()
            deleted = result.rowcount
            if deleted > 0:
                log.info(f"Cleaned up {deleted} old tasks")
            return deleted
        finally:
            conn.close()

    def _normalize_task_row(self, row: dict) -> dict:
        """Normalize DB task rows for API/UI consumption."""
        row["status"] = str(row.get("status"))
        row["runner_type"] = row.get("runner_type") or "v3"
        return row


# Global singleton
task_manager = TaskManager()

