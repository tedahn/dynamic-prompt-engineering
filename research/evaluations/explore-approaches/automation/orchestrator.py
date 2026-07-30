"""Fail-closed lifecycle state machine backed by the hash-chained event store."""

from __future__ import annotations

from typing import Any

from .core import PipelineError
from .event_store import EventStore


TRANSITIONS: dict[str, set[str]] = {
    "draft": {"frozen"},
    "frozen": {"holdout-ready"},
    "holdout-ready": {"running"},
    "running": {"grading"},
    "grading": {"promotable", "rejected", "inconclusive", "invalid"},
    "promotable": {"awaiting-human-approval"},
    "awaiting-human-approval": {"approved"},
    "approved": {"promoting"},
    "promoting": {"pr-open"},
    "pr-open": {"merged"},
    "merged": {"installing"},
    "installing": {"canary"},
    "canary": {"active", "quarantined"},
    "active": {"quarantined"},
    "quarantined": {"rolled-back"},
    "rolled-back": set(),
    "rejected": set(),
    "inconclusive": set(),
    "invalid": set(),
}


class Lifecycle:
    def __init__(self, store: EventStore, stream: str) -> None:
        self.store = store
        self.stream = stream

    @property
    def current(self) -> dict[str, Any]:
        return self.store.current(self.stream)

    def advance(
        self,
        next_state: str,
        event_type: str,
        payload: dict[str, Any],
        *,
        actor: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        current = self.current
        state = str(current["state"])
        if next_state not in TRANSITIONS.get(state, set()):
            raise PipelineError(f"Illegal lifecycle transition: {state} -> {next_state}")
        return self.store.append(
            self.stream,
            event_type,
            payload,
            actor=actor,
            idempotency_key=idempotency_key,
            expected_version=int(current["version"]),
            next_state=next_state,
        )

    def block(self, reason: str, payload: dict[str, Any] | None = None, *, actor: str = "automation") -> dict[str, Any]:
        current = self.current
        return self.store.append(
            self.stream,
            "BLOCKED",
            {"reason": reason, **(payload or {})},
            actor=actor,
            idempotency_key=f"blocked:{current['version']}:{reason}",
            expected_version=int(current["version"]),
            next_state=str(current["state"]),
        )

    def audit(self) -> dict[str, Any]:
        return self.store.audit(self.stream)
