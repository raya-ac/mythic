"""Mythic runtime orchestration."""

from __future__ import annotations

from dataclasses import dataclass

from mythic.events import CognitionEvent, EventBus
from mythic.memory import MemoryActivation, MemoryAdapter, NullMemoryAdapter
from mythic.session import CognitiveSession
from mythic.store import JsonRuntimeStore


@dataclass
class RuntimeStep:
    """Result of a runtime operation."""

    session: CognitiveSession
    events: list[CognitionEvent]


class MythicRuntime:
    """Coordinator for persistent cognitive sessions."""

    def __init__(
        self,
        *,
        store: JsonRuntimeStore | None = None,
        memory_adapter: MemoryAdapter | None = None,
        event_bus: EventBus | None = None,
    ):
        self.store = store or JsonRuntimeStore()
        self.memory_adapter = memory_adapter or NullMemoryAdapter()
        self.event_bus = event_bus or EventBus()

    def init(self) -> None:
        self.store.init()
        self.event_bus.emit("runtime_initialized", {"store": str(self.store.root)})

    def start_session(self, goal: str) -> RuntimeStep:
        session = CognitiveSession(goal=goal)
        root_task = session.planner.add_task(goal, metadata={"kind": "root_goal"})
        self.store.save_session(session)
        event = self.event_bus.emit(
            "session_started",
            {"goal": goal, "root_task_id": root_task.id},
            session_id=session.id,
        )
        return RuntimeStep(session=session, events=[event])

    def resume_session(self, session_id: str) -> CognitiveSession:
        session = self.store.load_session(session_id)
        self.event_bus.emit(
            "session_resumed",
            {"goal": session.goal, "status": session.status},
            session_id=session.id,
        )
        return session

    def activate_memory(self, session: CognitiveSession, *, top_k: int = 5) -> RuntimeStep:
        activations = self.memory_adapter.activate(session.goal, top_k=top_k)
        session.activate_memories(activations)
        self.store.save_session(session)

        events = [
            self.event_bus.emit(
                "memory_activation",
                activation.to_dict(),
                session_id=session.id,
            )
            for activation in activations
        ]
        events.append(
            self.event_bus.emit(
                "memory_activation_complete",
                {"count": len(activations), "goal": session.goal},
                session_id=session.id,
            )
        )
        return RuntimeStep(session=session, events=events)

    def checkpoint(self, session: CognitiveSession, note: str) -> RuntimeStep:
        session.checkpoint(note)
        self.store.save_session(session)
        event = self.event_bus.emit(
            "session_checkpoint",
            {"note": note},
            session_id=session.id,
        )
        return RuntimeStep(session=session, events=[event])

    def list_sessions(self) -> list[CognitiveSession]:
        return self.store.list_sessions()


__all__ = ["MemoryActivation", "MythicRuntime", "RuntimeStep"]

