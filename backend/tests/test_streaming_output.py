"""Tests for SSE streaming output functionality."""

import pytest
import asyncio
import json
from unittest.mock import AsyncMock

from services.sse_manager import SSEManager


@pytest.mark.asyncio
async def test_subscribe_creates_queue():
    """Test that subscribing creates a new queue."""
    manager = SSEManager()
    task_id = "test-task-1"

    queue = manager.subscribe(task_id)

    assert queue is not None
    assert isinstance(queue, asyncio.Queue)
    assert task_id in manager._queues
    assert queue in manager._queues[task_id]


@pytest.mark.asyncio
async def test_multiple_subscribers():
    """Test multiple subscribers for the same task."""
    manager = SSEManager()
    task_id = "test-task-multi"

    queue1 = manager.subscribe(task_id)
    queue2 = manager.subscribe(task_id)
    queue3 = manager.subscribe(task_id)

    assert len(manager._queues[task_id]) == 3
    assert queue1 in manager._queues[task_id]
    assert queue2 in manager._queues[task_id]
    assert queue3 in manager._queues[task_id]


@pytest.mark.asyncio
async def test_unsubscribe_removes_queue():
    """Test that unsubscribing removes the queue."""
    manager = SSEManager()
    task_id = "test-task-unsub"

    queue = manager.subscribe(task_id)
    assert task_id in manager._queues

    manager.unsubscribe(task_id, queue)
    assert task_id not in manager._queues


@pytest.mark.asyncio
async def test_unsubscribe_one_of_many():
    """Test unsubscribing one subscriber doesn't affect others."""
    manager = SSEManager()
    task_id = "test-task-partial-unsub"

    queue1 = manager.subscribe(task_id)
    queue2 = manager.subscribe(task_id)
    queue3 = manager.subscribe(task_id)

    manager.unsubscribe(task_id, queue2)

    assert len(manager._queues[task_id]) == 2
    assert queue1 in manager._queues[task_id]
    assert queue2 not in manager._queues[task_id]
    assert queue3 in manager._queues[task_id]


@pytest.mark.asyncio
async def test_send_event_to_subscribers():
    """Test sending an event to all subscribers."""
    manager = SSEManager()
    task_id = "test-task-send"

    queue1 = manager.subscribe(task_id)
    queue2 = manager.subscribe(task_id)

    await manager.send(task_id, "test_event", {"message": "Hello"})

    # Both queues should receive the event
    event1 = await asyncio.wait_for(queue1.get(), timeout=1.0)
    event2 = await asyncio.wait_for(queue2.get(), timeout=1.0)

    assert event1["event"] == "test_event"
    assert event2["event"] == "test_event"

    # Parse JSON data
    data1 = json.loads(event1["data"])
    data2 = json.loads(event2["data"])

    assert data1["message"] == "Hello"
    assert data2["message"] == "Hello"


@pytest.mark.asyncio
async def test_send_to_nonexistent_task():
    """Test sending to a task with no subscribers doesn't error."""
    manager = SSEManager()

    # Should not raise exception
    await manager.send("nonexistent-task", "test", {"data": "value"})


@pytest.mark.asyncio
async def test_send_progress_event():
    """Test sending progress events."""
    manager = SSEManager()
    task_id = "test-progress"

    queue = manager.subscribe(task_id)

    await manager.send_progress(task_id, step=3, total=6, message="Processing data")

    event = await asyncio.wait_for(queue.get(), timeout=1.0)

    assert event["event"] == "progress"
    data = json.loads(event["data"])
    assert data["step"] == 3
    assert data["total"] == 6
    assert data["message"] == "Processing data"


@pytest.mark.asyncio
async def test_send_stream_chunk():
    """Test sending streaming content chunks."""
    manager = SSEManager()
    task_id = "test-stream"

    queue = manager.subscribe(task_id)

    chunk_text = "This is a chunk of report content."
    await manager.send_stream_chunk(task_id, chunk_text)

    event = await asyncio.wait_for(queue.get(), timeout=1.0)

    assert event["event"] == "stream"
    data = json.loads(event["data"])
    assert data["chunk"] == chunk_text


@pytest.mark.asyncio
async def test_send_complete_event():
    """Test sending completion event."""
    manager = SSEManager()
    task_id = "test-complete"

    queue = manager.subscribe(task_id)

    report_id = "report-123"
    await manager.send_complete(task_id, report_id)

    event = await asyncio.wait_for(queue.get(), timeout=1.0)

    assert event["event"] == "complete"
    data = json.loads(event["data"])
    assert data["report_id"] == report_id


@pytest.mark.asyncio
async def test_send_error_event():
    """Test sending error event."""
    manager = SSEManager()
    task_id = "test-error"

    queue = manager.subscribe(task_id)

    error_msg = "Network connection failed"
    await manager.send_error(task_id, error_msg)

    event = await asyncio.wait_for(queue.get(), timeout=1.0)

    assert event["event"] == "error"
    data = json.loads(event["data"])
    assert data["error"] == error_msg


@pytest.mark.asyncio
async def test_event_ordering():
    """Test that events are received in the order they were sent."""
    manager = SSEManager()
    task_id = "test-ordering"

    queue = manager.subscribe(task_id)

    # Send multiple events in sequence
    await manager.send_progress(task_id, 1, 5, "Step 1")
    await manager.send_progress(task_id, 2, 5, "Step 2")
    await manager.send_progress(task_id, 3, 5, "Step 3")

    # Receive and verify order
    event1 = await asyncio.wait_for(queue.get(), timeout=1.0)
    event2 = await asyncio.wait_for(queue.get(), timeout=1.0)
    event3 = await asyncio.wait_for(queue.get(), timeout=1.0)

    data1 = json.loads(event1["data"])
    data2 = json.loads(event2["data"])
    data3 = json.loads(event3["data"])

    assert data1["step"] == 1
    assert data2["step"] == 2
    assert data3["step"] == 3


@pytest.mark.asyncio
async def test_concurrent_sends():
    """Test sending events concurrently to multiple tasks."""
    manager = SSEManager()

    task_ids = [f"task-{i}" for i in range(5)]
    queues = {tid: manager.subscribe(tid) for tid in task_ids}

    # Send events concurrently
    await asyncio.gather(*[
        manager.send_progress(tid, i, 10, f"Task {i}")
        for i, tid in enumerate(task_ids)
    ])

    # Verify each queue received its event
    for i, tid in enumerate(task_ids):
        event = await asyncio.wait_for(queues[tid].get(), timeout=1.0)
        data = json.loads(event["data"])
        assert data["step"] == i
        assert data["message"] == f"Task {i}"


@pytest.mark.asyncio
async def test_string_data_not_double_encoded():
    """Test that string data is not double-encoded as JSON."""
    manager = SSEManager()
    task_id = "test-string"

    queue = manager.subscribe(task_id)

    # Send plain string data
    await manager.send(task_id, "message", "Plain text message")

    event = await asyncio.wait_for(queue.get(), timeout=1.0)

    assert event["event"] == "message"
    assert event["data"] == "Plain text message"  # Should not be JSON-encoded


@pytest.mark.asyncio
async def test_queue_isolation():
    """Test that events for one task don't leak to another."""
    manager = SSEManager()

    queue1 = manager.subscribe("task-1")
    queue2 = manager.subscribe("task-2")

    await manager.send_progress("task-1", 1, 5, "Task 1 progress")
    await manager.send_progress("task-2", 2, 5, "Task 2 progress")

    # Queue 1 should only have task-1 event
    event1 = await asyncio.wait_for(queue1.get(), timeout=1.0)
    data1 = json.loads(event1["data"])
    assert data1["message"] == "Task 1 progress"

    # Queue 2 should only have task-2 event
    event2 = await asyncio.wait_for(queue2.get(), timeout=1.0)
    data2 = json.loads(event2["data"])
    assert data2["message"] == "Task 2 progress"

    # Queues should be empty
    assert queue1.empty()
    assert queue2.empty()


@pytest.mark.asyncio
async def test_late_subscriber():
    """Test that late subscribers don't receive past events."""
    manager = SSEManager()
    task_id = "test-late"

    # Send event before subscription
    await manager.send_progress(task_id, 1, 5, "Early event")

    # Subscribe late
    queue = manager.subscribe(task_id)

    # Send event after subscription
    await manager.send_progress(task_id, 2, 5, "Late event")

    # Should only receive the late event
    event = await asyncio.wait_for(queue.get(), timeout=1.0)
    data = json.loads(event["data"])
    assert data["step"] == 2
    assert data["message"] == "Late event"

    # Queue should be empty (no early event)
    assert queue.empty()


@pytest.mark.asyncio
async def test_streaming_large_chunks():
    """Test streaming large content chunks."""
    manager = SSEManager()
    task_id = "test-large"

    queue = manager.subscribe(task_id)

    # Send large chunk
    large_chunk = "A" * 10000  # 10KB chunk
    await manager.send_stream_chunk(task_id, large_chunk)

    event = await asyncio.wait_for(queue.get(), timeout=1.0)
    data = json.loads(event["data"])
    assert len(data["chunk"]) == 10000
    assert data["chunk"] == large_chunk


@pytest.mark.asyncio
async def test_rapid_event_sending():
    """Test sending many events rapidly."""
    manager = SSEManager()
    task_id = "test-rapid"

    queue = manager.subscribe(task_id)

    # Send 100 events rapidly
    num_events = 100
    for i in range(num_events):
        await manager.send_progress(task_id, i, num_events, f"Event {i}")

    # Receive all events
    received = []
    for _ in range(num_events):
        event = await asyncio.wait_for(queue.get(), timeout=2.0)
        data = json.loads(event["data"])
        received.append(data["step"])

    assert len(received) == num_events
    assert received == list(range(num_events))


@pytest.mark.asyncio
async def test_cleanup_after_unsubscribe_all():
    """Test that task is removed from queues dict when all subscribers leave."""
    manager = SSEManager()
    task_id = "test-cleanup"

    queue1 = manager.subscribe(task_id)
    queue2 = manager.subscribe(task_id)

    assert task_id in manager._queues

    manager.unsubscribe(task_id, queue1)
    assert task_id in manager._queues  # Still has queue2

    manager.unsubscribe(task_id, queue2)
    assert task_id not in manager._queues  # All subscribers gone