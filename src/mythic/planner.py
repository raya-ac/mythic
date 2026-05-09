"""Persistent planner state primitives."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TaskStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    BLOCKED = "blocked"
    DONE = "done"
    FAILED = "failed"


@dataclass
class TaskNode:
    """A planner task with dependency edges."""

    title: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: TaskStatus = TaskStatus.PENDING
    depends_on: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def set_status(self, status: TaskStatus) -> None:
        self.status = status
        self.updated_at = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "status": self.status.value,
            "depends_on": self.depends_on,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskNode":
        return cls(
            id=data["id"],
            title=data["title"],
            status=TaskStatus(data.get("status", TaskStatus.PENDING)),
            depends_on=list(data.get("depends_on", [])),
            metadata=dict(data.get("metadata", {})),
            created_at=float(data.get("created_at", time.time())),
            updated_at=float(data.get("updated_at", time.time())),
        )


@dataclass
class PlannerState:
    """Addressable task graph for a cognitive session."""

    tasks: dict[str, TaskNode] = field(default_factory=dict)

    def add_task(
        self,
        title: str,
        *,
        depends_on: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TaskNode:
        task = TaskNode(
            title=title,
            depends_on=depends_on or [],
            metadata=metadata or {},
        )
        self.tasks[task.id] = task
        return task

    def set_status(self, task_id: str, status: TaskStatus) -> TaskNode:
        task = self.tasks[task_id]
        task.set_status(status)
        return task

    def ready_tasks(self) -> list[TaskNode]:
        done = {
            task_id
            for task_id, task in self.tasks.items()
            if task.status == TaskStatus.DONE
        }
        return [
            task
            for task in self.tasks.values()
            if task.status == TaskStatus.PENDING
            and all(dep in done for dep in task.depends_on)
        ]

    def to_dict(self) -> dict[str, Any]:
        return {"tasks": [task.to_dict() for task in self.tasks.values()]}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "PlannerState":
        state = cls()
        if not data:
            return state
        for item in data.get("tasks", []):
            task = TaskNode.from_dict(item)
            state.tasks[task.id] = task
        return state

