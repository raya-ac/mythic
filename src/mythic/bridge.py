"""Bridges from Mythic runtime state into external memory systems."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

from mythic.cycles import CognitiveCycle, ReflectionRecord


@dataclass(frozen=True)
class BridgeMemory:
    """A memory payload ready to publish outside the runtime store."""

    content: str
    layer: str
    memory_type: str
    importance: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "layer": self.layer,
            "memory_type": self.memory_type,
            "importance": self.importance,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class BridgePublishResult:
    """Result from publishing runtime records into a memory bridge."""

    backend: str
    memory_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "ok": self.ok,
            "memory_ids": self.memory_ids,
            "errors": self.errors,
        }


class MemoryBridge(Protocol):
    """External bridge for publishing durable cognitive memory."""

    backend: str

    def publish_cycle(self, cycle: CognitiveCycle, snapshot: dict[str, Any] | None = None) -> BridgePublishResult: ...

    def publish_reflection(self, reflection: ReflectionRecord) -> BridgePublishResult: ...


class NullMemoryBridge:
    """Bridge used when no external memory publication is requested."""

    backend = "none"

    def publish_cycle(self, cycle: CognitiveCycle, snapshot: dict[str, Any] | None = None) -> BridgePublishResult:
        return BridgePublishResult(backend=self.backend)

    def publish_reflection(self, reflection: ReflectionRecord) -> BridgePublishResult:
        return BridgePublishResult(backend=self.backend)


class CycleMemoryFormatter:
    """Formats Mythic cycles and reflections for long-term memory systems."""

    def cycle_memory(self, cycle: CognitiveCycle, snapshot: dict[str, Any] | None = None) -> BridgeMemory:
        ready = []
        blocked = []
        suggested = []
        if snapshot:
            ready = [task["title"] for task in snapshot.get("planner", {}).get("ready", [])]
            blocked = [task["title"] for task in snapshot.get("planner", {}).get("blocked", [])]
            suggested = list(snapshot.get("suggested_next_actions", []))

        activation_ids = [activation.memory_id for activation in cycle.activations]
        lines = [
            f"Mythic cognitive cycle {cycle.id} for session {cycle.session_id}.",
            f"Goal: {cycle.activation_request.goal}",
            f"Status: {cycle.status}",
            f"Activated memories: {len(cycle.activations)}",
            f"Reflections recorded: {len(cycle.reflections)}",
        ]
        if ready:
            lines.append("Ready planner tasks: " + " | ".join(ready[:8]))
        if blocked:
            lines.append("Blocked planner tasks: " + " | ".join(blocked[:8]))
        if activation_ids:
            lines.append("Activated memory ids: " + " ".join(activation_ids[:12]))
        if suggested:
            lines.append("Suggested next actions: " + " | ".join(suggested[:8]))
        lines.append("Activation query:")
        lines.append(cycle.activation_request.to_query())

        return BridgeMemory(
            content="\n".join(lines),
            layer="episodic",
            memory_type="narrative",
            importance=0.78 if cycle.reflections else 0.68,
            metadata={
                "kind": "mythic_cycle",
                "cycle_id": cycle.id,
                "session_id": cycle.session_id,
                "activation_count": len(cycle.activations),
                "reflection_count": len(cycle.reflections),
            },
        )

    def reflection_memory(self, reflection: ReflectionRecord) -> BridgeMemory:
        content = "\n".join(
            [
                f"Mythic reflection {reflection.id} for session {reflection.session_id}.",
                f"Kind: {reflection.kind}",
                f"Severity: {reflection.severity}",
                f"Subject: {reflection.subject}",
                f"Detail: {reflection.detail}",
                f"Cycle: {reflection.cycle_id or 'none'}",
            ]
        )
        importance = 0.82 if reflection.severity == "error" else 0.74
        return BridgeMemory(
            content=content,
            layer="procedural",
            memory_type="procedure",
            importance=importance,
            metadata={
                "kind": "mythic_reflection",
                "reflection_id": reflection.id,
                "reflection_kind": reflection.kind,
                "session_id": reflection.session_id,
                "cycle_id": reflection.cycle_id,
                "severity": reflection.severity,
            },
        )


class EngramMemoryBridge:
    """Publishes Mythic runtime records into Engram's existing store."""

    backend = "engram"

    def __init__(
        self,
        config_path: str | None = None,
        *,
        formatter: CycleMemoryFormatter | None = None,
        embed: bool = False,
    ):
        from engram.config import Config
        from engram.store import Store

        self.config = Config.load(config_path)
        self.store = Store(self.config)
        self.store.init_db()
        self.formatter = formatter or CycleMemoryFormatter()
        self.embed = embed

    def publish_cycle(self, cycle: CognitiveCycle, snapshot: dict[str, Any] | None = None) -> BridgePublishResult:
        payloads = [self.formatter.cycle_memory(cycle, snapshot=snapshot)]
        payloads.extend(self.formatter.reflection_memory(reflection) for reflection in cycle.reflections)
        return self._publish_many(payloads)

    def publish_reflection(self, reflection: ReflectionRecord) -> BridgePublishResult:
        return self._publish_many([self.formatter.reflection_memory(reflection)])

    def _publish_many(self, payloads: list[BridgeMemory]) -> BridgePublishResult:
        memory_ids: list[str] = []
        errors: list[str] = []
        for payload in payloads:
            try:
                memory_ids.append(self._publish_one(payload))
            except Exception as exc:
                errors.append(str(exc))
        return BridgePublishResult(backend=self.backend, memory_ids=memory_ids, errors=errors)

    def _publish_one(self, payload: BridgeMemory) -> str:
        from engram.store import Memory

        embedding = None
        if self.embed:
            from engram.embeddings import embed_documents

            vectors = embed_documents([payload.content], self.config.embedding_model)
            if vectors:
                embedding = vectors[0]

        mem = Memory(
            id=str(uuid.uuid4()),
            content=payload.content,
            source_file="mythic-runtime",
            source_type="mythic",
            layer=payload.layer,
            memory_type=payload.memory_type,
            embedding=embedding,
            importance=payload.importance,
            metadata=payload.metadata,
        )
        self.store.save_memory(mem)
        return mem.id

