"""Cognitive cycle and reflection models."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from mythic.memory import MemoryActivation, MemoryActivationRequest


@dataclass(frozen=True)
class ReflectionRecord:
    """First-class record of runtime uncertainty, blockage, or failure."""

    session_id: str
    kind: str
    subject: str
    detail: str
    severity: str = "info"
    cycle_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "cycle_id": self.cycle_id,
            "kind": self.kind,
            "severity": self.severity,
            "subject": self.subject,
            "detail": self.detail,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReflectionRecord":
        return cls(
            id=data["id"],
            session_id=data["session_id"],
            cycle_id=data.get("cycle_id"),
            kind=data["kind"],
            severity=data.get("severity", "info"),
            subject=data["subject"],
            detail=data["detail"],
            metadata=dict(data.get("metadata", {})),
            created_at=float(data.get("created_at", time.time())),
        )


@dataclass(frozen=True)
class CognitiveCycle:
    """One persisted activation/planning step for a cognitive session."""

    session_id: str
    activation_request: MemoryActivationRequest
    activations: list[MemoryActivation] = field(default_factory=list)
    reflections: list[ReflectionRecord] = field(default_factory=list)
    status: str = "completed"
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "status": self.status,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "activation_request": self.activation_request.to_dict(),
            "activations": [activation.to_dict() for activation in self.activations],
            "reflections": [reflection.to_dict() for reflection in self.reflections],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CognitiveCycle":
        request_data = dict(data["activation_request"])
        request = MemoryActivationRequest(
            session_id=request_data["session_id"],
            cycle_id=request_data.get("cycle_id") or data["id"],
            goal=request_data["goal"],
            active_goals=list(request_data.get("active_goals", [])),
            ready_tasks=list(request_data.get("ready_tasks", [])),
            active_tasks=list(request_data.get("active_tasks", [])),
            blocked_tasks=list(request_data.get("blocked_tasks", [])),
            recent_reasoning=list(request_data.get("recent_reasoning", [])),
            previous_activation_ids=list(request_data.get("previous_activation_ids", [])),
        )
        return cls(
            id=data["id"],
            session_id=data["session_id"],
            status=data.get("status", "completed"),
            created_at=float(data.get("created_at", time.time())),
            completed_at=data.get("completed_at"),
            activation_request=request,
            activations=[
                MemoryActivation(
                    memory_id=item["memory_id"],
                    score=float(item.get("score", 0.0)),
                    planner_relevance=float(item.get("planner_relevance", 0.0)),
                    layer=item.get("layer"),
                    content_preview=item.get("content_preview"),
                    metadata=dict(item.get("metadata", {})),
                )
                for item in data.get("activations", [])
            ],
            reflections=[
                ReflectionRecord.from_dict(item)
                for item in data.get("reflections", [])
            ],
        )

