"""Recoverable execution runtime models."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ExecutionStatus(str, Enum):
    """Lifecycle states for recoverable runtime executions."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


TERMINAL_STATUSES = {
    ExecutionStatus.COMPLETED,
    ExecutionStatus.FAILED,
    ExecutionStatus.CANCELED,
}


@dataclass(frozen=True)
class RuntimeExecution:
    """A durable unit of recoverable runtime work."""

    session_id: str
    kind: str
    goal: str
    status: ExecutionStatus = ExecutionStatus.PENDING
    payload: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None
    attempt: int = 1
    parent_id: str | None = None
    relation: str | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "kind": self.kind,
            "goal": self.goal,
            "status": self.status.value,
            "payload": self.payload,
            "result": self.result,
            "error": self.error,
            "attempt": self.attempt,
            "parent_id": self.parent_id,
            "relation": self.relation,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RuntimeExecution":
        return cls(
            id=data["id"],
            session_id=data["session_id"],
            kind=data["kind"],
            goal=data["goal"],
            status=ExecutionStatus(data.get("status", ExecutionStatus.PENDING)),
            payload=dict(data.get("payload", {})),
            result=data.get("result"),
            error=data.get("error"),
            attempt=int(data.get("attempt", 1)),
            parent_id=data.get("parent_id"),
            relation=data.get("relation"),
            created_at=float(data.get("created_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
            started_at=data.get("started_at"),
            completed_at=data.get("completed_at"),
        )


@dataclass(frozen=True)
class ExecutionCheckpoint:
    """A restart point for a runtime execution."""

    execution_id: str
    note: str
    payload: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "execution_id": self.execution_id,
            "note": self.note,
            "payload": self.payload,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExecutionCheckpoint":
        return cls(
            id=data["id"],
            execution_id=data["execution_id"],
            note=data["note"],
            payload=dict(data.get("payload", {})),
            created_at=float(data.get("created_at", time.time())),
        )


def transition_execution(
    execution: RuntimeExecution,
    status: ExecutionStatus | str,
    *,
    payload: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
    error: str | None = None,
    now: float | None = None,
) -> RuntimeExecution:
    """Return an execution with an updated lifecycle state."""

    parsed_status = ExecutionStatus(status)
    timestamp = time.time() if now is None else now
    started_at = execution.started_at
    completed_at = execution.completed_at
    if parsed_status == ExecutionStatus.RUNNING and started_at is None:
        started_at = timestamp
    if parsed_status in TERMINAL_STATUSES:
        completed_at = timestamp
    elif parsed_status in {ExecutionStatus.PENDING, ExecutionStatus.RUNNING, ExecutionStatus.PAUSED}:
        completed_at = None

    return RuntimeExecution(
        id=execution.id,
        session_id=execution.session_id,
        kind=execution.kind,
        goal=execution.goal,
        status=parsed_status,
        payload=payload if payload is not None else dict(execution.payload),
        result=result if result is not None else execution.result,
        error=error,
        attempt=execution.attempt,
        parent_id=execution.parent_id,
        relation=execution.relation,
        created_at=execution.created_at,
        updated_at=timestamp,
        started_at=started_at,
        completed_at=completed_at,
    )


def retry_execution(
    execution: RuntimeExecution,
    *,
    payload: dict[str, Any] | None = None,
    now: float | None = None,
) -> RuntimeExecution:
    """Create a new running execution retry."""

    timestamp = time.time() if now is None else now
    return RuntimeExecution(
        session_id=execution.session_id,
        kind=execution.kind,
        goal=execution.goal,
        status=ExecutionStatus.RUNNING,
        payload=payload if payload is not None else dict(execution.payload),
        attempt=execution.attempt + 1,
        parent_id=execution.id,
        relation="retry",
        created_at=timestamp,
        updated_at=timestamp,
        started_at=timestamp,
    )


def branch_execution(
    execution: RuntimeExecution,
    *,
    goal: str | None = None,
    payload: dict[str, Any] | None = None,
    now: float | None = None,
) -> RuntimeExecution:
    """Create a pending branch from an execution."""

    timestamp = time.time() if now is None else now
    return RuntimeExecution(
        session_id=execution.session_id,
        kind=execution.kind,
        goal=goal or execution.goal,
        status=ExecutionStatus.PENDING,
        payload=payload if payload is not None else dict(execution.payload),
        attempt=1,
        parent_id=execution.id,
        relation="branch",
        created_at=timestamp,
        updated_at=timestamp,
    )


__all__ = [
    "ExecutionCheckpoint",
    "ExecutionStatus",
    "RuntimeExecution",
    "TERMINAL_STATUSES",
    "branch_execution",
    "retry_execution",
    "transition_execution",
]
