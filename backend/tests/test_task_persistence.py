"""Tests for task persistence and recovery functionality."""

import pytest
import asyncio
import json
import tempfile
import os
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from services.task_manager import TaskManager, TaskStatus


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    with patch('services.task_manager.get_db') as mock_get_db:
        import sqlite3
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        mock_get_db.return_value = conn

        yield path, mock_get_db

    # Cleanup
    try:
        os.unlink(path)
    except:
        pass


@pytest.mark.asyncio
async def test_task_creation(temp_db):
    """Test creating a new task record."""
    _, mock_get_db = temp_db
    manager = TaskManager()

    task_id = "test-task-1"
    report_id = "report-1"
    excel_row = {"company_name": "Test Company", "industry": "Tech"}
    attachment_items = [("file1.pdf", "content1"), ("file2.pdf", "content2")]

    await manager.create_task(
        task_id=task_id,
        report_id=report_id,
        excel_row=excel_row,
        attachment_items=attachment_items,
        owner="user1"
    )

    # Verify task was created
    task = await manager.get_task(task_id)
    assert task is not None
    assert task["task_id"] == task_id
    assert task["report_id"] == report_id
    assert task["status"] == TaskStatus.PENDING
    assert task["owner"] == "user1"

    # Verify JSON fields
    stored_row = json.loads(task["excel_row"])
    assert stored_row["company_name"] == "Test Company"


@pytest.mark.asyncio
async def test_task_status_update(temp_db):
    """Test updating task status and progress."""
    _, mock_get_db = temp_db
    manager = TaskManager()

    task_id = "test-task-2"
    await manager.create_task(
        task_id=task_id,
        report_id="report-2",
        excel_row={"company_name": "Test"},
        attachment_items=[]
    )

    # Update to running
    await manager.update_task_status(task_id, TaskStatus.RUNNING, current_step=1)
    task = await manager.get_task(task_id)
    assert task["status"] == TaskStatus.RUNNING
    assert task["current_step"] == 1

    # Update to completed
    await manager.update_task_status(task_id, TaskStatus.COMPLETED, current_step=6)
    task = await manager.get_task(task_id)
    assert task["status"] == TaskStatus.COMPLETED
    assert task["current_step"] == 6
    assert task["completed_at"] is not None


@pytest.mark.asyncio
async def test_task_failure_with_error(temp_db):
    """Test recording task failure with error message."""
    _, mock_get_db = temp_db
    manager = TaskManager()

    task_id = "test-task-3"
    await manager.create_task(
        task_id=task_id,
        report_id="report-3",
        excel_row={"company_name": "Test"},
        attachment_items=[]
    )

    error_msg = "Network connection failed"
    await manager.update_task_status(
        task_id,
        TaskStatus.FAILED,
        error_message=error_msg
    )

    task = await manager.get_task(task_id)
    assert task["status"] == TaskStatus.FAILED
    assert task["error_message"] == error_msg
    assert task["completed_at"] is not None


@pytest.mark.asyncio
async def test_list_tasks_with_filters(temp_db):
    """Test listing tasks with status and owner filters."""
    _, mock_get_db = temp_db
    manager = TaskManager()

    # Create multiple tasks
    await manager.create_task("task-1", "report-1", {"name": "A"}, [], owner="user1")
    await manager.create_task("task-2", "report-2", {"name": "B"}, [], owner="user2")
    await manager.create_task("task-3", "report-3", {"name": "C"}, [], owner="user1")

    await manager.update_task_status("task-1", TaskStatus.RUNNING)
    await manager.update_task_status("task-2", TaskStatus.COMPLETED)

    # Filter by status
    running_tasks = await manager.list_tasks(status=TaskStatus.RUNNING)
    assert len(running_tasks) == 1
    assert running_tasks[0]["task_id"] == "task-1"

    # Filter by owner
    user1_tasks = await manager.list_tasks(owner="user1")
    assert len(user1_tasks) == 2

    # Filter by both
    user1_pending = await manager.list_tasks(status=TaskStatus.PENDING, owner="user1")
    assert len(user1_pending) == 1
    assert user1_pending[0]["task_id"] == "task-3"


@pytest.mark.asyncio
async def test_get_pending_tasks(temp_db):
    """Test retrieving pending and running tasks for recovery."""
    _, mock_get_db = temp_db
    manager = TaskManager()

    # Create tasks with different statuses
    await manager.create_task("task-pending", "r1", {"name": "A"}, [])
    await manager.create_task("task-running", "r2", {"name": "B"}, [])
    await manager.create_task("task-completed", "r3", {"name": "C"}, [])
    await manager.create_task("task-failed", "r4", {"name": "D"}, [])

    await manager.update_task_status("task-running", TaskStatus.RUNNING)
    await manager.update_task_status("task-completed", TaskStatus.COMPLETED)
    await manager.update_task_status("task-failed", TaskStatus.FAILED)

    # Get pending tasks (should include pending and running)
    pending = await manager.get_pending_tasks()
    assert len(pending) == 2
    task_ids = {t["task_id"] for t in pending}
    assert "task-pending" in task_ids
    assert "task-running" in task_ids


@pytest.mark.asyncio
async def test_start_task_success(temp_db):
    """Test starting a task that completes successfully."""
    _, mock_get_db = temp_db
    manager = TaskManager()

    task_id = "test-task-start"
    await manager.create_task(task_id, "report-1", {"name": "Test"}, [])

    # Create a simple task coroutine
    completed = asyncio.Event()

    async def task_coro():
        await asyncio.sleep(0.01)
        completed.set()

    await manager.start_task(task_id, task_coro)

    # Wait for completion
    await asyncio.wait_for(completed.wait(), timeout=1.0)
    await asyncio.sleep(0.05)  # Give time for status update

    task = await manager.get_task(task_id)
    assert task["status"] == TaskStatus.COMPLETED
    assert not manager.is_task_running(task_id)


@pytest.mark.asyncio
async def test_start_task_failure(temp_db):
    """Test starting a task that fails with exception."""
    _, mock_get_db = temp_db
    manager = TaskManager()

    task_id = "test-task-fail"
    await manager.create_task(task_id, "report-1", {"name": "Test"}, [])

    async def failing_task():
        await asyncio.sleep(0.01)
        raise ValueError("Task failed intentionally")

    await manager.start_task(task_id, failing_task)
    await asyncio.sleep(0.1)  # Wait for failure

    task = await manager.get_task(task_id)
    assert task["status"] == TaskStatus.FAILED
    assert "Task failed intentionally" in task["error_message"]


@pytest.mark.asyncio
async def test_cancel_running_task(temp_db):
    """Test cancelling a running task."""
    _, mock_get_db = temp_db
    manager = TaskManager()

    task_id = "test-task-cancel"
    await manager.create_task(task_id, "report-1", {"name": "Test"}, [])

    # Start a long-running task
    async def long_task():
        await asyncio.sleep(10)  # Will be cancelled before this

    await manager.start_task(task_id, long_task)
    await asyncio.sleep(0.01)  # Let it start

    # Cancel the task
    cancelled = await manager.cancel_task(task_id)
    assert cancelled is True

    await asyncio.sleep(0.05)  # Wait for cancellation

    task = await manager.get_task(task_id)
    assert task["status"] == TaskStatus.CANCELLED


@pytest.mark.asyncio
async def test_cancel_nonexistent_task(temp_db):
    """Test cancelling a task that doesn't exist."""
    _, mock_get_db = temp_db
    manager = TaskManager()

    cancelled = await manager.cancel_task("nonexistent-task")
    assert cancelled is False


@pytest.mark.asyncio
async def test_task_recovery(temp_db):
    """Test recovering pending tasks after restart."""
    _, mock_get_db = temp_db
    manager = TaskManager()

    # Create pending and running tasks
    await manager.create_task(
        "task-recover-1",
        "report-1",
        {"company_name": "Company A"},
        [("file1.pdf", "content1")],
        owner="user1"
    )
    await manager.create_task(
        "task-recover-2",
        "report-2",
        {"company_name": "Company B"},
        [("file2.pdf", "content2")],
        owner="user2"
    )
    await manager.update_task_status("task-recover-2", TaskStatus.RUNNING)

    # Mock pipeline runner
    recovered_tasks = []

    async def mock_pipeline_runner(**kwargs):
        recovered_tasks.append(kwargs["task_id"])
        await asyncio.sleep(0.01)

    # Recover tasks
    count = await manager.recover_tasks(mock_pipeline_runner)

    assert count == 2
    await asyncio.sleep(0.1)  # Wait for tasks to start

    assert "task-recover-1" in recovered_tasks
    assert "task-recover-2" in recovered_tasks


@pytest.mark.asyncio
async def test_cleanup_old_tasks(temp_db):
    """Test cleaning up old completed tasks."""
    _, mock_get_db = temp_db
    manager = TaskManager()

    # Create and complete tasks
    await manager.create_task("task-old", "report-1", {"name": "Old"}, [])
    await manager.create_task("task-recent", "report-2", {"name": "Recent"}, [])

    await manager.update_task_status("task-old", TaskStatus.COMPLETED)
    await manager.update_task_status("task-recent", TaskStatus.COMPLETED)

    # Manually set old task's completed_at to 31 days ago
    conn = mock_get_db.return_value
    old_date = (datetime.now() - timedelta(days=31)).isoformat()
    conn.execute(
        "UPDATE pipeline_tasks SET completed_at = ? WHERE task_id = ?",
        (old_date, "task-old")
    )
    conn.commit()

    # Cleanup tasks older than 30 days
    deleted = await manager.cleanup_old_tasks(days=30)

    assert deleted == 1

    # Verify old task is gone, recent task remains
    old_task = await manager.get_task("task-old")
    recent_task = await manager.get_task("task-recent")

    assert old_task is None
    assert recent_task is not None


@pytest.mark.asyncio
async def test_concurrent_task_execution(temp_db):
    """Test multiple tasks running concurrently."""
    _, mock_get_db = temp_db
    manager = TaskManager()

    # Create multiple tasks
    task_ids = [f"concurrent-{i}" for i in range(5)]
    for tid in task_ids:
        await manager.create_task(tid, f"report-{tid}", {"name": tid}, [])

    # Track completion
    completed = []

    async def task_coro(tid):
        await asyncio.sleep(0.05)
        completed.append(tid)

    # Start all tasks
    for tid in task_ids:
        await manager.start_task(tid, lambda t=tid: task_coro(t))

    # Wait for all to complete
    await asyncio.sleep(0.2)

    assert len(completed) == 5
    assert set(completed) == set(task_ids)

    # Verify all completed
    for tid in task_ids:
        task = await manager.get_task(tid)
        assert task["status"] == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_task_state_consistency(temp_db):
    """Test that task state remains consistent across operations."""
    _, mock_get_db = temp_db
    manager = TaskManager()

    task_id = "consistency-test"
    await manager.create_task(
        task_id,
        "report-1",
        {"company_name": "Test Co"},
        [("doc.pdf", "content")],
        owner="user1",
        is_regeneration=True
    )

    # Get initial state
    task1 = await manager.get_task(task_id)
    assert task1["is_regeneration"] == 1
    assert task1["owner"] == "user1"

    # Update status
    await manager.update_task_status(task_id, TaskStatus.RUNNING, current_step=3)

    # Verify state preserved
    task2 = await manager.get_task(task_id)
    assert task2["is_regeneration"] == 1
    assert task2["owner"] == "user1"
    assert task2["status"] == TaskStatus.RUNNING
    assert task2["current_step"] == 3

    # Complete task
    await manager.update_task_status(task_id, TaskStatus.COMPLETED)

    # Verify final state
    task3 = await manager.get_task(task_id)
    assert task3["is_regeneration"] == 1
    assert task3["owner"] == "user1"
    assert task3["status"] == TaskStatus.COMPLETED