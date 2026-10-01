"""Server-Sent Events broadcaster for the live at-risk feed."""
from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse


class Broadcaster:
    def __init__(self, replay: int = 30) -> None:
        self.subscribers: set[asyncio.Queue] = set()
        self.recent: deque[dict[str, Any]] = deque(maxlen=replay)
        self.loop: asyncio.AbstractEventLoop | None = None

    def publish(self, message: dict[str, Any]) -> None:
        """Thread-safe: request handlers run in a worker thread."""
        self.recent.append(message)
        if self.loop is None:
            return
        for queue in list(self.subscribers):
            self.loop.call_soon_threadsafe(queue.put_nowait, message)

    async def stream(self) -> AsyncIterator[str]:
        queue: asyncio.Queue = asyncio.Queue()
        self.subscribers.add(queue)
        try:
            for message in list(self.recent):
                yield f"data: {json.dumps(message, default=str)}\n\n"
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"data: {json.dumps(message, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            self.subscribers.discard(queue)


broadcaster = Broadcaster()
router = APIRouter(tags=["live"])


@router.get("/stream/at-risk")
async def stream_at_risk() -> StreamingResponse:
    return StreamingResponse(broadcaster.stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
