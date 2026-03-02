"""SSE event broadcasting for pipeline progress."""

from __future__ import annotations

import asyncio
import json
from typing import Any


class SSEManager:
    """Manages per-task SSE event queues."""

    def __init__(self):
        self._queues: dict[str, list[asyncio.Queue]] = {}

    def subscribe(self, task_id: str) -> asyncio.Queue:
        """Create a new queue for a subscriber."""
        q: asyncio.Queue = asyncio.Queue()
        self._queues.setdefault(task_id, []).append(q)
        return q

    def unsubscribe(self, task_id: str, q: asyncio.Queue):
        """Remove a subscriber queue."""
        if task_id in self._queues:
            self._queues[task_id] = [x for x in self._queues[task_id] if x is not q]
            if not self._queues[task_id]:
                del self._queues[task_id]

    async def send(self, task_id: str, event: str, data: Any):
        """Push an event to all subscribers of *task_id*."""
        payload = json.dumps(data, ensure_ascii=False) if not isinstance(data, str) else data
        for q in self._queues.get(task_id, []):
            await q.put({"event": event, "data": payload})

    async def send_progress(self, task_id: str, step: int, total: int, message: str):
        await self.send(task_id, "progress", {"step": step, "total": total, "message": message})

    async def send_stream_chunk(self, task_id: str, chunk: str):
        """Send a streaming chunk of report content."""
        await self.send(task_id, "stream", {"chunk": chunk})

    async def send_complete(self, task_id: str, report_id: str):
        await self.send(task_id, "complete", {"report_id": report_id})

    async def send_error(self, task_id: str, error: str):
        await self.send(task_id, "error", {"error": error})


# Global singleton
sse_manager = SSEManager()
