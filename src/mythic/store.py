"""Local runtime persistence."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Protocol

from mythic.cycles import CognitiveCycle, ReflectionRecord
from mythic.events import CognitionEvent
from mythic.session import CognitiveSession


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


class JsonRuntimeStore:
    """Small transparent persistence backend for debugging runtime state."""

    def __init__(self, root: str | Path = ".mythic"):
        self.root = Path(root)
        self.sessions_dir = self.root / "sessions"
        self.events_path = self.root / "events.jsonl"
        self.cycles_path = self.root / "cycles.jsonl"
        self.reflections_path = self.root / "reflections.jsonl"

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

    def list_events(
        self,
        *,
        limit: int = 50,
        session_id: str | None = None,
    ) -> list[CognitionEvent]:
        self.init()
        if not self.events_path.exists():
            return []
        events = [
            CognitionEvent.from_dict(json.loads(line))
            for line in self.events_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if session_id is not None:
            events = [event for event in events if event.session_id == session_id]
        if limit > 0:
            events = events[-limit:]
        return events

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
