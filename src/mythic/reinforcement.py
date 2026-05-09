"""Adaptive reinforcement models for activated memories."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ActivationOutcome(str, Enum):
    """Known outcomes for a memory activation."""

    USEFUL = "useful"
    NEUTRAL = "neutral"
    HARMFUL = "harmful"
    STALE = "stale"
    CONTRADICTED = "contradicted"


OUTCOME_DELTAS: dict[ActivationOutcome, float] = {
    ActivationOutcome.USEFUL: 0.15,
    ActivationOutcome.NEUTRAL: 0.02,
    ActivationOutcome.HARMFUL: -0.18,
    ActivationOutcome.STALE: -0.12,
    ActivationOutcome.CONTRADICTED: -0.25,
}


def clamp_score(value: float) -> float:
    """Keep local reinforcement bounded so retrieval scores still matter."""

    return max(-1.0, min(1.0, value))


@dataclass(frozen=True)
class ActivationFeedback:
    """Runtime feedback about whether an activated memory helped execution."""

    session_id: str
    memory_id: str
    outcome: ActivationOutcome
    signal: float
    cycle_id: str | None = None
    note: str | None = None
    source: str = "runtime"
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: float = field(default_factory=time.time)

    @classmethod
    def create(
        cls,
        *,
        session_id: str,
        memory_id: str,
        outcome: ActivationOutcome | str,
        cycle_id: str | None = None,
        note: str | None = None,
        source: str = "runtime",
        signal: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> "ActivationFeedback":
        parsed_outcome = ActivationOutcome(outcome)
        return cls(
            session_id=session_id,
            memory_id=memory_id,
            cycle_id=cycle_id,
            outcome=parsed_outcome,
            signal=float(signal if signal is not None else OUTCOME_DELTAS[parsed_outcome]),
            note=note,
            source=source,
            metadata=metadata or {},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "cycle_id": self.cycle_id,
            "memory_id": self.memory_id,
            "outcome": self.outcome.value,
            "signal": self.signal,
            "note": self.note,
            "source": self.source,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ActivationFeedback":
        return cls(
            id=data["id"],
            session_id=data["session_id"],
            cycle_id=data.get("cycle_id"),
            memory_id=data["memory_id"],
            outcome=ActivationOutcome(data["outcome"]),
            signal=float(data.get("signal", OUTCOME_DELTAS[ActivationOutcome(data["outcome"])])),
            note=data.get("note"),
            source=data.get("source", "runtime"),
            metadata=dict(data.get("metadata", {})),
            created_at=float(data.get("created_at", time.time())),
        )


@dataclass(frozen=True)
class ReinforcementState:
    """Accumulated local runtime weighting for a memory."""

    memory_id: str
    score: float = 0.0
    uses: int = 0
    successes: int = 0
    failures: int = 0
    contradictions: int = 0
    stale: int = 0
    last_outcome: ActivationOutcome | None = None
    updated_at: float = field(default_factory=time.time)
    decayed_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "score": self.score,
            "uses": self.uses,
            "successes": self.successes,
            "failures": self.failures,
            "contradictions": self.contradictions,
            "stale": self.stale,
            "last_outcome": self.last_outcome.value if self.last_outcome is not None else None,
            "updated_at": self.updated_at,
            "decayed_at": self.decayed_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReinforcementState":
        outcome = data.get("last_outcome")
        return cls(
            memory_id=data["memory_id"],
            score=float(data.get("score", 0.0)),
            uses=int(data.get("uses", 0)),
            successes=int(data.get("successes", 0)),
            failures=int(data.get("failures", 0)),
            contradictions=int(data.get("contradictions", 0)),
            stale=int(data.get("stale", 0)),
            last_outcome=ActivationOutcome(outcome) if outcome else None,
            updated_at=float(data.get("updated_at", time.time())),
            decayed_at=data.get("decayed_at"),
        )


def apply_feedback(
    state: ReinforcementState | None,
    feedback: ActivationFeedback,
) -> ReinforcementState:
    """Apply one feedback record to a memory's reinforcement state."""

    current = state or ReinforcementState(memory_id=feedback.memory_id)
    successes = current.successes
    failures = current.failures
    contradictions = current.contradictions
    stale = current.stale

    if feedback.outcome == ActivationOutcome.USEFUL:
        successes += 1
    elif feedback.outcome in {ActivationOutcome.HARMFUL, ActivationOutcome.CONTRADICTED}:
        failures += 1
    if feedback.outcome == ActivationOutcome.CONTRADICTED:
        contradictions += 1
    if feedback.outcome == ActivationOutcome.STALE:
        stale += 1

    return ReinforcementState(
        memory_id=feedback.memory_id,
        score=clamp_score(current.score + feedback.signal),
        uses=current.uses + 1,
        successes=successes,
        failures=failures,
        contradictions=contradictions,
        stale=stale,
        last_outcome=feedback.outcome,
        updated_at=feedback.created_at,
        decayed_at=current.decayed_at,
    )


def decay_state(state: ReinforcementState, *, rate: float, now: float | None = None) -> ReinforcementState:
    """Decay a memory reinforcement score toward zero."""

    bounded_rate = max(0.0, min(1.0, rate))
    return ReinforcementState(
        memory_id=state.memory_id,
        score=clamp_score(state.score * (1.0 - bounded_rate)),
        uses=state.uses,
        successes=state.successes,
        failures=state.failures,
        contradictions=state.contradictions,
        stale=state.stale,
        last_outcome=state.last_outcome,
        updated_at=state.updated_at,
        decayed_at=now if now is not None else time.time(),
    )


__all__ = [
    "ActivationFeedback",
    "ActivationOutcome",
    "ReinforcementState",
    "apply_feedback",
    "decay_state",
]
