"""Local runtime persistence."""

from __future__ import annotations

import json
from pathlib import Path

from mythic.session import CognitiveSession


class JsonRuntimeStore:
    """Small local-first persistence layer for runtime state."""

    def __init__(self, root: str | Path = ".mythic"):
        self.root = Path(root)
        self.sessions_dir = self.root / "sessions"

    def init(self) -> None:
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def save_session(self, session: CognitiveSession) -> None:
        self.init()
        path = self.sessions_dir / f"{session.id}.json"
        path.write_text(json.dumps(session.to_dict(), indent=2, sort_keys=True), encoding="utf-8")

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

