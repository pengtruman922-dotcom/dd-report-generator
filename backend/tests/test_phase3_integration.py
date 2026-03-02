"""Integration tests for Phase 3 features (task persistence + streaming)."""

import pytest
import asyncio
import json
import tempfile
import os
from unittest.mock import patch, AsyncMock

from services.task_manager import TaskManager, TaskStatus
from services.sse_manager import SSEManager


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

    try:
        os.unlink(path)
    except:
        pass


@pytest.mark.asyncio
async def test_task_with_streaming_progress(temp_db):
    """Test task execution with streaming progress updates."""
    _, mock_get_db = temp_db
    task_manager = TaskManager()
    sse_manager = SSEManager()

    task_id = "streaming-task-1"
    await task_manager.create_task(
        task_id,
        "report-1",
        {"company_name": "Test Co"},
        []
    )

    # Subscribe to SSE events
    queue = sse_manager.subscribe(task_id)

    # Create task that sends progress
    async def task_with_progress():
        for step in range(1, 7):
            await sse_manager.send_progress(task_id, step, 6, f"Step {step}")
            await asyncio.sleep(0.01)

    await task_manager.start_task(task_id, task_with_progress)

    # Collect progress events
    progress_events = []
    for _ in range(6):
        event = await asyncio.wait_for(queue.get(), timeout=1.0)
        data = json.loads(event["data"])
        progress_events.append(data["step"])

    await asyncio.sleep(0.05)  # Wait for completion

    # Verify progress sequence
    assert progress_events == [1, 2, 3, 4, 5, 6]

    # Verify task completed
    task = await task_manager.get_task(task_id)
    assert task["status"] == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_task_failure_with_error_event(temp_db):
    """Test that task failures send error events."""
    _, mock_get_db = temp_db
    task_manager = TaskManager()
    sse_manager = SSEManager()

    task_id = "failing-task"
    await task_manager.create_task(task_id, "report-1", {"name": "Test"}, [])

    queue = sse_manager.subscribe(task_id)

    async def failing_task():
        await sse_manager.send_progress(task_id, 1, 3, "Starting")
        await asyncio.sleep(0.01)
        await sse_manager.send_error(task_id, "Simulated failure")
        raise ValueError("Task failed")

    await task_manager.start_task(task_id, failing_task)
    await asyncio.sleep(0.1)

    # Collect events
    events = []
    while not queue.empty():
        event = await queue.get()
        events.append(event)

    # Should have progress and error events
    assert len(events) >= 2
    assert events[0]["event"] == "progress"
    assert events[1]["event"] == "error"

    # Verify task marked as failed
    task = await task_manager.get_task(task_id)
    assert task["status"] == TaskStatus.FAILED


@pytest.mark.asyncio
async def test_service_restart_recovery_with_streaming(temp_db):
    """Test recovering tasks after service restart with streaming."""
    _, mock_get_db = temp_db
    task_manager = TaskManager()
    sse_manager = SSEManager()

    # Create pending tasks
    await task_manager.create_task(
        "recover-1",
        "report-1",
        {"company_name": "Company A"},
        [("file.pdf", "content")]
    )
    await task_manager.create_task(
        "recover-2",
        "report-2",
        {"company_name": "Company B"},
        [("file.pdf", "content")]
    )

    # Subscribe to both tasks
    queue1 = sse_manager.subscribe("recover-1")
    queue2 = sse_manager.subscribe("recover-2")

    # Mock pipeline runner that sends progress
    async def mock_pipeline(**kwargs):
        task_id = kwargs["task_id"]
        await sse_manager.send_progress(task_id, 1, 3, "Recovered and running")
        await asyncio.sleep(0.01)
        await sse_manager.send_complete(task_id, f"report-{task_id}")

    # Recover tasks
    recovered = await task_manager.recover_tasks(mock_pipeline)
    assert recovered == 2

    await asyncio.sleep(0.1)

    # Verify both tasks received events
    event1 = await asyncio.wait_for(queue1.get(), timeout=1.0)
    event2 = await asyncio.wait_for(queue2.get(), timeout=1.0)

    assert event1["event"] == "progress"
    assert event2["event"] == "progress"


@pytest.mark.asyncio
async def test_concurrent_tasks_with_isolated_streams(temp_db):
    """Test multiple concurrent tasks with isolated streaming."""
    _, mock_get_db = temp_db
    task_manager = TaskManager()
    sse_manager = SSEManager()

    task_ids = [f"concurrent-{i}" for i in range(3)]
    queues = {}

    # Create and subscribe to tasks
    for tid in task_ids:
        await task_manager.create_task(tid, f"report-{tid}", {"name": tid}, [])
        queues[tid] = sse_manager.subscribe(tid)

    # Create tasks that send different progress
    async def task_with_id(tid, steps):
        for step in range(1, steps + 1):
            await sse_manager.send_progress(tid, step, steps, f"{tid} step {step}")
            await asyncio.sleep(0.01)

    # Start all tasks with different step counts
    await task_manager.start_task(task_ids[0], lambda: task_with_id(task_ids[0], 3))
    await task_manager.start_task(task_ids[1], lambda: task_with_id(task_ids[1], 4))
    await task_manager.start_task(task_ids[2], lambda: task_with_id(task_ids[2], 5))

    await asyncio.sleep(0.2)

    # Verify each queue received correct number of events
    events_0 = []
    while not queues[task_ids[0]].empty():
        events_0.append(await queues[task_ids[0]].get())

    events_1 = []
    while not queues[task_ids[1]].empty():
        events_1.append(await queues[task_ids[1]].get())

    events_2 = []
    while not queues[task_ids[2]].empty():
        events_2.append(await queues[task_ids[2]].get())

    assert len(events_0) == 3
    assert len(events_1) == 4
    assert len(events_2) == 5


@pytest.mark.asyncio
async def test_streaming_interruption_recovery(temp_db):
    """Test recovering from streaming connection interruption."""
    _, mock_get_db = temp_db
    task_manager = TaskManager()
    sse_manager = SSEManager()

    task_id = "interruption-test"
    await task_manager.create_task(task_id, "report-1", {"name": "Test"}, [])

    # First subscriber
    queue1 = sse_manager.subscribe(task_id)

    async def long_task():
        for step in range(1, 11):
            await sse_manager.send_progress(task_id, step, 10, f"Step {step}")
            await asyncio.sleep(0.01)

    await task_manager.start_task(task_id, long_task)

    # Receive first few events
    event1 = await asyncio.wait_for(queue1.get(), timeout=1.0)
    event2 = await asyncio.wait_for(queue1.get(), timeout=1.0)

    # Simulate disconnection and reconnection
    sse_manager.unsubscribe(task_id, queue1)
    queue2 = sse_manager.subscribe(task_id)  # New connection

    await asyncio.sleep(0.15)  # Wait for task to finish

    # New subscriber should receive remaining events
    remaining_events = []
    while not queue2.empty():
        remaining_events.append(await queue2.get())

    # Should have received some events (not all, since we reconnected late)
    assert len(remaining_events) > 0


@pytest.mark.asyncio
async def test_task_cancellation_with_cleanup(temp_db):
    """Test that cancelled tasks clean up streaming resources."""
    _, mock_get_db = temp_db
    task_manager = TaskManager()
    sse_manager = SSEManager()

    task_id = "cancel-test"
    await task_manager.create_task(task_id, "report-1", {"name": "Test"}, [])

    queue = sse_manager.subscribe(task_id)

    async def long_task():
        for step in range(1, 100):
            await sse_manager.send_progress(task_id, step, 100, f"Step {step}")
            await asyncio.sleep(0.01)

    await task_manager.start_task(task_id, long_task)
    await asyncio.sleep(0.05)  # Let it run a bit

    # Cancel task
    cancelled = await task_manager.cancel_task(task_id)
    assert cancelled is True

    await asyncio.sleep(0.05)

    # Verify task status
    task = await task_manager.get_task(task_id)
    assert task["status"] == TaskStatus.CANCELLED

    # Cleanup streaming resources
    sse_manager.unsubscribe(task_id, queue)
    assert task_id not in sse_manager._queues


@pytest.mark.asyncio
async def test_full_pipeline_with_persistence_and_streaming(temp_db):
    """Test complete pipeline flow with both persistence and streaming."""
    _, mock_get_db = temp_db
    task_manager = TaskManager()
    sse_manager = SSEManager()

    task_id = "full-pipeline"
    report_id = "report-full"

    await task_manager.create_task(
        task_id,
        report_id,
        {"company_name": "Full Test Co"},
        [("doc.pdf", "content")],
        owner="user1"
    )

    queue = sse_manager.subscribe(task_id)

    # Simulate full pipeline
    async def full_pipeline():
        steps = [
            "Extracting data",
            "Researching company",
            "Generating report",
            "Finalizing"
        ]

        for i, step_msg in enumerate(steps, 1):
            await task_manager.update_task_status(task_id, TaskStatus.RUNNING, current_step=i)
            await sse_manager.send_progress(task_id, i, len(steps), step_msg)
            await asyncio.sleep(0.02)

        # Send completion
        await sse_manager.send_complete(task_id, report_id)

    await task_manager.start_task(task_id, full_pipeline)
    await asyncio.sleep(0.2)

    # Collect all events
    events = []
    while not queue.empty():
        events.append(await queue.get())

    # Verify event sequence
    assert len(events) == 5  # 4 progress + 1 complete
    assert all(e["event"] in ["progress", "complete"] for e in events)
    assert events[-1]["event"] == "complete"

    # Verify final task state
    task = await task_manager.get_task(task_id)
    assert task["status"] == TaskStatus.COMPLETED
    assert task["current_step"] == 4
    assert task["completed_at"] is not None


@pytest.mark.asyncio
async def test_error_propagation_through_streaming(temp_db):
    """Test that errors are properly propagated through streaming."""
    _, mock_get_db = temp_db
    task_manager = TaskManager()
    sse_manager = SSEManager()

    task_id = "error-propagation"
    await task_manager.create_task(task_id, "report-1", {"name": "Test"}, [])

    queue = sse_manager.subscribe(task_id)

    async def task_with_error():
        await sse_manager.send_progress(task_id, 1, 3, "Step 1")
        await asyncio.sleep(0.01)
        await sse_manager.send_progress(task_id, 2, 3, "Step 2")
        await asyncio.sleep(0.01)

        error_msg = "Critical error occurred"
        await sse_manager.send_error(task_id, error_msg)
        raise RuntimeError(error_msg)

    await task_manager.start_task(task_id, task_with_error)
    await asyncio.sleep(0.1)

    # Collect events
    events = []
    while not queue.empty():
        events.append(await queue.get())

    # Verify error event was sent
    error_events = [e for e in events if e["event"] == "error"]
    assert len(error_events) == 1

    error_data = json.loads(error_events[0]["data"])
    assert "Critical error occurred" in error_data["error"]

    # Verify task failed
    task = await task_manager.get_task(task_id)
    assert task["status"] == TaskStatus.FAILED
    assert "Critical error occurred" in task["error_message"]


@pytest.mark.asyncio
async def test_performance_under_load(temp_db):
    """Test system performance with many concurrent tasks and streams."""
    _, mock_get_db = temp_db
    task_manager = TaskManager()
    sse_manager = SSEManager()

    num_tasks = 10
    task_ids = [f"load-test-{i}" for i in range(num_tasks)]

    # Create all tasks
    for tid in task_ids:
        await task_manager.create_task(tid, f"report-{tid}", {"name": tid}, [])

    # Subscribe to all
    queues = {tid: sse_manager.subscribe(tid) for tid in task_ids}

    # Start all tasks
    async def task_work(tid):
        for step in range(1, 6):
            await sse_manager.send_progress(tid, step, 5, f"Step {step}")
            await asyncio.sleep(0.005)

    for tid in task_ids:
        await task_manager.start_task(tid, lambda t=tid: task_work(t))

    # Wait for all to complete
    await asyncio.sleep(0.5)

    # Verify all completed
    for tid in task_ids:
        task = await task_manager.get_task(tid)
        assert task["status"] == TaskStatus.COMPLETED

    # Verify all received events
    for tid in task_ids:
        events_count = 0
        while not queues[tid].empty():
            await queues[tid].get()
            events_count += 1
        assert events_count == 5  # 5 progress events per task