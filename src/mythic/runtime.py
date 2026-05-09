"""Mythic runtime orchestration."""

from __future__ import annotations

from dataclasses import dataclass

from mythic.events import CognitionEvent, EventBus
from mythic.memory import MemoryActivation, MemoryAdapter, NullMemoryAdapter
from mythic.planner import TaskNode, TaskStatus
from mythic.session import CognitiveSession
from mythic.store import RuntimeStore, SQLiteRuntimeStore


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
        store: RuntimeStore | None = None,
        memory_adapter: MemoryAdapter | None = None,
        event_bus: EventBus | None = None,
    ):
        self.store = store or SQLiteRuntimeStore()
        self.memory_adapter = memory_adapter or NullMemoryAdapter()
        self.event_bus = event_bus or EventBus()

    def init(self) -> None:
        self.store.init()
        self._emit("runtime_initialized", {"store": str(self.store.root)})

    def _emit(
        self,
        event_type: str,
        data: dict | None = None,
        *,
        session_id: str | None = None,
    ) -> CognitionEvent:
        event = self.event_bus.emit(event_type, data, session_id=session_id)
        self.store.save_event(event)
        return event

    def start_session(self, goal: str) -> RuntimeStep:
        session = CognitiveSession(goal=goal)
        root_task = session.planner.add_task(goal, metadata={"kind": "root_goal"})
        self.store.save_session(session)
        event = self._emit(
            "session_started",
            {"goal": goal, "root_task_id": root_task.id},
            session_id=session.id,
        )
        return RuntimeStep(session=session, events=[event])

    def resume_session(self, session_id: str) -> CognitiveSession:
        session = self.store.load_session(session_id)
        self._emit(
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
            self._emit(
                "memory_activation",
                activation.to_dict(),
                session_id=session.id,
            )
            for activation in activations
        ]
        events.append(
            self._emit(
                "memory_activation_complete",
                {"count": len(activations), "goal": session.goal},
                session_id=session.id,
            )
        )
        return RuntimeStep(session=session, events=events)

    def checkpoint(self, session: CognitiveSession, note: str) -> RuntimeStep:
        session.checkpoint(note)
        self.store.save_session(session)
        event = self._emit(
            "session_checkpoint",
            {"note": note},
            session_id=session.id,
        )
        return RuntimeStep(session=session, events=[event])

    def add_task(
        self,
        session: CognitiveSession,
        title: str,
        *,
        depends_on: list[str] | None = None,
    ) -> RuntimeStep:
        task = session.planner.add_task(title, depends_on=depends_on)
        self.store.save_session(session)
        event = self._emit(
            "planner_task_added",
            {"task": task.to_dict()},
            session_id=session.id,
        )
        return RuntimeStep(session=session, events=[event])

    def set_task_status(
        self,
        session: CognitiveSession,
        task_id: str,
        status: TaskStatus,
    ) -> RuntimeStep:
        task = session.planner.set_status(task_id, status)
        self.store.save_session(session)
        event = self._emit(
            "planner_task_status_changed",
            {"task_id": task_id, "status": task.status.value},
            session_id=session.id,
        )
        return RuntimeStep(session=session, events=[event])

    def ready_tasks(self, session: CognitiveSession) -> list[TaskNode]:
        return session.planner.ready_tasks()

    def list_sessions(self) -> list[CognitiveSession]:
        return self.store.list_sessions()

    def list_events(
        self,
        *,
        limit: int = 50,
        session_id: str | None = None,
    ) -> list[CognitionEvent]:
        return self.store.list_events(limit=limit, session_id=session_id)


__all__ = ["MemoryActivation", "MythicRuntime", "RuntimeStep"]
