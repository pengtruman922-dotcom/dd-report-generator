"""Task management endpoints for pipeline tasks."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import get_current_user
from services.task_manager import task_manager, TaskStatus

router = APIRouter()


class CancelTaskRequest(BaseModel):
    task_id: str


@router.get("/list")
async def list_tasks(
    status: str | None = None,
    owner: str | None = None,
    limit: int = 100,
    user: dict = Depends(get_current_user),
):
    """List pipeline tasks with optional filtering."""
    # Non-admin users can only see their own tasks
    if user["role"] != "admin":
        owner = user["username"]

    # Validate status if provided
    task_status = None
    if status:
        try:
            task_status = TaskStatus(status)
        except ValueError:
            raise HTTPException(400, f"Invalid status: {status}")

    tasks = await task_manager.list_tasks(
        status=task_status,
        owner=owner,
        limit=limit,
    )

    return {"tasks": tasks, "total": len(tasks)}


@router.get("/{task_id}")
async def get_task(task_id: str, user: dict = Depends(get_current_user)):
    """Get details of a specific task."""
    task = await task_manager.get_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")

    # Check access permissions
    if user["role"] != "admin" and task.get("owner") != user["username"]:
        raise HTTPException(403, "无权访问此任务")

    return task


@router.post("/cancel")
async def cancel_task(req: CancelTaskRequest, user: dict = Depends(get_current_user)):
    """Cancel a running task."""
    task = await task_manager.get_task(req.task_id)
    if not task:
        raise HTTPException(404, "Task not found")

    # Check access permissions
    if user["role"] != "admin" and task.get("owner") != user["username"]:
        raise HTTPException(403, "无权取消此任务")

    # Check if task is cancellable
    if task["status"] not in [TaskStatus.PENDING, TaskStatus.RUNNING]:
        raise HTTPException(400, f"任务状态为 {task['status']}，无法取消")

    success = await task_manager.cancel_task(req.task_id)
    if not success:
        raise HTTPException(400, "任务未在运行中，无法取消")

    return {"status": "ok", "task_id": req.task_id}


@router.post("/cleanup")
async def cleanup_old_tasks(days: int = 30, user: dict = Depends(get_current_user)):
    """Cleanup old completed/failed tasks (admin only)."""
    if user["role"] != "admin":
        raise HTTPException(403, "仅管理员可执行此操作")

    deleted = await task_manager.cleanup_old_tasks(days=days)
    return {"deleted": deleted}
