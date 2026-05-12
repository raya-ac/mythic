"""Replayable cognition stream models."""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from mythic.events import CognitionEvent


def normalize_event_types(event_types: str | Iterable[str] | None) -> list[str] | None:
    """Return a stable list of event type filters."""

    if event_types is None:
        return None
    if isinstance(event_types, str):
        return [event_types]
    normalized = [event_type for event_type in event_types if event_type]
    return normalized or None


@dataclass(frozen=True)
class StreamCheckpoint:
    """A named cursor into the persisted cognition event stream."""

    name: str
    last_event_id: str | None = None
    filters: dict[str, Any] = field(default_factory=dict)
    event_count: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "last_event_id": self.last_event_id,
            "filters": self.filters,
            "event_count": self.event_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StreamCheckpoint":
        return cls(
            name=data["name"],
            last_event_id=data.get("last_event_id"),
            filters=dict(data.get("filters", {})),
            event_count=int(data.get("event_count", 0)),
            created_at=float(data.get("created_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
        )


@dataclass(frozen=True)
class EventReplay:
    """A bounded replay from the cognition event stream."""

    events: list[CognitionEvent]
    filters: dict[str, Any] = field(default_factory=dict)
    after_event_id: str | None = None
    generated_at: float = field(default_factory=time.time)

    @property
    def next_after_event_id(self) -> str | None:
        if self.events:
            return self.events[-1].event_id
        return self.after_event_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "events": [event.to_dict() for event in self.events],
            "filters": self.filters,
            "after_event_id": self.after_event_id,
            "next_after_event_id": self.next_after_event_id,
            "generated_at": self.generated_at,
        }


@dataclass(frozen=True)
class EventStreamSummary:
    """Aggregate view of a replayable event stream."""

    total_events: int
    event_counts: dict[str, int]
    session_counts: dict[str, int]
    filters: dict[str, Any] = field(default_factory=dict)
    first_timestamp: float | None = None
    last_timestamp: float | None = None
    last_event_id: str | None = None
    generated_at: float = field(default_factory=time.time)

    @classmethod
    def from_events(
        cls,
        events: Sequence[CognitionEvent],
        *,
        filters: dict[str, Any] | None = None,
    ) -> "EventStreamSummary":
        event_counts = Counter(event.type for event in events)
        session_counts = Counter(event.session_id or "runtime" for event in events)
        first = events[0] if events else None
        last = events[-1] if events else None
        return cls(
            total_events=len(events),
            event_counts=dict(sorted(event_counts.items())),
            session_counts=dict(sorted(session_counts.items())),
            filters=filters or {},
            first_timestamp=first.timestamp if first else None,
            last_timestamp=last.timestamp if last else None,
            last_event_id=last.event_id if last else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_events": self.total_events,
            "event_counts": self.event_counts,
            "session_counts": self.session_counts,
            "filters": self.filters,
            "first_timestamp": self.first_timestamp,
            "last_timestamp": self.last_timestamp,
            "last_event_id": self.last_event_id,
            "generated_at": self.generated_at,
        }


def stream_filters(
    *,
    session_id: str | None = None,
    event_types: str | Iterable[str] | None = None,
    since: float | None = None,
    until: float | None = None,
) -> dict[str, Any]:
    """Build a serializable filter dictionary for event streams."""

    filters: dict[str, Any] = {}
    if session_id is not None:
        filters["session_id"] = session_id
    if (types := normalize_event_types(event_types)) is not None:
        filters["event_types"] = types
    if since is not None:
        filters["since"] = since
    if until is not None:
        filters["until"] = until
    return filters


def filter_replay_events(
    events: Sequence[CognitionEvent],
    *,
    limit: int = 100,
    session_id: str | None = None,
    event_types: str | Iterable[str] | None = None,
    after_event_id: str | None = None,
    since: float | None = None,
    until: float | None = None,
) -> list[CognitionEvent]:
    """Filter an already ordered event sequence for replay."""

    start_index = 0
    if after_event_id is not None:
        for index, event in enumerate(events):
            if event.event_id == after_event_id:
                start_index = index + 1
                break

    candidates = list(events[start_index:])
    normalized_types = normalize_event_types(event_types)
    if session_id is not None:
        candidates = [event for event in candidates if event.session_id == session_id]
    if normalized_types is not None:
        allowed = set(normalized_types)
        candidates = [event for event in candidates if event.type in allowed]
    if since is not None:
        candidates = [event for event in candidates if event.timestamp >= since]
    if until is not None:
        candidates = [event for event in candidates if event.timestamp <= until]
    if limit > 0:
        candidates = candidates[:limit]
    return candidates


__all__ = [
    "EventReplay",
    "EventStreamSummary",
    "StreamCheckpoint",
    "filter_replay_events",
    "normalize_event_types",
    "stream_filters",
]
