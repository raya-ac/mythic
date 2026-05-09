"""Memory activation interfaces."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


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

    def activate(self, goal: str, *, top_k: int = 5) -> list[MemoryActivation]:
        """Return memories relevant to a runtime goal."""


class NullMemoryAdapter:
    """Adapter used when no memory system is attached yet."""

    def activate(self, goal: str, *, top_k: int = 5) -> list[MemoryActivation]:
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

    def activate(self, goal: str, *, top_k: int = 5) -> list[MemoryActivation]:
        from engram.retrieval import search

        results = search(
            goal,
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
                        "importance": memory.importance,
                        "memory_type": memory.memory_type,
                        "source_type": memory.source_type,
                    },
                )
            )
        return activations

