"""Mythic runtime orchestration."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from mythic.bridge import BridgePublishResult, MemoryBridge, NullMemoryBridge
from mythic.cycles import CognitiveCycle, ReflectionRecord
from mythic.drift import DriftAnalyzer, DriftReport
from mythic.events import CognitionEvent, EventBus
from mythic.execution import (
    ExecutionCheckpoint,
    ExecutionStatus,
    RuntimeExecution,
    branch_execution as make_branch_execution,
    retry_execution as make_retry_execution,
    transition_execution,
)
from mythic.memory import MemoryActivation, MemoryActivationRequest, MemoryAdapter, NullMemoryAdapter
from mythic.mesh import MemoryMeshEdge, MemoryMeshNode, MeshTraversal, mesh_node_id
from mythic.planner import TaskNode, TaskStatus
from mythic.plugins import PluginHost, PluginResult
from mythic.reinforcement import ActivationFeedback, ActivationOutcome, ReinforcementState, apply_feedback, decay_state
from mythic.session import CognitiveSession
from mythic.store import RuntimeStore, SQLiteRuntimeStore
from mythic.streams import (
    EventReplay,
    EventStreamSummary,
    StreamCheckpoint,
    normalize_event_types,
    stream_filters,
)


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


@dataclass
class FeedbackStep:
    """Result of recording feedback for one activated memory."""

    feedback: ActivationFeedback
    state: ReinforcementState
    event: CognitionEvent


@dataclass
class DecayStep:
    """Result of decaying all reinforcement states."""

    states: list[ReinforcementState]
    event: CognitionEvent


@dataclass
class MeshLinkStep:
    """Result of recording a mesh relationship."""

    source: MemoryMeshNode
    target: MemoryMeshNode
    edge: MemoryMeshEdge


@dataclass
class DriftStep:
    """Result of one drift inspection."""

    report: DriftReport
    event: CognitionEvent


@dataclass
class ExecutionStep:
    """Result of changing an execution record."""

    execution: RuntimeExecution
    events: list[CognitionEvent]


@dataclass
class ExecutionCheckpointStep:
    """Result of checkpointing an execution."""

    execution: RuntimeExecution
    checkpoint: ExecutionCheckpoint
    events: list[CognitionEvent]


@dataclass
class StreamCheckpointStep:
    """Result of checkpointing an event stream."""

    checkpoint: StreamCheckpoint
    replay: EventReplay
    event: CognitionEvent


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
        drift_analyzer: DriftAnalyzer | None = None,
    ):
        self.store = store or SQLiteRuntimeStore()
        self.memory_adapter = memory_adapter or NullMemoryAdapter()
        self.memory_bridge = memory_bridge or NullMemoryBridge()
        self.event_bus = event_bus or EventBus()
        self.plugin_host = plugin_host or PluginHost()
        self.drift_analyzer = drift_analyzer or DriftAnalyzer()

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

    def _mesh_node(
        self,
        kind: str,
        identifier: str,
        *,
        label: str | None = None,
        metadata: dict | None = None,
    ) -> MemoryMeshNode:
        node = MemoryMeshNode(
            id=mesh_node_id(kind, identifier),
            kind=kind,
            label=label or identifier,
            metadata=metadata or {},
        )
        self.store.save_mesh_node(node)
        return node

    def _mesh_edge(
        self,
        source_id: str,
        target_id: str,
        kind: str,
        *,
        confidence: float = 1.0,
        planner_relevance: float = 0.0,
        emotional_weight: float = 0.0,
        metadata: dict | None = None,
    ) -> MemoryMeshEdge:
        edge = MemoryMeshEdge(
            source_id=source_id,
            target_id=target_id,
            kind=kind,
            confidence=confidence,
            planner_relevance=planner_relevance,
            emotional_weight=emotional_weight,
            metadata=metadata or {},
        )
        self.store.save_mesh_edge(edge)
        saved = self.store.load_mesh_edge(edge.id)
        return saved or edge

    def _record_session_mesh(self, session: CognitiveSession) -> None:
        session_node = self._mesh_node(
            "session",
            session.id,
            label=session.goal,
            metadata={"status": session.status},
        )
        for goal in session.active_goals:
            goal_node = self._mesh_node("goal", goal, label=goal)
            self._mesh_edge(session_node.id, goal_node.id, "pursues", metadata={"session_id": session.id})
        for task in session.planner.tasks.values():
            task_node = self._mesh_node(
                "task",
                task.id,
                label=task.title,
                metadata=task.to_dict(),
            )
            self._mesh_edge(session_node.id, task_node.id, "has_task", metadata={"status": task.status.value})
            for dependency_id in task.depends_on:
                dependency_node = self._mesh_node("task", dependency_id, label=dependency_id)
                self._mesh_edge(task_node.id, dependency_node.id, "depends_on")

    def _record_cycle_mesh(
        self,
        session: CognitiveSession,
        cycle: CognitiveCycle,
    ) -> None:
        session_node = self._mesh_node("session", session.id, label=session.goal)
        cycle_node = self._mesh_node(
            "cycle",
            cycle.id,
            label=f"cycle {cycle.id}",
            metadata={"status": cycle.status, "created_at": cycle.created_at},
        )
        self._mesh_edge(session_node.id, cycle_node.id, "ran_cycle")
        for activation in cycle.activations:
            memory_node = self._mesh_node(
                "memory",
                activation.memory_id,
                label=activation.content_preview or activation.memory_id,
                metadata={
                    "layer": activation.layer,
                    "score": activation.score,
                    "planner_relevance": activation.planner_relevance,
                },
            )
            self._mesh_edge(
                cycle_node.id,
                memory_node.id,
                "activated",
                confidence=activation.score,
                planner_relevance=activation.planner_relevance,
                metadata={"activation": activation.to_dict()},
            )
        for reflection in cycle.reflections:
            reflection_node = self._mesh_node(
                "reflection",
                reflection.id,
                label=reflection.subject,
                metadata=reflection.to_dict(),
            )
            self._mesh_edge(
                cycle_node.id,
                reflection_node.id,
                "produced_reflection",
                metadata={"kind": reflection.kind, "severity": reflection.severity},
            )

    def _record_execution_mesh(self, execution: RuntimeExecution) -> None:
        session_node = self._mesh_node("session", execution.session_id, label=execution.session_id)
        execution_node = self._mesh_node(
            "execution",
            execution.id,
            label=execution.goal,
            metadata=execution.to_dict(),
        )
        self._mesh_edge(
            session_node.id,
            execution_node.id,
            "has_execution",
            metadata={"kind": execution.kind, "status": execution.status.value},
        )
        if execution.parent_id is not None:
            parent_node = self._mesh_node("execution", execution.parent_id, label=execution.parent_id)
            self._mesh_edge(
                parent_node.id,
                execution_node.id,
                execution.relation or "continued_as",
                metadata={"attempt": execution.attempt},
            )

    def start_session(self, goal: str) -> RuntimeStep:
        session = CognitiveSession(goal=goal)
        root_task = session.planner.add_task(goal, metadata={"kind": "root_goal"})
        self.store.save_session(session)
        self._record_session_mesh(session)
        event = self._emit(
            "session_started",
            {"goal": goal, "root_task_id": root_task.id},
            session_id=session.id,
        )
        return RuntimeStep(session=session, events=[event])

    def resume_session(self, session_id: str) -> CognitiveSession:
        session = self.store.load_session(session_id)
        self._record_session_mesh(session)
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

    def _apply_reinforcement(self, activations: list[MemoryActivation]) -> list[MemoryActivation]:
        reinforced: list[MemoryActivation] = []
        for activation in activations:
            state = self.store.load_reinforcement(activation.memory_id)
            if state is None:
                reinforced.append(activation)
                continue

            adjusted_relevance = max(0.0, min(1.0, activation.planner_relevance + state.score))
            metadata = dict(activation.metadata)
            metadata["reinforcement"] = state.to_dict()
            metadata["base_planner_relevance"] = activation.planner_relevance
            metadata["reinforced_planner_relevance"] = adjusted_relevance
            reinforced.append(
                MemoryActivation(
                    memory_id=activation.memory_id,
                    score=activation.score,
                    planner_relevance=adjusted_relevance,
                    layer=activation.layer,
                    content_preview=activation.content_preview,
                    metadata=metadata,
                )
            )
        return reinforced

    def activate_memory(self, session: CognitiveSession, *, top_k: int = 5) -> RuntimeStep:
        request = self._activation_request(session)
        activations = self._apply_reinforcement(
            self.memory_adapter.activate(request, top_k=top_k)
        )
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
        self._record_session_mesh(session)
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
        self._record_session_mesh(session)
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

        activations = self._apply_reinforcement(
            self.memory_adapter.activate(request, top_k=top_k)
        )
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
        self._record_cycle_mesh(session, completed_cycle)

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

    def record_feedback(
        self,
        *,
        session_id: str,
        memory_id: str,
        outcome: ActivationOutcome | str,
        cycle_id: str | None = None,
        note: str | None = None,
        source: str = "human",
        signal: float | None = None,
        metadata: dict | None = None,
    ) -> FeedbackStep:
        feedback = ActivationFeedback.create(
            session_id=session_id,
            memory_id=memory_id,
            cycle_id=cycle_id,
            outcome=outcome,
            note=note,
            source=source,
            signal=signal,
            metadata=metadata,
        )
        state = apply_feedback(self.store.load_reinforcement(memory_id), feedback)
        self.store.save_feedback(feedback)
        self.store.save_reinforcement(state)
        session_node = self._mesh_node("session", session_id, label=session_id)
        memory_node = self._mesh_node("memory", memory_id, label=memory_id)
        self._mesh_edge(
            session_node.id,
            memory_node.id,
            "reinforced",
            planner_relevance=state.score,
            metadata={
                "outcome": feedback.outcome.value,
                "feedback_id": feedback.id,
                "note": feedback.note,
            },
        )
        event = self._emit(
            "memory_reinforced",
            {
                "feedback": feedback.to_dict(),
                "reinforcement": state.to_dict(),
            },
            session_id=session_id,
        )
        return FeedbackStep(feedback=feedback, state=state, event=event)

    def decay_reinforcements(self, *, rate: float = 0.05) -> DecayStep:
        bounded_rate = max(0.0, min(1.0, rate))
        states = [
            decay_state(state, rate=bounded_rate)
            for state in self.store.list_reinforcements(limit=0)
        ]
        for state in states:
            self.store.save_reinforcement(state)
        event = self._emit(
            "reinforcement_decay_completed",
            {"rate": bounded_rate, "count": len(states)},
        )
        return DecayStep(states=states, event=event)

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
        if session_id is not None:
            session_node = self._mesh_node("session", session_id, label=session_id)
            plugin_node = self._mesh_node(
                "plugin",
                result.plugin.name,
                label=result.plugin.name,
                metadata=result.plugin.to_dict(),
            )
            self._mesh_edge(
                session_node.id,
                plugin_node.id,
                "ran_plugin",
                confidence=1.0 if result.ok else 0.5,
                metadata={"ok": result.ok, "elapsed_ms": result.elapsed_ms},
            )
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

    def link_mesh(
        self,
        *,
        source_kind: str,
        source_identifier: str,
        target_kind: str,
        target_identifier: str,
        kind: str,
        source_label: str | None = None,
        target_label: str | None = None,
        confidence: float = 1.0,
        planner_relevance: float = 0.0,
        emotional_weight: float = 0.0,
        metadata: dict | None = None,
    ) -> MeshLinkStep:
        source = self._mesh_node(
            source_kind,
            source_identifier,
            label=source_label,
        )
        target = self._mesh_node(
            target_kind,
            target_identifier,
            label=target_label,
        )
        edge = self._mesh_edge(
            source.id,
            target.id,
            kind,
            confidence=confidence,
            planner_relevance=planner_relevance,
            emotional_weight=emotional_weight,
            metadata=metadata,
        )
        return MeshLinkStep(source=source, target=target, edge=edge)

    def list_mesh_nodes(
        self,
        *,
        limit: int = 50,
        kind: str | None = None,
    ) -> list[MemoryMeshNode]:
        return self.store.list_mesh_nodes(limit=limit, kind=kind)

    def list_mesh_edges(
        self,
        *,
        limit: int = 50,
        source_id: str | None = None,
        target_id: str | None = None,
        kind: str | None = None,
    ) -> list[MemoryMeshEdge]:
        return self.store.list_mesh_edges(
            limit=limit,
            source_id=source_id,
            target_id=target_id,
            kind=kind,
        )

    def traverse_mesh(
        self,
        identifier: str,
        *,
        kind: str | None = None,
        depth: int = 2,
        limit: int = 50,
    ) -> MeshTraversal:
        root_id = mesh_node_id(kind, identifier) if kind is not None else identifier
        root = self.store.load_mesh_node(root_id)
        if root is None:
            return MeshTraversal(root_id=root_id, depth=depth)

        max_depth = max(0, depth)
        max_items = max(0, limit)
        all_edges = self.store.list_mesh_edges(limit=0)
        edge_by_node: dict[str, list[MemoryMeshEdge]] = {}
        for edge in all_edges:
            edge_by_node.setdefault(edge.source_id, []).append(edge)
            edge_by_node.setdefault(edge.target_id, []).append(edge)

        nodes: dict[str, MemoryMeshNode] = {root.id: root}
        edges: dict[str, MemoryMeshEdge] = {}
        frontier: list[tuple[str, int]] = [(root.id, 0)]
        visited: set[str] = set()

        while frontier and (max_items == 0 or len(nodes) < max_items):
            node_id, current_depth = frontier.pop(0)
            if node_id in visited or current_depth >= max_depth:
                visited.add(node_id)
                continue
            visited.add(node_id)
            for edge in edge_by_node.get(node_id, []):
                edges[edge.id] = edge
                other_id = edge.target_id if edge.source_id == node_id else edge.source_id
                if other_id not in nodes:
                    other = self.store.load_mesh_node(other_id)
                    if other is not None:
                        nodes[other_id] = other
                if other_id not in visited:
                    frontier.append((other_id, current_depth + 1))
                if max_items > 0 and len(nodes) >= max_items:
                    break

        ordered_nodes = sorted(nodes.values(), key=lambda node: node.updated_at, reverse=True)
        ordered_edges = sorted(edges.values(), key=lambda edge: edge.updated_at, reverse=True)
        if max_items > 0:
            ordered_nodes = ordered_nodes[:max_items]
            ordered_edges = ordered_edges[:max_items]
        return MeshTraversal(root_id=root_id, depth=max_depth, nodes=ordered_nodes, edges=ordered_edges)

    def inspect_drift(
        self,
        *,
        session_id: str | None = None,
        stale_after_seconds: float = 7 * 24 * 60 * 60,
        persist: bool = True,
    ) -> DriftStep:
        report = self.drift_analyzer.analyze(
            self.store,
            session_id=session_id,
            stale_after_seconds=stale_after_seconds,
        )
        if persist:
            self.store.save_drift_report(report)
        event = self._emit(
            "drift_inspection_completed",
            {
                "report_id": report.id,
                "scope": report.scope,
                "score": report.score,
                "issue_count": len(report.issues),
                "persisted": persist,
            },
            session_id=session_id,
        )
        return DriftStep(report=report, event=event)

    def list_drift_reports(
        self,
        *,
        limit: int = 20,
        scope: str | None = None,
    ) -> list[DriftReport]:
        return self.store.list_drift_reports(limit=limit, scope=scope)

    def start_execution(
        self,
        *,
        session_id: str,
        kind: str,
        goal: str,
        payload: dict | None = None,
    ) -> ExecutionStep:
        timestamp = time.time()
        execution = RuntimeExecution(
            session_id=session_id,
            kind=kind,
            goal=goal,
            status=ExecutionStatus.RUNNING,
            payload=payload or {},
            created_at=timestamp,
            updated_at=timestamp,
            started_at=timestamp,
        )
        self.store.save_execution(execution)
        self._record_execution_mesh(execution)
        event = self._emit(
            "execution_started",
            {"execution": execution.to_dict()},
            session_id=session_id,
        )
        return ExecutionStep(execution=execution, events=[event])

    def set_execution_status(
        self,
        execution_id: str,
        status: ExecutionStatus | str,
        *,
        payload: dict | None = None,
        result: dict | None = None,
        error: str | None = None,
    ) -> ExecutionStep:
        previous = self.store.load_execution(execution_id)
        execution = transition_execution(
            previous,
            status,
            payload=payload,
            result=result,
            error=error,
        )
        self.store.save_execution(execution)
        self._record_execution_mesh(execution)
        event = self._emit(
            "execution_status_changed",
            {
                "execution_id": execution.id,
                "previous_status": previous.status.value,
                "status": execution.status.value,
                "execution": execution.to_dict(),
            },
            session_id=execution.session_id,
        )
        return ExecutionStep(execution=execution, events=[event])

    def checkpoint_execution(
        self,
        execution_id: str,
        note: str,
        *,
        payload: dict | None = None,
    ) -> ExecutionCheckpointStep:
        execution = self.store.load_execution(execution_id)
        checkpoint = ExecutionCheckpoint(
            execution_id=execution.id,
            note=note,
            payload=payload or {},
        )
        self.store.save_execution_checkpoint(checkpoint)
        checkpoint_node = self._mesh_node(
            "execution_checkpoint",
            checkpoint.id,
            label=checkpoint.note,
            metadata=checkpoint.to_dict(),
        )
        execution_node = self._mesh_node("execution", execution.id, label=execution.goal)
        self._mesh_edge(
            execution_node.id,
            checkpoint_node.id,
            "checkpointed",
            metadata={"note": checkpoint.note},
        )
        event = self._emit(
            "execution_checkpointed",
            {
                "execution_id": execution.id,
                "checkpoint": checkpoint.to_dict(),
            },
            session_id=execution.session_id,
        )
        return ExecutionCheckpointStep(execution=execution, checkpoint=checkpoint, events=[event])

    def retry_execution(
        self,
        execution_id: str,
        *,
        payload: dict | None = None,
    ) -> ExecutionStep:
        previous = self.store.load_execution(execution_id)
        execution = make_retry_execution(previous, payload=payload)
        self.store.save_execution(execution)
        self._record_execution_mesh(execution)
        event = self._emit(
            "execution_retried",
            {
                "previous_execution_id": previous.id,
                "execution": execution.to_dict(),
            },
            session_id=execution.session_id,
        )
        return ExecutionStep(execution=execution, events=[event])

    def branch_execution(
        self,
        execution_id: str,
        *,
        goal: str | None = None,
        payload: dict | None = None,
    ) -> ExecutionStep:
        previous = self.store.load_execution(execution_id)
        execution = make_branch_execution(previous, goal=goal, payload=payload)
        self.store.save_execution(execution)
        self._record_execution_mesh(execution)
        event = self._emit(
            "execution_branched",
            {
                "previous_execution_id": previous.id,
                "execution": execution.to_dict(),
            },
            session_id=execution.session_id,
        )
        return ExecutionStep(execution=execution, events=[event])

    def list_executions(
        self,
        *,
        limit: int = 50,
        session_id: str | None = None,
        status: ExecutionStatus | str | None = None,
    ) -> list[RuntimeExecution]:
        return self.store.list_executions(limit=limit, session_id=session_id, status=status)

    def list_execution_checkpoints(
        self,
        execution_id: str,
        *,
        limit: int = 20,
    ) -> list[ExecutionCheckpoint]:
        return self.store.list_execution_checkpoints(execution_id=execution_id, limit=limit)

    def list_sessions(self) -> list[CognitiveSession]:
        return self.store.list_sessions()

    def list_events(
        self,
        *,
        limit: int = 50,
        session_id: str | None = None,
    ) -> list[CognitionEvent]:
        return self.store.list_events(limit=limit, session_id=session_id)

    def subscribe_events(
        self,
        callback: Callable[[CognitionEvent], None],
        *,
        session_id: str | None = None,
        event_types: list[str] | str | None = None,
    ) -> Callable[[], None]:
        normalized_types = normalize_event_types(event_types)
        allowed_types = set(normalized_types) if normalized_types is not None else None

        def filtered_callback(event: CognitionEvent) -> None:
            if session_id is not None and event.session_id != session_id:
                return
            if allowed_types is not None and event.type not in allowed_types:
                return
            callback(event)

        return self.event_bus.subscribe(filtered_callback)

    def replay_events(
        self,
        *,
        limit: int = 100,
        session_id: str | None = None,
        event_types: list[str] | str | None = None,
        after_event_id: str | None = None,
        since: float | None = None,
        until: float | None = None,
    ) -> EventReplay:
        filters = stream_filters(
            session_id=session_id,
            event_types=event_types,
            since=since,
            until=until,
        )
        return EventReplay(
            events=self.store.replay_events(
                limit=limit,
                session_id=session_id,
                event_types=event_types,
                after_event_id=after_event_id,
                since=since,
                until=until,
            ),
            filters=filters,
            after_event_id=after_event_id,
        )

    def event_summary(
        self,
        *,
        limit: int = 0,
        session_id: str | None = None,
        event_types: list[str] | str | None = None,
        after_event_id: str | None = None,
        since: float | None = None,
        until: float | None = None,
    ) -> EventStreamSummary:
        replay = self.replay_events(
            limit=limit,
            session_id=session_id,
            event_types=event_types,
            after_event_id=after_event_id,
            since=since,
            until=until,
        )
        return EventStreamSummary.from_events(replay.events, filters=replay.filters)

    def checkpoint_event_stream(
        self,
        name: str,
        *,
        limit: int = 100,
        session_id: str | None = None,
        event_types: list[str] | str | None = None,
        last_event_id: str | None = None,
        after_event_id: str | None = None,
        since: float | None = None,
        until: float | None = None,
    ) -> StreamCheckpointStep:
        filters = stream_filters(
            session_id=session_id,
            event_types=event_types,
            since=since,
            until=until,
        )
        replay = EventReplay(events=[], filters=filters)
        event_count = 0
        if last_event_id is None:
            replay = self.replay_events(
                limit=limit,
                session_id=session_id,
                event_types=event_types,
                after_event_id=after_event_id,
                since=since,
                until=until,
            )
            last_event_id = replay.next_after_event_id
            event_count = len(replay.events)

        try:
            existing = self.store.load_stream_checkpoint(name)
            created_at = existing.created_at
            event_count += existing.event_count
        except FileNotFoundError:
            created_at = time.time()

        checkpoint = StreamCheckpoint(
            name=name,
            last_event_id=last_event_id,
            filters=filters,
            event_count=event_count,
            created_at=created_at,
            updated_at=time.time(),
        )
        self.store.save_stream_checkpoint(checkpoint)
        event = self._emit(
            "event_stream_checkpointed",
            {"checkpoint": checkpoint.to_dict()},
            session_id=session_id,
        )
        return StreamCheckpointStep(checkpoint=checkpoint, replay=replay, event=event)

    def resume_event_stream(
        self,
        name: str,
        *,
        limit: int = 100,
        advance: bool = False,
    ) -> EventReplay:
        checkpoint = self.store.load_stream_checkpoint(name)
        filters = checkpoint.filters
        replay = self.replay_events(
            limit=limit,
            session_id=filters.get("session_id"),
            event_types=filters.get("event_types"),
            after_event_id=checkpoint.last_event_id,
            since=filters.get("since"),
            until=filters.get("until"),
        )
        if advance and replay.next_after_event_id != checkpoint.last_event_id:
            updated = StreamCheckpoint(
                name=checkpoint.name,
                last_event_id=replay.next_after_event_id,
                filters=checkpoint.filters,
                event_count=checkpoint.event_count + len(replay.events),
                created_at=checkpoint.created_at,
                updated_at=time.time(),
            )
            self.store.save_stream_checkpoint(updated)
            self._emit(
                "event_stream_checkpointed",
                {"checkpoint": updated.to_dict(), "advanced": True},
                session_id=filters.get("session_id"),
            )
        return replay

    def list_stream_checkpoints(self, *, limit: int = 20) -> list[StreamCheckpoint]:
        return self.store.list_stream_checkpoints(limit=limit)

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

    def list_feedback(
        self,
        *,
        limit: int = 50,
        memory_id: str | None = None,
        session_id: str | None = None,
    ) -> list[ActivationFeedback]:
        return self.store.list_feedback(limit=limit, memory_id=memory_id, session_id=session_id)

    def list_reinforcements(self, *, limit: int = 50) -> list[ReinforcementState]:
        return self.store.list_reinforcements(limit=limit)

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
            "event_stream": self.event_summary(session_id=session.id, limit=limit).to_dict(),
            "memory_mesh": self.traverse_mesh(session.id, kind="session", depth=2, limit=limit).to_dict(),
            "latest_drift_report": (
                reports[0].to_dict()
                if (reports := self.list_drift_reports(limit=1, scope=f"session:{session.id}"))
                else None
            ),
            "recent_executions": [
                execution.to_dict()
                for execution in self.list_executions(session_id=session.id, limit=limit)
            ],
            "suggested_next_actions": suggestions[:limit],
        }

__all__ = [
    "CycleStep",
    "DecayStep",
    "DriftStep",
    "ExecutionCheckpoint",
    "ExecutionCheckpointStep",
    "ExecutionStatus",
    "ExecutionStep",
    "FeedbackStep",
    "MeshLinkStep",
    "MemoryActivation",
    "MemoryMeshEdge",
    "MemoryMeshNode",
    "MeshTraversal",
    "MythicRuntime",
    "PluginRunStep",
    "RuntimeExecution",
    "RuntimeStep",
]
