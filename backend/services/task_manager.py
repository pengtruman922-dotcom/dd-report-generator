"""Task persistence and recovery manager for pipeline tasks.

Persists running tasks to database and supports automatic recovery on service restart.
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
        """Create a new task record in the database."""
        conn = get_db()
        try:
            conn.execute("""
                INSERT INTO pipeline_tasks (
                    task_id, report_id, status, owner,
                    excel_row, attachment_items, failed_attachments,
                    attachments_info, is_regeneration
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            ))
            conn.commit()
            log.info(f"Created task record: {task_id}")
        finally:
            conn.close()

    async def update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        current_step: int | None = None,
        error_message: str | None = None,
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

            if status == TaskStatus.COMPLETED or status == TaskStatus.FAILED:
                updates.append("completed_at = ?")
                values.append(datetime.now().isoformat())

            values.append(task_id)

            conn.execute(
                f"UPDATE pipeline_tasks SET {', '.join(updates)} WHERE task_id = ?",
                values
            )
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
                return dict(row)
            return None
        finally:
            conn.close()

    async def list_tasks(
        self,
        status: TaskStatus | None = None,
        owner: str | None = None,
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

            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    async def get_pending_tasks(self) -> list[dict]:
        """Get all pending or running tasks (for recovery)."""
        conn = get_db()
        try:
            rows = conn.execute("""
                SELECT * FROM pipeline_tasks
                WHERE status IN (?, ?)
                ORDER BY created_at ASC
            """, (TaskStatus.PENDING, TaskStatus.RUNNING)).fetchall()
            return [dict(row) for row in rows]
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
        """Recover pending/running tasks after service restart.

        Args:
            pipeline_runner: Async function that takes task parameters and runs the pipeline

        Returns:
            Number of tasks recovered
        """
        pending_tasks = await self.get_pending_tasks()
        recovered = 0

        for task_data in pending_tasks:
            task_id = task_data["task_id"]
            try:
                # Parse stored data
                excel_row = json.loads(task_data["excel_row"])
                attachment_items_data = json.loads(task_data["attachment_items"])
                attachment_items = [(name, text) for name, text in attachment_items_data]
                failed_attachments = json.loads(task_data["failed_attachments"])
                attachments_info = json.loads(task_data["attachments_info"])
                is_regeneration = bool(task_data["is_regeneration"])
                owner = task_data["owner"]

                log.info(f"Recovering task {task_id} (owner={owner})")

                # Create task coroutine with proper closure
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

                # Start the task
                await self.start_task(task_id, create_task_coro)
                recovered += 1

            except Exception as e:
                log.error(f"Failed to recover task {task_id}: {e}")
                await self.update_task_status(
                    task_id,
                    TaskStatus.FAILED,
                    error_message=f"Recovery failed: {e}"
                )

        if recovered > 0:
            log.info(f"Recovered {recovered} tasks")

        return recovered

    def is_task_running(self, task_id: str) -> bool:
        """Check if a task is currently running in memory."""
        task = self._running_tasks.get(task_id)
        return task is not None and not task.done()

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


# Global singleton
task_manager = TaskManager()

