"""Runtime drift detection models and analysis."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from mythic.mesh import mesh_node_id
from mythic.planner import TaskStatus
from mythic.reinforcement import ActivationOutcome


class DriftSeverity(str, Enum):
    """Severity levels for drift issues."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


DEFAULT_IMPACT: dict[DriftSeverity, float] = {
    DriftSeverity.INFO: 1.5,
    DriftSeverity.WARNING: 6.0,
    DriftSeverity.ERROR: 12.0,
}


@dataclass(frozen=True)
class DriftIssue:
    """One detected runtime, planner, memory, or graph inconsistency."""

    kind: str
    severity: DriftSeverity
    subject: str
    detail: str
    score_impact: float
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str | None = None
    created_at: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if self.id is None:
            digest = hashlib.sha1(
                f"{self.kind}\0{self.severity.value}\0{self.subject}\0{self.detail}".encode("utf-8")
            ).hexdigest()
            object.__setattr__(self, "id", digest[:24])

    @classmethod
    def create(
        cls,
        *,
        kind: str,
        severity: DriftSeverity | str,
        subject: str,
        detail: str,
        metadata: dict[str, Any] | None = None,
        score_impact: float | None = None,
    ) -> "DriftIssue":
        parsed_severity = DriftSeverity(severity)
        return cls(
            kind=kind,
            severity=parsed_severity,
            subject=subject,
            detail=detail,
            score_impact=float(score_impact if score_impact is not None else DEFAULT_IMPACT[parsed_severity]),
            metadata=metadata or {},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "severity": self.severity.value,
            "subject": self.subject,
            "detail": self.detail,
            "score_impact": self.score_impact,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DriftIssue":
        return cls(
            id=data["id"],
            kind=data["kind"],
            severity=DriftSeverity(data["severity"]),
            subject=data["subject"],
            detail=data["detail"],
            score_impact=float(data.get("score_impact", DEFAULT_IMPACT[DriftSeverity(data["severity"])])),
            metadata=dict(data.get("metadata", {})),
            created_at=float(data.get("created_at", time.time())),
        )


@dataclass(frozen=True)
class DriftReport:
    """A persisted drift inspection result."""

    scope: str
    issues: list[DriftIssue] = field(default_factory=list)
    score: float = 100.0
    id: str | None = None
    generated_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.id is None:
            digest = hashlib.sha1(f"{self.scope}\0{self.generated_at}".encode("utf-8")).hexdigest()
            object.__setattr__(self, "id", digest[:24])

    @classmethod
    def create(
        cls,
        *,
        scope: str,
        issues: list[DriftIssue],
        metadata: dict[str, Any] | None = None,
    ) -> "DriftReport":
        impact = sum(issue.score_impact for issue in issues)
        return cls(
            scope=scope,
            issues=issues,
            score=max(0.0, min(100.0, 100.0 - impact)),
            metadata=metadata or {},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "scope": self.scope,
            "score": self.score,
            "issue_count": len(self.issues),
            "generated_at": self.generated_at,
            "metadata": self.metadata,
            "issues": [issue.to_dict() for issue in self.issues],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DriftReport":
        return cls(
            id=data["id"],
            scope=data["scope"],
            score=float(data.get("score", 100.0)),
            generated_at=float(data.get("generated_at", time.time())),
            metadata=dict(data.get("metadata", {})),
            issues=[DriftIssue.from_dict(item) for item in data.get("issues", [])],
        )


class DriftAnalyzer:
    """Analyze runtime persistence for stale, contradictory, or inconsistent state."""

    def analyze(
        self,
        store: Any,
        *,
        session_id: str | None = None,
        stale_after_seconds: float = 7 * 24 * 60 * 60,
        now: float | None = None,
    ) -> DriftReport:
        timestamp = time.time() if now is None else now
        sessions = store.list_sessions()
        if session_id is not None:
            sessions = [session for session in sessions if session.id == session_id]

        issues: list[DriftIssue] = []
        issues.extend(self._planner_issues(store, sessions, timestamp, stale_after_seconds))
        issues.extend(self._mesh_issues(store, sessions))
        issues.extend(self._reinforcement_issues(store))
        issues.extend(self._cycle_issues(store, sessions))

        scope = f"session:{session_id}" if session_id is not None else "runtime"
        return DriftReport.create(
            scope=scope,
            issues=sorted(issues, key=lambda issue: (issue.severity.value, issue.kind, issue.subject)),
            metadata={
                "session_id": session_id,
                "stale_after_seconds": stale_after_seconds,
                "inspected_sessions": len(sessions),
            },
        )

    def _planner_issues(
        self,
        store: Any,
        sessions: list[Any],
        now: float,
        stale_after_seconds: float,
    ) -> list[DriftIssue]:
        issues: list[DriftIssue] = []
        for session in sessions:
            if session.status == "active" and now - session.updated_at > stale_after_seconds:
                issues.append(
                    DriftIssue.create(
                        kind="stale_session",
                        severity=DriftSeverity.WARNING,
                        subject=session.id,
                        detail="Active session has not been updated within the stale workflow threshold.",
                        metadata={"goal": session.goal, "updated_at": session.updated_at},
                    )
                )

            for task in session.planner.tasks.values():
                for dependency_id in task.depends_on:
                    if dependency_id not in session.planner.tasks:
                        issues.append(
                            DriftIssue.create(
                                kind="planner_missing_dependency",
                                severity=DriftSeverity.ERROR,
                                subject=task.id,
                                detail=f"Planner task depends on missing task {dependency_id}.",
                                metadata={"session_id": session.id, "task": task.to_dict()},
                            )
                        )
                if task.status == TaskStatus.BLOCKED:
                    issues.append(
                        DriftIssue.create(
                            kind="blocked_task",
                            severity=DriftSeverity.WARNING,
                            subject=task.id,
                            detail="Planner task is blocked and may need new information or a decision.",
                            metadata={"session_id": session.id, "task": task.to_dict()},
                        )
                    )
                elif task.status == TaskStatus.FAILED:
                    issues.append(
                        DriftIssue.create(
                            kind="failed_task",
                            severity=DriftSeverity.ERROR,
                            subject=task.id,
                            detail="Planner task is failed and should be repaired or superseded.",
                            metadata={"session_id": session.id, "task": task.to_dict()},
                        )
                    )
        return issues

    def _mesh_issues(self, store: Any, sessions: list[Any]) -> list[DriftIssue]:
        issues: list[DriftIssue] = []
        nodes = {node.id: node for node in store.list_mesh_nodes(limit=0)}
        edges = store.list_mesh_edges(limit=0)

        for edge in edges:
            if edge.source_id not in nodes:
                issues.append(
                    DriftIssue.create(
                        kind="mesh_dangling_source",
                        severity=DriftSeverity.ERROR,
                        subject=edge.id,
                        detail=f"Mesh edge source node is missing: {edge.source_id}.",
                        metadata={"edge": edge.to_dict()},
                    )
                )
            if edge.target_id not in nodes:
                issues.append(
                    DriftIssue.create(
                        kind="mesh_dangling_target",
                        severity=DriftSeverity.ERROR,
                        subject=edge.id,
                        detail=f"Mesh edge target node is missing: {edge.target_id}.",
                        metadata={"edge": edge.to_dict()},
                    )
                )

        for session in sessions:
            session_node_id = mesh_node_id("session", session.id)
            if session_node_id not in nodes:
                issues.append(
                    DriftIssue.create(
                        kind="missing_session_mesh_node",
                        severity=DriftSeverity.WARNING,
                        subject=session.id,
                        detail="Session is persisted without a corresponding memory mesh node.",
                        metadata={"goal": session.goal},
                    )
                )
            for task in session.planner.tasks.values():
                task_node_id = mesh_node_id("task", task.id)
                if task_node_id not in nodes:
                    issues.append(
                        DriftIssue.create(
                            kind="missing_task_mesh_node",
                            severity=DriftSeverity.WARNING,
                            subject=task.id,
                            detail="Planner task is persisted without a corresponding memory mesh node.",
                            metadata={"session_id": session.id, "task": task.to_dict()},
                        )
                    )
        return issues

    def _reinforcement_issues(self, store: Any) -> list[DriftIssue]:
        issues: list[DriftIssue] = []
        nodes = {node.id for node in store.list_mesh_nodes(limit=0)}
        for state in store.list_reinforcements(limit=0):
            memory_node_id = mesh_node_id("memory", state.memory_id)
            if memory_node_id not in nodes:
                issues.append(
                    DriftIssue.create(
                        kind="reinforcement_missing_memory_node",
                        severity=DriftSeverity.WARNING,
                        subject=state.memory_id,
                        detail="Reinforcement state references a memory with no memory mesh node.",
                        metadata={"reinforcement": state.to_dict()},
                    )
                )
            if state.contradictions:
                issues.append(
                    DriftIssue.create(
                        kind="contradicted_memory",
                        severity=DriftSeverity.ERROR,
                        subject=state.memory_id,
                        detail="Memory has contradiction feedback and should be checked before reuse.",
                        metadata={"reinforcement": state.to_dict()},
                    )
                )
            elif state.last_outcome == ActivationOutcome.STALE or state.stale:
                issues.append(
                    DriftIssue.create(
                        kind="stale_memory",
                        severity=DriftSeverity.WARNING,
                        subject=state.memory_id,
                        detail="Memory has stale feedback and may need verification before reuse.",
                        metadata={"reinforcement": state.to_dict()},
                    )
                )
            elif state.score < -0.2:
                issues.append(
                    DriftIssue.create(
                        kind="negative_reinforcement",
                        severity=DriftSeverity.WARNING,
                        subject=state.memory_id,
                        detail="Memory has accumulated negative reinforcement.",
                        metadata={"reinforcement": state.to_dict()},
                    )
                )
        return issues

    def _cycle_issues(self, store: Any, sessions: list[Any]) -> list[DriftIssue]:
        issues: list[DriftIssue] = []
        session_ids = {session.id for session in sessions}
        nodes = {node.id for node in store.list_mesh_nodes(limit=0)}
        edge_keys = {
            (edge.source_id, edge.kind, edge.target_id)
            for edge in store.list_mesh_edges(limit=0)
        }
        for session in sessions:
            for cycle in store.list_cycles(session_id=session.id, limit=0):
                cycle_node_id = mesh_node_id("cycle", cycle.id)
                session_node_id = mesh_node_id("session", cycle.session_id)
                if cycle.session_id not in session_ids:
                    issues.append(
                        DriftIssue.create(
                            kind="cycle_unknown_session",
                            severity=DriftSeverity.ERROR,
                            subject=cycle.id,
                            detail="Cycle references a session outside the inspected scope.",
                            metadata={"cycle": cycle.to_dict()},
                        )
                    )
                if cycle_node_id not in nodes:
                    issues.append(
                        DriftIssue.create(
                            kind="missing_cycle_mesh_node",
                            severity=DriftSeverity.WARNING,
                            subject=cycle.id,
                            detail="Cognitive cycle is persisted without a corresponding memory mesh node.",
                            metadata={"cycle": cycle.to_dict()},
                        )
                    )
                if (session_node_id, "ran_cycle", cycle_node_id) not in edge_keys:
                    issues.append(
                        DriftIssue.create(
                            kind="missing_cycle_mesh_edge",
                            severity=DriftSeverity.WARNING,
                            subject=cycle.id,
                            detail="Cognitive cycle is not linked from its session in the memory mesh.",
                            metadata={"cycle": cycle.to_dict()},
                        )
                    )
        return issues


__all__ = [
    "DriftAnalyzer",
    "DriftIssue",
    "DriftReport",
    "DriftSeverity",
]
