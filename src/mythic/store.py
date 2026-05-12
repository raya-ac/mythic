"""Local runtime persistence."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Protocol

from mythic.cycles import CognitiveCycle, ReflectionRecord
from mythic.drift import DriftReport
from mythic.events import CognitionEvent
from mythic.execution import ExecutionCheckpoint, ExecutionStatus, RuntimeExecution
from mythic.mesh import MemoryMeshEdge, MemoryMeshNode, merge_mesh_edge
from mythic.reinforcement import ActivationFeedback, ReinforcementState
from mythic.session import CognitiveSession
from mythic.streams import StreamCheckpoint, filter_replay_events, normalize_event_types


class RuntimeStore(Protocol):
    """Persistence contract used by the runtime."""

    root: Path

    def init(self) -> None: ...

    def save_session(self, session: CognitiveSession) -> None: ...

    def load_session(self, session_id: str) -> CognitiveSession: ...

    def list_sessions(self) -> list[CognitiveSession]: ...

    def save_event(self, event: CognitionEvent) -> None: ...

    def list_events(
        self,
        *,
        limit: int = 50,
        session_id: str | None = None,
    ) -> list[CognitionEvent]: ...

    def replay_events(
        self,
        *,
        limit: int = 100,
        session_id: str | None = None,
        event_types: list[str] | str | None = None,
        after_event_id: str | None = None,
        since: float | None = None,
        until: float | None = None,
    ) -> list[CognitionEvent]: ...

    def save_stream_checkpoint(self, checkpoint: StreamCheckpoint) -> None: ...

    def load_stream_checkpoint(self, name: str) -> StreamCheckpoint: ...

    def list_stream_checkpoints(self, *, limit: int = 20) -> list[StreamCheckpoint]: ...

    def save_cycle(self, cycle: CognitiveCycle) -> None: ...

    def list_cycles(
        self,
        *,
        limit: int = 20,
        session_id: str | None = None,
    ) -> list[CognitiveCycle]: ...

    def save_reflection(self, reflection: ReflectionRecord) -> None: ...

    def list_reflections(
        self,
        *,
        limit: int = 20,
        session_id: str | None = None,
    ) -> list[ReflectionRecord]: ...

    def save_feedback(self, feedback: ActivationFeedback) -> None: ...

    def list_feedback(
        self,
        *,
        limit: int = 50,
        memory_id: str | None = None,
        session_id: str | None = None,
    ) -> list[ActivationFeedback]: ...

    def load_reinforcement(self, memory_id: str) -> ReinforcementState | None: ...

    def save_reinforcement(self, state: ReinforcementState) -> None: ...

    def list_reinforcements(self, *, limit: int = 50) -> list[ReinforcementState]: ...

    def save_mesh_node(self, node: MemoryMeshNode) -> None: ...

    def load_mesh_node(self, node_id: str) -> MemoryMeshNode | None: ...

    def list_mesh_nodes(
        self,
        *,
        limit: int = 50,
        kind: str | None = None,
    ) -> list[MemoryMeshNode]: ...

    def save_mesh_edge(self, edge: MemoryMeshEdge) -> None: ...

    def load_mesh_edge(self, edge_id: str) -> MemoryMeshEdge | None: ...

    def list_mesh_edges(
        self,
        *,
        limit: int = 50,
        source_id: str | None = None,
        target_id: str | None = None,
        kind: str | None = None,
    ) -> list[MemoryMeshEdge]: ...

    def save_drift_report(self, report: DriftReport) -> None: ...

    def list_drift_reports(
        self,
        *,
        limit: int = 20,
        scope: str | None = None,
    ) -> list[DriftReport]: ...

    def save_execution(self, execution: RuntimeExecution) -> None: ...

    def load_execution(self, execution_id: str) -> RuntimeExecution: ...

    def list_executions(
        self,
        *,
        limit: int = 50,
        session_id: str | None = None,
        status: ExecutionStatus | str | None = None,
    ) -> list[RuntimeExecution]: ...

    def save_execution_checkpoint(self, checkpoint: ExecutionCheckpoint) -> None: ...

    def list_execution_checkpoints(
        self,
        *,
        execution_id: str,
        limit: int = 20,
    ) -> list[ExecutionCheckpoint]: ...


class JsonRuntimeStore:
    """Small transparent persistence backend for debugging runtime state."""

    def __init__(self, root: str | Path = ".mythic"):
        self.root = Path(root)
        self.sessions_dir = self.root / "sessions"
        self.events_path = self.root / "events.jsonl"
        self.cycles_path = self.root / "cycles.jsonl"
        self.reflections_path = self.root / "reflections.jsonl"
        self.feedback_path = self.root / "activation_feedback.jsonl"
        self.reinforcement_path = self.root / "reinforcement.json"
        self.mesh_nodes_path = self.root / "mesh_nodes.json"
        self.mesh_edges_path = self.root / "mesh_edges.json"
        self.drift_reports_path = self.root / "drift_reports.jsonl"
        self.executions_path = self.root / "executions.json"
        self.execution_checkpoints_path = self.root / "execution_checkpoints.jsonl"
        self.stream_checkpoints_path = self.root / "stream_checkpoints.json"

    def init(self) -> None:
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def save_session(self, session: CognitiveSession) -> None:
        self.init()
        path = self.sessions_dir / f"{session.id}.json"
        path.write_text(
            json.dumps(session.to_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def load_session(self, session_id: str) -> CognitiveSession:
        path = self.sessions_dir / f"{session_id}.json"
        return CognitiveSession.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def list_sessions(self) -> list[CognitiveSession]:
        self.init()
        sessions = [
            CognitiveSession.from_dict(json.loads(path.read_text(encoding="utf-8")))
            for path in self.sessions_dir.glob("*.json")
        ]
        return sorted(sessions, key=lambda session: session.updated_at, reverse=True)

    def save_event(self, event: CognitionEvent) -> None:
        self.init()
        with self.events_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event.to_dict(), sort_keys=True) + "\n")

    def _all_events(self) -> list[CognitionEvent]:
        if not self.events_path.exists():
            return []
        return [
            CognitionEvent.from_dict(json.loads(line))
            for line in self.events_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def list_events(
        self,
        *,
        limit: int = 50,
        session_id: str | None = None,
    ) -> list[CognitionEvent]:
        self.init()
        events = self._all_events()
        if session_id is not None:
            events = [event for event in events if event.session_id == session_id]
        if limit > 0:
            events = events[-limit:]
        return events

    def replay_events(
        self,
        *,
        limit: int = 100,
        session_id: str | None = None,
        event_types: list[str] | str | None = None,
        after_event_id: str | None = None,
        since: float | None = None,
        until: float | None = None,
    ) -> list[CognitionEvent]:
        self.init()
        return filter_replay_events(
            self._all_events(),
            limit=limit,
            session_id=session_id,
            event_types=event_types,
            after_event_id=after_event_id,
            since=since,
            until=until,
        )

    def _stream_checkpoints_payload(self) -> dict[str, dict]:
        if not self.stream_checkpoints_path.exists():
            return {}
        return json.loads(self.stream_checkpoints_path.read_text(encoding="utf-8"))

    def save_stream_checkpoint(self, checkpoint: StreamCheckpoint) -> None:
        self.init()
        payload = self._stream_checkpoints_payload()
        payload[checkpoint.name] = checkpoint.to_dict()
        self.stream_checkpoints_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def load_stream_checkpoint(self, name: str) -> StreamCheckpoint:
        self.init()
        data = self._stream_checkpoints_payload().get(name)
        if data is None:
            raise FileNotFoundError(f"stream checkpoint not found: {name}")
        return StreamCheckpoint.from_dict(data)

    def list_stream_checkpoints(self, *, limit: int = 20) -> list[StreamCheckpoint]:
        self.init()
        checkpoints = [
            StreamCheckpoint.from_dict(item)
            for item in self._stream_checkpoints_payload().values()
        ]
        checkpoints = sorted(checkpoints, key=lambda checkpoint: checkpoint.updated_at, reverse=True)
        if limit > 0:
            checkpoints = checkpoints[:limit]
        return checkpoints

    def save_cycle(self, cycle: CognitiveCycle) -> None:
        self.init()
        with self.cycles_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(cycle.to_dict(), sort_keys=True) + "\n")

    def list_cycles(
        self,
        *,
        limit: int = 20,
        session_id: str | None = None,
    ) -> list[CognitiveCycle]:
        self.init()
        if not self.cycles_path.exists():
            return []
        cycles = [
            CognitiveCycle.from_dict(json.loads(line))
            for line in self.cycles_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if session_id is not None:
            cycles = [cycle for cycle in cycles if cycle.session_id == session_id]
        if limit > 0:
            cycles = cycles[-limit:]
        return cycles

    def save_reflection(self, reflection: ReflectionRecord) -> None:
        self.init()
        with self.reflections_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(reflection.to_dict(), sort_keys=True) + "\n")

    def list_reflections(
        self,
        *,
        limit: int = 20,
        session_id: str | None = None,
    ) -> list[ReflectionRecord]:
        self.init()
        if not self.reflections_path.exists():
            return []
        reflections = [
            ReflectionRecord.from_dict(json.loads(line))
            for line in self.reflections_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if session_id is not None:
            reflections = [reflection for reflection in reflections if reflection.session_id == session_id]
        if limit > 0:
            reflections = reflections[-limit:]
        return reflections

    def save_feedback(self, feedback: ActivationFeedback) -> None:
        self.init()
        with self.feedback_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(feedback.to_dict(), sort_keys=True) + "\n")

    def list_feedback(
        self,
        *,
        limit: int = 50,
        memory_id: str | None = None,
        session_id: str | None = None,
    ) -> list[ActivationFeedback]:
        self.init()
        if not self.feedback_path.exists():
            return []
        feedback = [
            ActivationFeedback.from_dict(json.loads(line))
            for line in self.feedback_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if memory_id is not None:
            feedback = [item for item in feedback if item.memory_id == memory_id]
        if session_id is not None:
            feedback = [item for item in feedback if item.session_id == session_id]
        if limit > 0:
            feedback = feedback[-limit:]
        return feedback

    def _reinforcement_payload(self) -> dict[str, dict]:
        if not self.reinforcement_path.exists():
            return {}
        return json.loads(self.reinforcement_path.read_text(encoding="utf-8"))

    def load_reinforcement(self, memory_id: str) -> ReinforcementState | None:
        self.init()
        payload = self._reinforcement_payload().get(memory_id)
        if payload is None:
            return None
        return ReinforcementState.from_dict(payload)

    def save_reinforcement(self, state: ReinforcementState) -> None:
        self.init()
        payload = self._reinforcement_payload()
        payload[state.memory_id] = state.to_dict()
        self.reinforcement_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def list_reinforcements(self, *, limit: int = 50) -> list[ReinforcementState]:
        self.init()
        states = [
            ReinforcementState.from_dict(item)
            for item in self._reinforcement_payload().values()
        ]
        states = sorted(states, key=lambda state: state.updated_at, reverse=True)
        if limit > 0:
            states = states[:limit]
        return states

    def _mesh_nodes_payload(self) -> dict[str, dict]:
        if not self.mesh_nodes_path.exists():
            return {}
        return json.loads(self.mesh_nodes_path.read_text(encoding="utf-8"))

    def _mesh_edges_payload(self) -> dict[str, dict]:
        if not self.mesh_edges_path.exists():
            return {}
        return json.loads(self.mesh_edges_path.read_text(encoding="utf-8"))

    def save_mesh_node(self, node: MemoryMeshNode) -> None:
        self.init()
        payload = self._mesh_nodes_payload()
        existing = payload.get(node.id)
        if existing is not None:
            existing_metadata = dict(existing.get("metadata", {}))
            existing_metadata.update(node.metadata)
            node = MemoryMeshNode(
                id=node.id,
                kind=node.kind,
                label=node.label,
                metadata=existing_metadata,
                created_at=float(existing.get("created_at", node.created_at)),
                updated_at=node.updated_at,
            )
        payload[node.id] = node.to_dict()
        self.mesh_nodes_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def load_mesh_node(self, node_id: str) -> MemoryMeshNode | None:
        self.init()
        payload = self._mesh_nodes_payload().get(node_id)
        if payload is None:
            return None
        return MemoryMeshNode.from_dict(payload)

    def list_mesh_nodes(
        self,
        *,
        limit: int = 50,
        kind: str | None = None,
    ) -> list[MemoryMeshNode]:
        self.init()
        nodes = [
            MemoryMeshNode.from_dict(item)
            for item in self._mesh_nodes_payload().values()
        ]
        if kind is not None:
            nodes = [node for node in nodes if node.kind == kind]
        nodes = sorted(nodes, key=lambda node: node.updated_at, reverse=True)
        if limit > 0:
            nodes = nodes[:limit]
        return nodes

    def save_mesh_edge(self, edge: MemoryMeshEdge) -> None:
        self.init()
        payload = self._mesh_edges_payload()
        existing = payload.get(edge.id)
        if existing is not None:
            edge = merge_mesh_edge(MemoryMeshEdge.from_dict(existing), edge)
        payload[edge.id] = edge.to_dict()
        self.mesh_edges_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def load_mesh_edge(self, edge_id: str) -> MemoryMeshEdge | None:
        self.init()
        payload = self._mesh_edges_payload().get(edge_id)
        if payload is None:
            return None
        return MemoryMeshEdge.from_dict(payload)

    def list_mesh_edges(
        self,
        *,
        limit: int = 50,
        source_id: str | None = None,
        target_id: str | None = None,
        kind: str | None = None,
    ) -> list[MemoryMeshEdge]:
        self.init()
        edges = [
            MemoryMeshEdge.from_dict(item)
            for item in self._mesh_edges_payload().values()
        ]
        if source_id is not None:
            edges = [edge for edge in edges if edge.source_id == source_id]
        if target_id is not None:
            edges = [edge for edge in edges if edge.target_id == target_id]
        if kind is not None:
            edges = [edge for edge in edges if edge.kind == kind]
        edges = sorted(edges, key=lambda edge: edge.updated_at, reverse=True)
        if limit > 0:
            edges = edges[:limit]
        return edges

    def save_drift_report(self, report: DriftReport) -> None:
        self.init()
        with self.drift_reports_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(report.to_dict(), sort_keys=True) + "\n")

    def list_drift_reports(
        self,
        *,
        limit: int = 20,
        scope: str | None = None,
    ) -> list[DriftReport]:
        self.init()
        if not self.drift_reports_path.exists():
            return []
        reports = [
            DriftReport.from_dict(json.loads(line))
            for line in self.drift_reports_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if scope is not None:
            reports = [report for report in reports if report.scope == scope]
        reports = sorted(reports, key=lambda report: report.generated_at, reverse=True)
        if limit > 0:
            reports = reports[:limit]
        return reports

    def _executions_payload(self) -> dict[str, dict]:
        if not self.executions_path.exists():
            return {}
        return json.loads(self.executions_path.read_text(encoding="utf-8"))

    def save_execution(self, execution: RuntimeExecution) -> None:
        self.init()
        payload = self._executions_payload()
        payload[execution.id] = execution.to_dict()
        self.executions_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def load_execution(self, execution_id: str) -> RuntimeExecution:
        self.init()
        data = self._executions_payload().get(execution_id)
        if data is None:
            raise FileNotFoundError(f"execution not found: {execution_id}")
        return RuntimeExecution.from_dict(data)

    def list_executions(
        self,
        *,
        limit: int = 50,
        session_id: str | None = None,
        status: ExecutionStatus | str | None = None,
    ) -> list[RuntimeExecution]:
        self.init()
        executions = [
            RuntimeExecution.from_dict(item)
            for item in self._executions_payload().values()
        ]
        if session_id is not None:
            executions = [execution for execution in executions if execution.session_id == session_id]
        if status is not None:
            parsed_status = ExecutionStatus(status)
            executions = [execution for execution in executions if execution.status == parsed_status]
        executions = sorted(executions, key=lambda execution: execution.updated_at, reverse=True)
        if limit > 0:
            executions = executions[:limit]
        return executions

    def save_execution_checkpoint(self, checkpoint: ExecutionCheckpoint) -> None:
        self.init()
        with self.execution_checkpoints_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(checkpoint.to_dict(), sort_keys=True) + "\n")

    def list_execution_checkpoints(
        self,
        *,
        execution_id: str,
        limit: int = 20,
    ) -> list[ExecutionCheckpoint]:
        self.init()
        if not self.execution_checkpoints_path.exists():
            return []
        checkpoints = [
            ExecutionCheckpoint.from_dict(json.loads(line))
            for line in self.execution_checkpoints_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        checkpoints = [checkpoint for checkpoint in checkpoints if checkpoint.execution_id == execution_id]
        checkpoints = sorted(checkpoints, key=lambda checkpoint: checkpoint.created_at, reverse=True)
        if limit > 0:
            checkpoints = checkpoints[:limit]
        return checkpoints


class SQLiteRuntimeStore:
    """SQLite-backed local-first persistence for sessions and cognition events."""

    def __init__(self, root: str | Path = ".mythic"):
        self.root = Path(root)
        if self.root.suffix in {".db", ".sqlite", ".sqlite3"}:
            self.db_path = self.root
        else:
            self.db_path = self.root / "runtime.db"
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def init(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                goal TEXT NOT NULL,
                status TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_updated
                ON sessions(updated_at DESC);

            CREATE TABLE IF NOT EXISTS events (
                event_id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                session_id TEXT,
                timestamp REAL NOT NULL,
                data TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_events_timestamp
                ON events(timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_events_session
                ON events(session_id, timestamp DESC);

            CREATE TABLE IF NOT EXISTS stream_checkpoints (
                name TEXT PRIMARY KEY,
                last_event_id TEXT,
                filters TEXT NOT NULL,
                event_count INTEGER NOT NULL,
                payload TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_stream_checkpoints_updated
                ON stream_checkpoints(updated_at DESC);

            CREATE TABLE IF NOT EXISTS cycles (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                status TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at REAL NOT NULL,
                completed_at REAL
            );
            CREATE INDEX IF NOT EXISTS idx_cycles_session
                ON cycles(session_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS reflections (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                cycle_id TEXT,
                kind TEXT NOT NULL,
                severity TEXT NOT NULL,
                subject TEXT NOT NULL,
                detail TEXT NOT NULL,
                metadata TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_reflections_session
                ON reflections(session_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS activation_feedback (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                cycle_id TEXT,
                memory_id TEXT NOT NULL,
                outcome TEXT NOT NULL,
                signal REAL NOT NULL,
                note TEXT,
                source TEXT NOT NULL,
                metadata TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_activation_feedback_memory
                ON activation_feedback(memory_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_activation_feedback_session
                ON activation_feedback(session_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS reinforcement_state (
                memory_id TEXT PRIMARY KEY,
                score REAL NOT NULL,
                uses INTEGER NOT NULL,
                successes INTEGER NOT NULL,
                failures INTEGER NOT NULL,
                contradictions INTEGER NOT NULL,
                stale INTEGER NOT NULL,
                last_outcome TEXT,
                updated_at REAL NOT NULL,
                decayed_at REAL
            );
            CREATE INDEX IF NOT EXISTS idx_reinforcement_updated
                ON reinforcement_state(updated_at DESC);

            CREATE TABLE IF NOT EXISTS mesh_nodes (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                label TEXT NOT NULL,
                metadata TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_mesh_nodes_kind
                ON mesh_nodes(kind, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_mesh_nodes_updated
                ON mesh_nodes(updated_at DESC);

            CREATE TABLE IF NOT EXISTS mesh_edges (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                confidence REAL NOT NULL,
                planner_relevance REAL NOT NULL,
                emotional_weight REAL NOT NULL,
                activation_count INTEGER NOT NULL,
                metadata TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                last_activated_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_mesh_edges_source
                ON mesh_edges(source_id, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_mesh_edges_target
                ON mesh_edges(target_id, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_mesh_edges_kind
                ON mesh_edges(kind, updated_at DESC);

            CREATE TABLE IF NOT EXISTS drift_reports (
                id TEXT PRIMARY KEY,
                scope TEXT NOT NULL,
                score REAL NOT NULL,
                issue_count INTEGER NOT NULL,
                payload TEXT NOT NULL,
                generated_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_drift_reports_scope
                ON drift_reports(scope, generated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_drift_reports_generated
                ON drift_reports(generated_at DESC);

            CREATE TABLE IF NOT EXISTS executions (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                goal TEXT NOT NULL,
                status TEXT NOT NULL,
                attempt INTEGER NOT NULL,
                parent_id TEXT,
                relation TEXT,
                payload TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                started_at REAL,
                completed_at REAL
            );
            CREATE INDEX IF NOT EXISTS idx_executions_session
                ON executions(session_id, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_executions_status
                ON executions(status, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_executions_parent
                ON executions(parent_id, updated_at DESC);

            CREATE TABLE IF NOT EXISTS execution_checkpoints (
                id TEXT PRIMARY KEY,
                execution_id TEXT NOT NULL,
                note TEXT NOT NULL,
                payload TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_execution_checkpoints_execution
                ON execution_checkpoints(execution_id, created_at DESC);
            """
        )
        self.conn.commit()

    def save_session(self, session: CognitiveSession) -> None:
        self.init()
        payload = json.dumps(session.to_dict(), sort_keys=True)
        self.conn.execute(
            """
            INSERT INTO sessions (id, goal, status, payload, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                goal = excluded.goal,
                status = excluded.status,
                payload = excluded.payload,
                updated_at = excluded.updated_at
            """,
            (
                session.id,
                session.goal,
                session.status,
                payload,
                session.created_at,
                session.updated_at,
            ),
        )
        self.conn.commit()

    def load_session(self, session_id: str) -> CognitiveSession:
        self.init()
        row = self.conn.execute(
            "SELECT payload FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            raise FileNotFoundError(f"session not found: {session_id}")
        return CognitiveSession.from_dict(json.loads(row["payload"]))

    def list_sessions(self) -> list[CognitiveSession]:
        self.init()
        rows = self.conn.execute(
            "SELECT payload FROM sessions ORDER BY updated_at DESC"
        ).fetchall()
        return [CognitiveSession.from_dict(json.loads(row["payload"])) for row in rows]

    def save_event(self, event: CognitionEvent) -> None:
        self.init()
        self.conn.execute(
            """
            INSERT OR IGNORE INTO events (event_id, type, session_id, timestamp, data)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.type,
                event.session_id,
                event.timestamp,
                json.dumps(event.data, sort_keys=True),
            ),
        )
        self.conn.commit()

    def list_events(
        self,
        *,
        limit: int = 50,
        session_id: str | None = None,
    ) -> list[CognitionEvent]:
        self.init()
        params: list[object] = []
        where = ""
        if session_id is not None:
            where = "WHERE session_id = ?"
            params.append(session_id)

        if limit > 0:
            params.append(limit)
            rows = self.conn.execute(
                f"""
                SELECT * FROM events
                {where}
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
            rows = list(reversed(rows))
        else:
            rows = self.conn.execute(
                f"""
                SELECT * FROM events
                {where}
                ORDER BY timestamp ASC
                """,
                params,
            ).fetchall()

        return [
            CognitionEvent(
                event_id=row["event_id"],
                type=row["type"],
                session_id=row["session_id"],
                timestamp=row["timestamp"],
                data=json.loads(row["data"]),
            )
            for row in rows
        ]

    def replay_events(
        self,
        *,
        limit: int = 100,
        session_id: str | None = None,
        event_types: list[str] | str | None = None,
        after_event_id: str | None = None,
        since: float | None = None,
        until: float | None = None,
    ) -> list[CognitionEvent]:
        self.init()
        params: list[object] = []
        filters: list[str] = []
        if after_event_id is not None:
            row = self.conn.execute(
                "SELECT rowid FROM events WHERE event_id = ?",
                (after_event_id,),
            ).fetchone()
            if row is not None:
                filters.append("rowid > ?")
                params.append(row["rowid"])
        if session_id is not None:
            filters.append("session_id = ?")
            params.append(session_id)
        normalized_types = normalize_event_types(event_types)
        if normalized_types is not None:
            placeholders = ", ".join("?" for _ in normalized_types)
            filters.append(f"type IN ({placeholders})")
            params.extend(normalized_types)
        if since is not None:
            filters.append("timestamp >= ?")
            params.append(since)
        if until is not None:
            filters.append("timestamp <= ?")
            params.append(until)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""

        if limit > 0:
            params.append(limit)
            rows = self.conn.execute(
                f"""
                SELECT * FROM events
                {where}
                ORDER BY rowid ASC
                LIMIT ?
                """,
                params,
            ).fetchall()
        else:
            rows = self.conn.execute(
                f"""
                SELECT * FROM events
                {where}
                ORDER BY rowid ASC
                """,
                params,
            ).fetchall()
        return [
            CognitionEvent(
                event_id=row["event_id"],
                type=row["type"],
                session_id=row["session_id"],
                timestamp=row["timestamp"],
                data=json.loads(row["data"]),
            )
            for row in rows
        ]

    def save_stream_checkpoint(self, checkpoint: StreamCheckpoint) -> None:
        self.init()
        self.conn.execute(
            """
            INSERT INTO stream_checkpoints
            (name, last_event_id, filters, event_count, payload, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                last_event_id = excluded.last_event_id,
                filters = excluded.filters,
                event_count = excluded.event_count,
                payload = excluded.payload,
                updated_at = excluded.updated_at
            """,
            (
                checkpoint.name,
                checkpoint.last_event_id,
                json.dumps(checkpoint.filters, sort_keys=True),
                checkpoint.event_count,
                json.dumps(checkpoint.to_dict(), sort_keys=True),
                checkpoint.created_at,
                checkpoint.updated_at,
            ),
        )
        self.conn.commit()

    def load_stream_checkpoint(self, name: str) -> StreamCheckpoint:
        self.init()
        row = self.conn.execute(
            "SELECT payload FROM stream_checkpoints WHERE name = ?",
            (name,),
        ).fetchone()
        if row is None:
            raise FileNotFoundError(f"stream checkpoint not found: {name}")
        return StreamCheckpoint.from_dict(json.loads(row["payload"]))

    def list_stream_checkpoints(self, *, limit: int = 20) -> list[StreamCheckpoint]:
        self.init()
        params: list[object] = []
        if limit > 0:
            params.append(limit)
            rows = self.conn.execute(
                """
                SELECT payload FROM stream_checkpoints
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT payload FROM stream_checkpoints
                ORDER BY updated_at DESC
                """
            ).fetchall()
        return [StreamCheckpoint.from_dict(json.loads(row["payload"])) for row in rows]

    def save_cycle(self, cycle: CognitiveCycle) -> None:
        self.init()
        self.conn.execute(
            """
            INSERT OR REPLACE INTO cycles
            (id, session_id, status, payload, created_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                cycle.id,
                cycle.session_id,
                cycle.status,
                json.dumps(cycle.to_dict(), sort_keys=True),
                cycle.created_at,
                cycle.completed_at,
            ),
        )
        self.conn.commit()

    def list_cycles(
        self,
        *,
        limit: int = 20,
        session_id: str | None = None,
    ) -> list[CognitiveCycle]:
        self.init()
        params: list[object] = []
        where = ""
        if session_id is not None:
            where = "WHERE session_id = ?"
            params.append(session_id)

        if limit > 0:
            params.append(limit)
            rows = self.conn.execute(
                f"""
                SELECT payload FROM cycles
                {where}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
            rows = list(reversed(rows))
        else:
            rows = self.conn.execute(
                f"""
                SELECT payload FROM cycles
                {where}
                ORDER BY created_at ASC
                """,
                params,
            ).fetchall()

        return [CognitiveCycle.from_dict(json.loads(row["payload"])) for row in rows]

    def save_reflection(self, reflection: ReflectionRecord) -> None:
        self.init()
        self.conn.execute(
            """
            INSERT OR REPLACE INTO reflections
            (id, session_id, cycle_id, kind, severity, subject, detail, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                reflection.id,
                reflection.session_id,
                reflection.cycle_id,
                reflection.kind,
                reflection.severity,
                reflection.subject,
                reflection.detail,
                json.dumps(reflection.metadata, sort_keys=True),
                reflection.created_at,
            ),
        )
        self.conn.commit()

    def list_reflections(
        self,
        *,
        limit: int = 20,
        session_id: str | None = None,
    ) -> list[ReflectionRecord]:
        self.init()
        params: list[object] = []
        where = ""
        if session_id is not None:
            where = "WHERE session_id = ?"
            params.append(session_id)

        if limit > 0:
            params.append(limit)
            rows = self.conn.execute(
                f"""
                SELECT * FROM reflections
                {where}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
            rows = list(reversed(rows))
        else:
            rows = self.conn.execute(
                f"""
                SELECT * FROM reflections
                {where}
                ORDER BY created_at ASC
                """,
                params,
            ).fetchall()

        return [
            ReflectionRecord(
                id=row["id"],
                session_id=row["session_id"],
                cycle_id=row["cycle_id"],
                kind=row["kind"],
                severity=row["severity"],
                subject=row["subject"],
                detail=row["detail"],
                metadata=json.loads(row["metadata"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def save_feedback(self, feedback: ActivationFeedback) -> None:
        self.init()
        self.conn.execute(
            """
            INSERT OR IGNORE INTO activation_feedback
            (id, session_id, cycle_id, memory_id, outcome, signal, note, source, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                feedback.id,
                feedback.session_id,
                feedback.cycle_id,
                feedback.memory_id,
                feedback.outcome.value,
                feedback.signal,
                feedback.note,
                feedback.source,
                json.dumps(feedback.metadata, sort_keys=True),
                feedback.created_at,
            ),
        )
        self.conn.commit()

    def list_feedback(
        self,
        *,
        limit: int = 50,
        memory_id: str | None = None,
        session_id: str | None = None,
    ) -> list[ActivationFeedback]:
        self.init()
        params: list[object] = []
        filters: list[str] = []
        if memory_id is not None:
            filters.append("memory_id = ?")
            params.append(memory_id)
        if session_id is not None:
            filters.append("session_id = ?")
            params.append(session_id)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""

        if limit > 0:
            params.append(limit)
            rows = self.conn.execute(
                f"""
                SELECT * FROM activation_feedback
                {where}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
            rows = list(reversed(rows))
        else:
            rows = self.conn.execute(
                f"""
                SELECT * FROM activation_feedback
                {where}
                ORDER BY created_at ASC
                """,
                params,
            ).fetchall()

        return [
            ActivationFeedback.from_dict(
                {
                    "id": row["id"],
                    "session_id": row["session_id"],
                    "cycle_id": row["cycle_id"],
                    "memory_id": row["memory_id"],
                    "outcome": row["outcome"],
                    "signal": row["signal"],
                    "note": row["note"],
                    "source": row["source"],
                    "metadata": json.loads(row["metadata"]),
                    "created_at": row["created_at"],
                }
            )
            for row in rows
        ]

    def load_reinforcement(self, memory_id: str) -> ReinforcementState | None:
        self.init()
        row = self.conn.execute(
            "SELECT * FROM reinforcement_state WHERE memory_id = ?",
            (memory_id,),
        ).fetchone()
        if row is None:
            return None
        return ReinforcementState.from_dict(dict(row))

    def save_reinforcement(self, state: ReinforcementState) -> None:
        self.init()
        self.conn.execute(
            """
            INSERT INTO reinforcement_state
            (memory_id, score, uses, successes, failures, contradictions, stale, last_outcome, updated_at, decayed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(memory_id) DO UPDATE SET
                score = excluded.score,
                uses = excluded.uses,
                successes = excluded.successes,
                failures = excluded.failures,
                contradictions = excluded.contradictions,
                stale = excluded.stale,
                last_outcome = excluded.last_outcome,
                updated_at = excluded.updated_at,
                decayed_at = excluded.decayed_at
            """,
            (
                state.memory_id,
                state.score,
                state.uses,
                state.successes,
                state.failures,
                state.contradictions,
                state.stale,
                state.last_outcome.value if state.last_outcome is not None else None,
                state.updated_at,
                state.decayed_at,
            ),
        )
        self.conn.commit()

    def list_reinforcements(self, *, limit: int = 50) -> list[ReinforcementState]:
        self.init()
        if limit > 0:
            rows = self.conn.execute(
                """
                SELECT * FROM reinforcement_state
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT * FROM reinforcement_state
                ORDER BY updated_at DESC
                """
            ).fetchall()
        return [ReinforcementState.from_dict(dict(row)) for row in rows]

    def save_mesh_node(self, node: MemoryMeshNode) -> None:
        self.init()
        existing = self.load_mesh_node(node.id)
        if existing is not None:
            metadata = dict(existing.metadata)
            metadata.update(node.metadata)
            node = MemoryMeshNode(
                id=node.id,
                kind=node.kind,
                label=node.label,
                metadata=metadata,
                created_at=existing.created_at,
                updated_at=node.updated_at,
            )
        self.conn.execute(
            """
            INSERT INTO mesh_nodes (id, kind, label, metadata, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                kind = excluded.kind,
                label = excluded.label,
                metadata = excluded.metadata,
                updated_at = excluded.updated_at
            """,
            (
                node.id,
                node.kind,
                node.label,
                json.dumps(node.metadata, sort_keys=True),
                node.created_at,
                node.updated_at,
            ),
        )
        self.conn.commit()

    def load_mesh_node(self, node_id: str) -> MemoryMeshNode | None:
        self.init()
        row = self.conn.execute(
            "SELECT * FROM mesh_nodes WHERE id = ?",
            (node_id,),
        ).fetchone()
        if row is None:
            return None
        return MemoryMeshNode(
            id=row["id"],
            kind=row["kind"],
            label=row["label"],
            metadata=json.loads(row["metadata"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list_mesh_nodes(
        self,
        *,
        limit: int = 50,
        kind: str | None = None,
    ) -> list[MemoryMeshNode]:
        self.init()
        params: list[object] = []
        where = ""
        if kind is not None:
            where = "WHERE kind = ?"
            params.append(kind)
        if limit > 0:
            params.append(limit)
            rows = self.conn.execute(
                f"""
                SELECT * FROM mesh_nodes
                {where}
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        else:
            rows = self.conn.execute(
                f"""
                SELECT * FROM mesh_nodes
                {where}
                ORDER BY updated_at DESC
                """,
                params,
            ).fetchall()
        return [
            MemoryMeshNode(
                id=row["id"],
                kind=row["kind"],
                label=row["label"],
                metadata=json.loads(row["metadata"]),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    def save_mesh_edge(self, edge: MemoryMeshEdge) -> None:
        self.init()
        existing = self.load_mesh_edge(edge.id)
        if existing is not None:
            edge = merge_mesh_edge(existing, edge)
        self.conn.execute(
            """
            INSERT INTO mesh_edges
            (id, source_id, target_id, kind, confidence, planner_relevance, emotional_weight,
             activation_count, metadata, created_at, updated_at, last_activated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                confidence = excluded.confidence,
                planner_relevance = excluded.planner_relevance,
                emotional_weight = excluded.emotional_weight,
                activation_count = excluded.activation_count,
                metadata = excluded.metadata,
                updated_at = excluded.updated_at,
                last_activated_at = excluded.last_activated_at
            """,
            (
                edge.id,
                edge.source_id,
                edge.target_id,
                edge.kind,
                edge.confidence,
                edge.planner_relevance,
                edge.emotional_weight,
                edge.activation_count,
                json.dumps(edge.metadata, sort_keys=True),
                edge.created_at,
                edge.updated_at,
                edge.last_activated_at,
            ),
        )
        self.conn.commit()

    def load_mesh_edge(self, edge_id: str) -> MemoryMeshEdge | None:
        self.init()
        row = self.conn.execute(
            "SELECT * FROM mesh_edges WHERE id = ?",
            (edge_id,),
        ).fetchone()
        if row is None:
            return None
        return MemoryMeshEdge(
            id=row["id"],
            source_id=row["source_id"],
            target_id=row["target_id"],
            kind=row["kind"],
            confidence=row["confidence"],
            planner_relevance=row["planner_relevance"],
            emotional_weight=row["emotional_weight"],
            activation_count=row["activation_count"],
            metadata=json.loads(row["metadata"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_activated_at=row["last_activated_at"],
        )

    def list_mesh_edges(
        self,
        *,
        limit: int = 50,
        source_id: str | None = None,
        target_id: str | None = None,
        kind: str | None = None,
    ) -> list[MemoryMeshEdge]:
        self.init()
        params: list[object] = []
        filters: list[str] = []
        if source_id is not None:
            filters.append("source_id = ?")
            params.append(source_id)
        if target_id is not None:
            filters.append("target_id = ?")
            params.append(target_id)
        if kind is not None:
            filters.append("kind = ?")
            params.append(kind)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""

        if limit > 0:
            params.append(limit)
            rows = self.conn.execute(
                f"""
                SELECT * FROM mesh_edges
                {where}
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        else:
            rows = self.conn.execute(
                f"""
                SELECT * FROM mesh_edges
                {where}
                ORDER BY updated_at DESC
                """,
                params,
            ).fetchall()
        return [
            MemoryMeshEdge(
                id=row["id"],
                source_id=row["source_id"],
                target_id=row["target_id"],
                kind=row["kind"],
                confidence=row["confidence"],
                planner_relevance=row["planner_relevance"],
                emotional_weight=row["emotional_weight"],
                activation_count=row["activation_count"],
                metadata=json.loads(row["metadata"]),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                last_activated_at=row["last_activated_at"],
            )
            for row in rows
        ]

    def save_drift_report(self, report: DriftReport) -> None:
        self.init()
        self.conn.execute(
            """
            INSERT OR REPLACE INTO drift_reports
            (id, scope, score, issue_count, payload, generated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                report.id,
                report.scope,
                report.score,
                len(report.issues),
                json.dumps(report.to_dict(), sort_keys=True),
                report.generated_at,
            ),
        )
        self.conn.commit()

    def list_drift_reports(
        self,
        *,
        limit: int = 20,
        scope: str | None = None,
    ) -> list[DriftReport]:
        self.init()
        params: list[object] = []
        where = ""
        if scope is not None:
            where = "WHERE scope = ?"
            params.append(scope)
        if limit > 0:
            params.append(limit)
            rows = self.conn.execute(
                f"""
                SELECT payload FROM drift_reports
                {where}
                ORDER BY generated_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        else:
            rows = self.conn.execute(
                f"""
                SELECT payload FROM drift_reports
                {where}
                ORDER BY generated_at DESC
                """,
                params,
            ).fetchall()
        return [DriftReport.from_dict(json.loads(row["payload"])) for row in rows]

    def save_execution(self, execution: RuntimeExecution) -> None:
        self.init()
        self.conn.execute(
            """
            INSERT INTO executions
            (id, session_id, kind, goal, status, attempt, parent_id, relation, payload,
             created_at, updated_at, started_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                session_id = excluded.session_id,
                kind = excluded.kind,
                goal = excluded.goal,
                status = excluded.status,
                attempt = excluded.attempt,
                parent_id = excluded.parent_id,
                relation = excluded.relation,
                payload = excluded.payload,
                updated_at = excluded.updated_at,
                started_at = excluded.started_at,
                completed_at = excluded.completed_at
            """,
            (
                execution.id,
                execution.session_id,
                execution.kind,
                execution.goal,
                execution.status.value,
                execution.attempt,
                execution.parent_id,
                execution.relation,
                json.dumps(execution.to_dict(), sort_keys=True),
                execution.created_at,
                execution.updated_at,
                execution.started_at,
                execution.completed_at,
            ),
        )
        self.conn.commit()

    def load_execution(self, execution_id: str) -> RuntimeExecution:
        self.init()
        row = self.conn.execute(
            "SELECT payload FROM executions WHERE id = ?",
            (execution_id,),
        ).fetchone()
        if row is None:
            raise FileNotFoundError(f"execution not found: {execution_id}")
        return RuntimeExecution.from_dict(json.loads(row["payload"]))

    def list_executions(
        self,
        *,
        limit: int = 50,
        session_id: str | None = None,
        status: ExecutionStatus | str | None = None,
    ) -> list[RuntimeExecution]:
        self.init()
        params: list[object] = []
        filters: list[str] = []
        if session_id is not None:
            filters.append("session_id = ?")
            params.append(session_id)
        if status is not None:
            filters.append("status = ?")
            params.append(ExecutionStatus(status).value)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""

        if limit > 0:
            params.append(limit)
            rows = self.conn.execute(
                f"""
                SELECT payload FROM executions
                {where}
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        else:
            rows = self.conn.execute(
                f"""
                SELECT payload FROM executions
                {where}
                ORDER BY updated_at DESC
                """,
                params,
            ).fetchall()
        return [RuntimeExecution.from_dict(json.loads(row["payload"])) for row in rows]

    def save_execution_checkpoint(self, checkpoint: ExecutionCheckpoint) -> None:
        self.init()
        self.conn.execute(
            """
            INSERT OR REPLACE INTO execution_checkpoints
            (id, execution_id, note, payload, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                checkpoint.id,
                checkpoint.execution_id,
                checkpoint.note,
                json.dumps(checkpoint.to_dict(), sort_keys=True),
                checkpoint.created_at,
            ),
        )
        self.conn.commit()

    def list_execution_checkpoints(
        self,
        *,
        execution_id: str,
        limit: int = 20,
    ) -> list[ExecutionCheckpoint]:
        self.init()
        params: list[object] = [execution_id]
        if limit > 0:
            params.append(limit)
            rows = self.conn.execute(
                """
                SELECT payload FROM execution_checkpoints
                WHERE execution_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        else:
            rows = self.conn.execute(
                """
                SELECT payload FROM execution_checkpoints
                WHERE execution_id = ?
                ORDER BY created_at DESC
                """,
                params,
            ).fetchall()
        return [ExecutionCheckpoint.from_dict(json.loads(row["payload"])) for row in rows]

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None


def make_runtime_store(
    root: str | Path = ".mythic",
    *,
    backend: str = "sqlite",
) -> RuntimeStore:
    if backend == "json":
        return JsonRuntimeStore(root)
    if backend == "sqlite":
        return SQLiteRuntimeStore(root)
    raise ValueError(f"unknown runtime store backend: {backend}")
