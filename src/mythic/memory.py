"""Memory activation interfaces."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class MemoryActivationRequest:
    """Planner-aware context used to activate memory."""

    session_id: str
    goal: str
    active_goals: list[str] = field(default_factory=list)
    ready_tasks: list[str] = field(default_factory=list)
    active_tasks: list[str] = field(default_factory=list)
    blocked_tasks: list[str] = field(default_factory=list)
    recent_reasoning: list[str] = field(default_factory=list)
    previous_activation_ids: list[str] = field(default_factory=list)
    cycle_id: str | None = None

    def to_query(self) -> str:
        parts = [f"goal: {self.goal}"]
        if self.active_goals:
            parts.append("active goals: " + " | ".join(self.active_goals))
        if self.ready_tasks:
            parts.append("ready tasks: " + " | ".join(self.ready_tasks))
        if self.active_tasks:
            parts.append("active tasks: " + " | ".join(self.active_tasks))
        if self.blocked_tasks:
            parts.append("blocked tasks: " + " | ".join(self.blocked_tasks))
        if self.recent_reasoning:
            parts.append("recent reasoning: " + " | ".join(self.recent_reasoning))
        if self.previous_activation_ids:
            parts.append("prior activations: " + " ".join(self.previous_activation_ids))
        return "\n".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "cycle_id": self.cycle_id,
            "goal": self.goal,
            "active_goals": self.active_goals,
            "ready_tasks": self.ready_tasks,
            "active_tasks": self.active_tasks,
            "blocked_tasks": self.blocked_tasks,
            "recent_reasoning": self.recent_reasoning,
            "previous_activation_ids": self.previous_activation_ids,
            "query": self.to_query(),
        }


@dataclass(frozen=True)
class MemoryActivation:
    """A memory selected for active use by the runtime."""

    memory_id: str
    score: float
    planner_relevance: float
    layer: str | None = None
    content_preview: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "score": self.score,
            "planner_relevance": self.planner_relevance,
            "layer": self.layer,
            "content_preview": self.content_preview,
            "metadata": self.metadata,
        }


class MemoryAdapter(Protocol):
    """Runtime-facing memory activation adapter."""

    def activate(self, request: MemoryActivationRequest, *, top_k: int = 5) -> list[MemoryActivation]:
        """Return memories relevant to a runtime activation request."""


class NullMemoryAdapter:
    """Adapter used when no memory system is attached yet."""

    def activate(self, request: MemoryActivationRequest, *, top_k: int = 5) -> list[MemoryActivation]:
        return []


class EngramMemoryAdapter:
    """Lazy adapter around Engram's existing retrieval stack."""

    def __init__(self, config_path: str | None = None):
        from engram.config import Config
        from engram.store import Store

        self.config = Config.load(config_path)
        self.store = Store(self.config)
        self.store.init_db()
        self.store.init_ann_index(background=True)

    def activate(self, request: MemoryActivationRequest, *, top_k: int = 5) -> list[MemoryActivation]:
        from engram.retrieval import search

        query = request.to_query()
        results = search(
            query,
            self.store,
            self.config,
            top_k=top_k,
            rerank=False,
        )
        activations: list[MemoryActivation] = []
        for result in results:
            memory = result.memory
            activations.append(
                MemoryActivation(
                    memory_id=memory.id,
                    score=float(result.score),
                    planner_relevance=float(result.score),
                    layer=memory.layer,
                    content_preview=memory.content[:240],
                    metadata={
                        "activation_request": request.to_dict(),
                        "importance": memory.importance,
                        "memory_type": memory.memory_type,
                        "source_type": memory.source_type,
                    },
                )
            )
        return activations
