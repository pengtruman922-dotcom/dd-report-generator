"""Tests for intake runtime cleanup after report deletion."""

import asyncio

from routers import intake as intake_router


def test_cleanup_runtime_state_for_report_clears_tasks_snapshots_and_sse():
    report_id = "rpt_cleanup"
    task_id = "task_cleanup"

    intake_router._intake_tasks.clear()
    intake_router._update_snapshots.clear()
    intake_router.sse_manager.clear_task(report_id)
    intake_router.sse_manager.clear_task(task_id)

    intake_router._intake_tasks[task_id] = {
        "task_id": task_id,
        "report_id": report_id,
        "status": "running",
    }
    intake_router._update_snapshots[task_id] = {"report_id": report_id}

    queue = intake_router.sse_manager.subscribe(task_id)
    queue_report = intake_router.sse_manager.subscribe(report_id)
    asyncio.run(intake_router.sse_manager.send_progress(task_id, 1, 3, "Running"))
    asyncio.run(intake_router.sse_manager.send_progress(report_id, 1, 3, "Report event"))

    cleared = intake_router.cleanup_runtime_state_for_report(report_id)

    assert task_id in cleared
    assert task_id not in intake_router._intake_tasks
    assert task_id not in intake_router._update_snapshots
    assert task_id not in intake_router.sse_manager._queues
    assert task_id not in intake_router.sse_manager._history
    assert report_id not in intake_router.sse_manager._queues
    assert report_id not in intake_router.sse_manager._history

    # local queue objects may still exist, but should no longer be tracked
    assert queue is not None
    assert queue_report is not None
