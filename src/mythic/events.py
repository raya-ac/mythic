"""Structured runtime events for cognition streams."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CognitionEvent:
    """A single observable runtime event."""

    type: str
    data: dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    session_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "type": self.type,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "data": self.data,
        }


EventCallback = Callable[[CognitionEvent], None]


class EventBus:
    """In-process event bus with replayable recent history."""

    def __init__(self, max_events: int = 1000):
        self._events: deque[CognitionEvent] = deque(maxlen=max_events)
        self._callbacks: list[EventCallback] = []
        self._queues: list[asyncio.Queue[CognitionEvent]] = []

    def emit(
        self,
        event_type: str,
        data: dict[str, Any] | None = None,
        *,
        session_id: str | None = None,
    ) -> CognitionEvent:
        event = CognitionEvent(
            type=event_type,
            data=data or {},
            session_id=session_id,
        )
        self._events.append(event)

        for callback in list(self._callbacks):
            callback(event)

        for queue in list(self._queues):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass

        return event

    def recent(self, limit: int = 50) -> list[CognitionEvent]:
        if limit <= 0:
            return list(self._events)
        return list(self._events)[-limit:]

    def subscribe(self, callback: EventCallback) -> Callable[[], None]:
        self._callbacks.append(callback)

        def unsubscribe() -> None:
            if callback in self._callbacks:
                self._callbacks.remove(callback)

        return unsubscribe

    async def stream(self, max_queue_size: int = 100) -> AsyncIterator[CognitionEvent]:
        queue: asyncio.Queue[CognitionEvent] = asyncio.Queue(maxsize=max_queue_size)
        self._queues.append(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            if queue in self._queues:
                self._queues.remove(queue)

