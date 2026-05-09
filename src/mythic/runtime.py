"""Mythic runtime orchestration."""

from __future__ import annotations

import time
from dataclasses import dataclass

from mythic.bridge import BridgePublishResult, MemoryBridge, NullMemoryBridge
from mythic.cycles import CognitiveCycle, ReflectionRecord
from mythic.events import CognitionEvent, EventBus
from mythic.memory import MemoryActivation, MemoryActivationRequest, MemoryAdapter, NullMemoryAdapter
from mythic.planner import TaskNode, TaskStatus
from mythic.plugins import PluginHost, PluginResult
from mythic.session import CognitiveSession
from mythic.store import RuntimeStore, SQLiteRuntimeStore


@dataclass
class RuntimeStep:
    """Result of a runtime operation."""

    session: CognitiveSession
    events: list[CognitionEvent]


@dataclass
class PluginRunStep:
    """Result of a supervised plugin execution."""

    result: PluginResult
    events: list[CognitionEvent]


@dataclass
class CycleStep:
    """Result of one cognitive runtime cycle."""

    session: CognitiveSession
    cycle: CognitiveCycle
    events: list[CognitionEvent]
    bridge_result: BridgePublishResult | None = None


class MythicRuntime:
    """Coordinator for persistent cognitive sessions."""

    def __init__(
        self,
        *,
        store: RuntimeStore | None = None,
        memory_adapter: MemoryAdapter | None = None,
        memory_bridge: MemoryBridge | None = None,
        event_bus: EventBus | None = None,
        plugin_host: PluginHost | None = None,
    ):
        self.store = store or SQLiteRuntimeStore()
        self.memory_adapter = memory_adapter or NullMemoryAdapter()
        self.memory_bridge = memory_bridge or NullMemoryBridge()
        self.event_bus = event_bus or EventBus()
        self.plugin_host = plugin_host or PluginHost()

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

    def _activation_request(
        self,
        session: CognitiveSession,
        *,
        cycle_id: str | None = None,
    ) -> MemoryActivationRequest:
        ready = [task.title for task in session.planner.ready_tasks()]
        active = [
            task.title
            for task in session.planner.tasks.values()
            if task.status == TaskStatus.ACTIVE
        ]
        blocked = [
            task.title
            for task in session.planner.tasks.values()
            if task.status == TaskStatus.BLOCKED
        ]
        prior_activation_ids = [
            activation.memory_id
            for activation in session.recent_memory_activations
        ]
        return MemoryActivationRequest(
            session_id=session.id,
            cycle_id=cycle_id,
            goal=session.goal,
            active_goals=list(session.active_goals),
            ready_tasks=ready,
            active_tasks=active,
            blocked_tasks=blocked,
            recent_reasoning=session.reasoning_history[-5:],
            previous_activation_ids=prior_activation_ids[-10:],
        )

    def activate_memory(self, session: CognitiveSession, *, top_k: int = 5) -> RuntimeStep:
        request = self._activation_request(session)
        activations = self.memory_adapter.activate(request, top_k=top_k)
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
                {
                    "count": len(activations),
                    "goal": session.goal,
                    "activation_request": request.to_dict(),
                },
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

    def run_cycle(
        self,
        session: CognitiveSession,
        *,
        top_k: int = 5,
        publish: bool = False,
    ) -> CycleStep:
        cycle = CognitiveCycle(
            session_id=session.id,
            activation_request=self._activation_request(session),
            status="running",
        )
        request = self._activation_request(session, cycle_id=cycle.id)
        started = self._emit(
            "cognitive_cycle_started",
            {
                "cycle_id": cycle.id,
                "activation_request": request.to_dict(),
            },
            session_id=session.id,
        )

        activations = self.memory_adapter.activate(request, top_k=top_k)
        session.activate_memories(activations)

        reflections = self._reflect_on_session(session, cycle_id=cycle.id)
        session.add_reasoning(
            f"[cycle] activated {len(activations)} memories; recorded {len(reflections)} reflections"
        )
        self.store.save_session(session)

        completed_cycle = CognitiveCycle(
            id=cycle.id,
            session_id=session.id,
            activation_request=request,
            activations=activations,
            reflections=reflections,
            status="completed",
            created_at=cycle.created_at,
            completed_at=time.time(),
        )
        self.store.save_cycle(completed_cycle)

        events = [started]
        events.extend(
            self._emit(
                "memory_activation",
                activation.to_dict(),
                session_id=session.id,
            )
            for activation in activations
        )
        for reflection in reflections:
            self.store.save_reflection(reflection)
            events.append(
                self._emit(
                    "reflection_recorded",
                    reflection.to_dict(),
                    session_id=session.id,
                )
            )
        events.append(
            self._emit(
                "cognitive_cycle_completed",
                {
                    "cycle_id": completed_cycle.id,
                    "activation_count": len(activations),
                    "reflection_count": len(reflections),
                    "status": completed_cycle.status,
                },
                session_id=session.id,
            )
        )

        bridge_result = None
        if publish:
            snapshot = self.session_snapshot(session)
            bridge_result = self.memory_bridge.publish_cycle(completed_cycle, snapshot=snapshot)
            events.append(
                self._emit(
                    "bridge_publish_completed",
                    {
                        "record_type": "cycle",
                        "cycle_id": completed_cycle.id,
                        "result": bridge_result.to_dict(),
                    },
                    session_id=session.id,
                )
            )

        return CycleStep(session=session, cycle=completed_cycle, events=events, bridge_result=bridge_result)

    def _reflect_on_session(self, session: CognitiveSession, *, cycle_id: str) -> list[ReflectionRecord]:
        reflections: list[ReflectionRecord] = []
        for task in session.planner.tasks.values():
            if task.status == TaskStatus.BLOCKED:
                reflections.append(
                    ReflectionRecord(
                        session_id=session.id,
                        cycle_id=cycle_id,
                        kind="blocked_task",
                        severity="warning",
                        subject=task.title,
                        detail="Planner task is blocked and needs new information, a decision, or an external change.",
                        metadata={"task": task.to_dict()},
                    )
                )
            elif task.status == TaskStatus.FAILED:
                reflections.append(
                    ReflectionRecord(
                        session_id=session.id,
                        cycle_id=cycle_id,
                        kind="failed_task",
                        severity="error",
                        subject=task.title,
                        detail="Planner task is marked failed and should be corrected before dependent work continues.",
                        metadata={"task": task.to_dict()},
                    )
                )
        return reflections

    def run_plugin(
        self,
        plugin_path: str,
        *,
        input_text: str | None = None,
        timeout_seconds: float | None = None,
        session_id: str | None = None,
    ) -> PluginRunStep:
        manifest = self.plugin_host.load_manifest(plugin_path)
        started = self._emit(
            "plugin_started",
            {
                "plugin": manifest.to_dict(),
                "input_bytes": len((input_text or "").encode("utf-8")),
            },
            session_id=session_id,
        )
        result = self.plugin_host.run(
            plugin_path,
            input_text=input_text,
            timeout_seconds=timeout_seconds,
        )
        completed = self._emit(
            "plugin_completed",
            {
                "plugin": result.plugin.to_dict(),
                "ok": result.ok,
                "returncode": result.returncode,
                "elapsed_ms": result.elapsed_ms,
                "timed_out": result.timed_out,
            },
            session_id=session_id,
        )
        events = [started, completed]
        if session_id is not None and not result.ok:
            reflection = ReflectionRecord(
                session_id=session_id,
                kind="plugin_failure",
                severity="error" if not result.timed_out else "warning",
                subject=result.plugin.name,
                detail=result.stderr.strip() or f"Plugin exited with return code {result.returncode}",
                metadata=result.to_dict(),
            )
            self.store.save_reflection(reflection)
            events.append(
                self._emit(
                    "reflection_recorded",
                    reflection.to_dict(),
                    session_id=session_id,
                )
            )
            bridge_result = self.memory_bridge.publish_reflection(reflection)
            if bridge_result.backend != "none":
                events.append(
                    self._emit(
                        "bridge_publish_completed",
                        {
                            "record_type": "reflection",
                            "reflection_id": reflection.id,
                            "result": bridge_result.to_dict(),
                        },
                        session_id=session_id,
                    )
                )
        return PluginRunStep(result=result, events=events)

    def discover_plugins(self, plugin_root: str) -> list[dict]:
        return [plugin.to_dict() for plugin in self.plugin_host.discover(plugin_root)]

    def run_capability(
        self,
        plugin_root: str,
        capability: str,
        *,
        input_text: str | None = None,
        timeout_seconds: float | None = None,
        session_id: str | None = None,
    ) -> PluginRunStep:
        plugin = self.plugin_host.find_by_capability(plugin_root, capability)
        if plugin is None:
            raise LookupError(f"no plugin found for capability: {capability}")
        selected = self._emit(
            "plugin_capability_selected",
            {
                "capability": capability,
                "plugin": plugin.manifest.to_dict(),
                "path": str(plugin.path),
            },
            session_id=session_id,
        )
        step = self.run_plugin(
            str(plugin.path),
            input_text=input_text,
            timeout_seconds=timeout_seconds,
            session_id=session_id,
        )
        return PluginRunStep(result=step.result, events=[selected, *step.events])

    def list_sessions(self) -> list[CognitiveSession]:
        return self.store.list_sessions()

    def list_events(
        self,
        *,
        limit: int = 50,
        session_id: str | None = None,
    ) -> list[CognitionEvent]:
        return self.store.list_events(limit=limit, session_id=session_id)

    def list_cycles(
        self,
        *,
        limit: int = 20,
        session_id: str | None = None,
    ) -> list[CognitiveCycle]:
        return self.store.list_cycles(limit=limit, session_id=session_id)

    def list_reflections(
        self,
        *,
        limit: int = 20,
        session_id: str | None = None,
    ) -> list[ReflectionRecord]:
        return self.store.list_reflections(limit=limit, session_id=session_id)

    def session_snapshot(self, session: CognitiveSession, *, limit: int = 10) -> dict:
        ready = [task.to_dict() for task in session.planner.ready_tasks()]
        active = [
            task.to_dict()
            for task in session.planner.tasks.values()
            if task.status == TaskStatus.ACTIVE
        ]
        blocked = [
            task.to_dict()
            for task in session.planner.tasks.values()
            if task.status == TaskStatus.BLOCKED
        ]
        failed = [
            task.to_dict()
            for task in session.planner.tasks.values()
            if task.status == TaskStatus.FAILED
        ]
        suggestions = [task["title"] for task in ready[:limit]]
        if blocked:
            suggestions.extend(f"unblock: {task['title']}" for task in blocked[:limit])
        if not suggestions and session.active_goals:
            suggestions.append(session.active_goals[0])

        return {
            "session": session.to_dict(),
            "planner": {
                "ready": ready,
                "active": active,
                "blocked": blocked,
                "failed": failed,
            },
            "recent_activations": [
                activation.to_dict()
                for activation in session.recent_memory_activations[-limit:]
            ],
            "recent_cycles": [
                cycle.to_dict()
                for cycle in self.list_cycles(session_id=session.id, limit=limit)
            ],
            "recent_reflections": [
                reflection.to_dict()
                for reflection in self.list_reflections(session_id=session.id, limit=limit)
            ],
            "recent_events": [
                event.to_dict()
                for event in self.list_events(session_id=session.id, limit=limit)
            ],
            "suggested_next_actions": suggestions[:limit],
        }

__all__ = ["CycleStep", "MemoryActivation", "MythicRuntime", "PluginRunStep", "RuntimeStep"]
