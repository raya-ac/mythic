"""Memory mesh graph primitives."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any


def mesh_node_id(kind: str, identifier: str) -> str:
    """Return a stable node id for a typed external object."""

    return f"{kind}:{identifier}"


def mesh_edge_id(source_id: str, kind: str, target_id: str) -> str:
    """Return a stable edge id for one directed relationship."""

    digest = hashlib.sha1(f"{source_id}\0{kind}\0{target_id}".encode("utf-8")).hexdigest()
    return digest[:24]


def clamp_weight(value: float) -> float:
    """Keep graph weights bounded for predictable traversal metadata."""

    return max(-1.0, min(1.0, value))


@dataclass(frozen=True)
class MemoryMeshNode:
    """A typed object in the local cognition graph."""

    kind: str
    label: str
    id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if self.id is None:
            object.__setattr__(self, "id", mesh_node_id(self.kind, self.label))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "label": self.label,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryMeshNode":
        return cls(
            id=data["id"],
            kind=data["kind"],
            label=data["label"],
            metadata=dict(data.get("metadata", {})),
            created_at=float(data.get("created_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
        )


@dataclass(frozen=True)
class MemoryMeshEdge:
    """A directed relationship between two memory mesh nodes."""

    source_id: str
    target_id: str
    kind: str
    confidence: float = 1.0
    planner_relevance: float = 0.0
    emotional_weight: float = 0.0
    activation_count: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    last_activated_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if self.id is None:
            object.__setattr__(self, "id", mesh_edge_id(self.source_id, self.kind, self.target_id))
        object.__setattr__(self, "confidence", clamp_weight(self.confidence))
        object.__setattr__(self, "planner_relevance", clamp_weight(self.planner_relevance))
        object.__setattr__(self, "emotional_weight", clamp_weight(self.emotional_weight))
        object.__setattr__(self, "activation_count", max(0, int(self.activation_count)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "kind": self.kind,
            "confidence": self.confidence,
            "planner_relevance": self.planner_relevance,
            "emotional_weight": self.emotional_weight,
            "activation_count": self.activation_count,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_activated_at": self.last_activated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryMeshEdge":
        return cls(
            id=data["id"],
            source_id=data["source_id"],
            target_id=data["target_id"],
            kind=data["kind"],
            confidence=float(data.get("confidence", 1.0)),
            planner_relevance=float(data.get("planner_relevance", 0.0)),
            emotional_weight=float(data.get("emotional_weight", 0.0)),
            activation_count=int(data.get("activation_count", 1)),
            metadata=dict(data.get("metadata", {})),
            created_at=float(data.get("created_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
            last_activated_at=float(data.get("last_activated_at", data.get("updated_at", time.time()))),
        )


@dataclass(frozen=True)
class MeshTraversal:
    """A bounded traversal result from one root node."""

    root_id: str
    depth: int
    nodes: list[MemoryMeshNode] = field(default_factory=list)
    edges: list[MemoryMeshEdge] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "root_id": self.root_id,
            "depth": self.depth,
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
        }


def merge_mesh_edge(existing: MemoryMeshEdge, incoming: MemoryMeshEdge) -> MemoryMeshEdge:
    """Merge repeated observations of the same relationship."""

    metadata = dict(existing.metadata)
    metadata.update(incoming.metadata)
    return MemoryMeshEdge(
        id=existing.id,
        source_id=existing.source_id,
        target_id=existing.target_id,
        kind=existing.kind,
        confidence=max(existing.confidence, incoming.confidence),
        planner_relevance=max(existing.planner_relevance, incoming.planner_relevance),
        emotional_weight=max(existing.emotional_weight, incoming.emotional_weight),
        activation_count=existing.activation_count + incoming.activation_count,
        metadata=metadata,
        created_at=existing.created_at,
        updated_at=incoming.updated_at,
        last_activated_at=incoming.last_activated_at,
    )


__all__ = [
    "MemoryMeshEdge",
    "MemoryMeshNode",
    "MeshTraversal",
    "merge_mesh_edge",
    "mesh_edge_id",
    "mesh_node_id",
]
