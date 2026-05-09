"""Cognitive session model."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from mythic.memory import MemoryActivation
from mythic.planner import PlannerState


@dataclass
class CognitiveSession:
    """Long-lived runtime state for a cognitive workflow."""

    goal: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: str = "active"
    active_goals: list[str] = field(default_factory=list)
    reasoning_history: list[str] = field(default_factory=list)
    recent_memory_activations: list[MemoryActivation] = field(default_factory=list)
    tool_context: dict[str, Any] = field(default_factory=dict)
    planner: PlannerState = field(default_factory=PlannerState)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not self.active_goals:
            self.active_goals.append(self.goal)

    def add_reasoning(self, entry: str) -> None:
        self.reasoning_history.append(entry)
        self.updated_at = time.time()

    def activate_memories(self, activations: list[MemoryActivation]) -> None:
        self.recent_memory_activations = activations
        self.updated_at = time.time()

    def checkpoint(self, note: str) -> None:
        self.reasoning_history.append(f"[checkpoint] {note}")
        self.updated_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "goal": self.goal,
            "status": self.status,
            "active_goals": self.active_goals,
            "reasoning_history": self.reasoning_history,
            "recent_memory_activations": [
                activation.to_dict()
                for activation in self.recent_memory_activations
            ],
            "tool_context": self.tool_context,
            "planner": self.planner.to_dict(),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CognitiveSession":
        session = cls(
            id=data["id"],
            goal=data["goal"],
            status=data.get("status", "active"),
            active_goals=list(data.get("active_goals", [])),
            reasoning_history=list(data.get("reasoning_history", [])),
            recent_memory_activations=[
                MemoryActivation(
                    memory_id=item["memory_id"],
                    score=float(item.get("score", 0.0)),
                    planner_relevance=float(item.get("planner_relevance", 0.0)),
                    layer=item.get("layer"),
                    content_preview=item.get("content_preview"),
                    metadata=dict(item.get("metadata", {})),
                )
                for item in data.get("recent_memory_activations", [])
            ],
            tool_context=dict(data.get("tool_context", {})),
            planner=PlannerState.from_dict(data.get("planner")),
            created_at=float(data.get("created_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
        )
        return session

