"""SQLite WAL event store with hash chaining and idempotent appends."""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
from typing import Any
import uuid

from .core import (
    PipelineError,
    canonical_json_bytes,
    ensure_private_directory,
    ensure_private_file,
    iso_now,
    sha256_bytes,
)


class EventStore:
    def __init__(self, path: Path):
        existing = path.exists() or path.is_symlink()
        ensure_private_directory(path.parent, create=True, normalize=not existing)
        if existing:
            ensure_private_file(path)
        self.path = path
        self.connection = sqlite3.connect(path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS streams (
              stream TEXT PRIMARY KEY,
              version INTEGER NOT NULL,
              last_hash TEXT NOT NULL,
              state TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
              event_id TEXT PRIMARY KEY,
              stream TEXT NOT NULL,
              version INTEGER NOT NULL,
              idempotency_key TEXT NOT NULL,
              event_type TEXT NOT NULL,
              actor TEXT NOT NULL,
              occurred_at TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              next_state TEXT NOT NULL,
              previous_hash TEXT NOT NULL,
              event_hash TEXT NOT NULL,
              UNIQUE(stream, version),
              UNIQUE(stream, idempotency_key)
            );
            """
        )
        self.connection.commit()
        self._secure_files(normalize=True)

    def _secure_files(self, *, normalize: bool = False) -> None:
        ensure_private_directory(self.path.parent)
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(f"{self.path}{suffix}")
            if candidate.exists() or candidate.is_symlink():
                ensure_private_file(candidate, normalize=normalize)

    def close(self) -> None:
        self._secure_files()
        self.connection.close()
        self._secure_files(normalize=True)

    def current(self, stream: str) -> dict[str, Any]:
        row = self.connection.execute("SELECT version,last_hash,state FROM streams WHERE stream=?", (stream,)).fetchone()
        if row is None:
            return {"stream": stream, "version": 0, "last_hash": "0" * 64, "state": "draft"}
        return {"stream": stream, "version": row["version"], "last_hash": row["last_hash"], "state": row["state"]}

    def append(
        self,
        stream: str,
        event_type: str,
        payload: dict[str, Any],
        *,
        actor: str,
        idempotency_key: str,
        expected_version: int,
        next_state: str,
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        timestamp = occurred_at or iso_now()
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            duplicate = self.connection.execute(
                "SELECT * FROM events WHERE stream=? AND idempotency_key=?", (stream, idempotency_key)
            ).fetchone()
            if duplicate is not None:
                existing_payload = json.loads(duplicate["payload_json"])
                if duplicate["event_type"] != event_type or duplicate["actor"] != actor or existing_payload != payload:
                    raise PipelineError("Conflicting idempotency-key reuse")
                self.connection.commit()
                self._secure_files(normalize=True)
                return dict(duplicate)
            current = self.current(stream)
            if current["version"] != expected_version:
                raise PipelineError(f"Stream version conflict: expected {expected_version}, found {current['version']}")
            version = expected_version + 1
            event_id = str(uuid.uuid4())
            body = {
                "event_id": event_id,
                "stream": stream,
                "version": version,
                "idempotency_key": idempotency_key,
                "event_type": event_type,
                "actor": actor,
                "occurred_at": timestamp,
                "payload": payload,
                "previous_hash": current["last_hash"],
                "next_state": next_state,
            }
            event_hash = sha256_bytes(canonical_json_bytes(body))
            self.connection.execute(
                "INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    event_id,
                    stream,
                    version,
                    idempotency_key,
                    event_type,
                    actor,
                    timestamp,
                    json.dumps(payload, sort_keys=True),
                    next_state,
                    current["last_hash"],
                    event_hash,
                ),
            )
            self.connection.execute(
                "INSERT INTO streams(stream,version,last_hash,state) VALUES(?,?,?,?) "
                "ON CONFLICT(stream) DO UPDATE SET version=excluded.version,last_hash=excluded.last_hash,state=excluded.state",
                (stream, version, event_hash, next_state),
            )
            self.connection.commit()
            self._secure_files(normalize=True)
            return {**body, "event_hash": event_hash}
        except Exception:
            self.connection.rollback()
            self._secure_files(normalize=True)
            raise

    def events(self, stream: str) -> list[dict[str, Any]]:
        rows = self.connection.execute("SELECT * FROM events WHERE stream=? ORDER BY version", (stream,)).fetchall()
        return [dict(row) for row in rows]

    def audit(self, stream: str) -> dict[str, Any]:
        previous = "0" * 64
        expected_version = 1
        expected_state = "draft"
        errors: list[str] = []
        for row in self.events(stream):
            payload = json.loads(row["payload_json"])
            body = {
                "event_id": row["event_id"],
                "stream": row["stream"],
                "version": row["version"],
                "idempotency_key": row["idempotency_key"],
                "event_type": row["event_type"],
                "actor": row["actor"],
                "occurred_at": row["occurred_at"],
                "payload": payload,
                "previous_hash": row["previous_hash"],
                "next_state": row["next_state"],
            }
            if row["version"] != expected_version:
                errors.append(f"version_gap:{row['version']}")
            if row["previous_hash"] != previous:
                errors.append(f"previous_hash_mismatch:{row['version']}")
            computed = sha256_bytes(canonical_json_bytes(body))
            if computed != row["event_hash"]:
                errors.append(f"event_hash_mismatch:{row['version']}")
            previous = row["event_hash"]
            expected_state = row["next_state"]
            expected_version += 1
        current = self.current(stream)
        if current["last_hash"] != previous:
            errors.append("stream_head_mismatch")
        if current["version"] != expected_version - 1:
            errors.append("stream_version_mismatch")
        if current["state"] != expected_state:
            errors.append("stream_state_mismatch")
        return {"ok": not errors, "errors": errors, "event_count": expected_version - 1, "current": current}
