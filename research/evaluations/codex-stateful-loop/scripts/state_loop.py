#!/usr/bin/env python3
"""Event-sourced harness for governed stateful Codex evaluation.

The harness is standard-library only. It never calls a model. A separate guarded
adapter executes prepared cells after a scoped external approval exists.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import random
import re
import sqlite3
import statistics
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


LAB_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = LAB_ROOT.parents[2]
CONFIG_PATH = LAB_ROOT / "config" / "loop-v1.json"
SEED_STATE_PATH = LAB_ROOT / "state" / "seed-state-v1.json"
DEV_EPISODES_PATH = LAB_ROOT / "fixtures" / "episodes-dev-v1.jsonl"
SUBJECT_PROMPT_PATH = LAB_ROOT / "prompts" / "subject.md"
GENESIS_HASH = "0" * 64
SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?i)\b(?:password|passwd|api[_-]?key|access[_-]?token)\s*[:=]\s*\S+"),
)
ALLOWED_ENTRY_KINDS = {"fact", "preference", "procedure", "lesson", "constraint"}
ALLOWED_EVIDENCE_STATES = {
    "Grounded fact",
    "Corroborated",
    "Experimental",
    "Looks believable",
    "Forecast/opinion",
    "Unknown",
}
ALLOWED_ACTORS = {"human", "subject", "optimizer", "grader", "adjudicator", "harness"}


class StateLoopError(RuntimeError):
    """A controlled harness failure."""


class ConflictError(StateLoopError):
    """An optimistic concurrency or idempotency conflict."""


@dataclass(frozen=True)
class ArtifactRef:
    sha256: str
    size: int
    relative_path: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json(value).encode("utf-8"))


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise StateLoopError(f"Expected JSON object: {path}")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise StateLoopError(f"Expected object at {path}:{number}")
        rows.append(value)
    return rows


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def connect(instance: Path) -> sqlite3.Connection:
    database = instance / "state.db"
    if not database.exists():
        raise StateLoopError(f"Instance is not initialized: {instance}")
    connection = sqlite3.connect(database, timeout=30, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = FULL")
    return connection


def initialize_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE streams (
            stream_id TEXT PRIMARY KEY,
            version INTEGER NOT NULL,
            tail_hash TEXT NOT NULL
        );
        CREATE TABLE artifacts (
            sha256 TEXT PRIMARY KEY,
            size INTEGER NOT NULL,
            media_type TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE events (
            event_id TEXT PRIMARY KEY,
            stream_id TEXT NOT NULL,
            stream_version INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            actor_type TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            session_id TEXT,
            correlation_id TEXT NOT NULL,
            causation_id TEXT,
            iteration_id TEXT,
            run_id TEXT,
            candidate_id TEXT,
            base_snapshot_id TEXT,
            surface_snapshot_id TEXT,
            policy_snapshot_sha256 TEXT,
            payload_json TEXT NOT NULL,
            input_refs_json TEXT NOT NULL,
            output_refs_json TEXT NOT NULL,
            previous_event_hash TEXT NOT NULL,
            event_hash TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            UNIQUE(stream_id, stream_version)
        );
        CREATE TABLE snapshots (
            snapshot_id TEXT PRIMARY KEY,
            parent_snapshot_id TEXT,
            revision INTEGER NOT NULL,
            status TEXT NOT NULL,
            owner TEXT NOT NULL,
            artifact_sha256 TEXT NOT NULL REFERENCES artifacts(sha256),
            created_event_id TEXT NOT NULL REFERENCES events(event_id),
            created_at TEXT NOT NULL,
            rollback_snapshot_id TEXT
        );
        CREATE TABLE active_state (
            singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
            snapshot_id TEXT NOT NULL REFERENCES snapshots(snapshot_id),
            version INTEGER NOT NULL
        );
        CREATE TABLE proposals (
            proposal_id TEXT PRIMARY KEY,
            base_snapshot_id TEXT NOT NULL REFERENCES snapshots(snapshot_id),
            candidate_snapshot_id TEXT NOT NULL REFERENCES snapshots(snapshot_id),
            artifact_sha256 TEXT NOT NULL REFERENCES artifacts(sha256),
            status TEXT NOT NULL,
            created_event_id TEXT NOT NULL REFERENCES events(event_id)
        );
        CREATE TABLE epochs (
            epoch_id TEXT PRIMARY KEY,
            stage TEXT NOT NULL,
            baseline_snapshot_id TEXT NOT NULL REFERENCES snapshots(snapshot_id),
            candidate_snapshot_id TEXT NOT NULL REFERENCES snapshots(snapshot_id),
            plan_sha256 TEXT NOT NULL REFERENCES artifacts(sha256),
            blind_plan_sha256 TEXT NOT NULL REFERENCES artifacts(sha256),
            status TEXT NOT NULL,
            created_event_id TEXT NOT NULL REFERENCES events(event_id),
            summary_sha256 TEXT
        );
        CREATE TABLE cells (
            cell_id TEXT PRIMARY KEY,
            epoch_id TEXT NOT NULL REFERENCES epochs(epoch_id),
            anonymous_id TEXT NOT NULL,
            episode_id TEXT NOT NULL,
            family TEXT NOT NULL,
            condition_id TEXT NOT NULL,
            trial INTEGER NOT NULL,
            ordinal INTEGER NOT NULL,
            packet_sha256 TEXT NOT NULL REFERENCES artifacts(sha256),
            status TEXT NOT NULL,
            result_sha256 TEXT,
            UNIQUE(epoch_id, episode_id, condition_id, trial)
        );
        CREATE TABLE evaluations (
            record_id TEXT PRIMARY KEY,
            cell_id TEXT NOT NULL REFERENCES cells(cell_id),
            artifact_sha256 TEXT NOT NULL REFERENCES artifacts(sha256),
            record_status TEXT NOT NULL,
            created_event_id TEXT NOT NULL REFERENCES events(event_id)
        );
        """
    )


def put_artifact(
    connection: sqlite3.Connection,
    instance: Path,
    content: bytes,
    media_type: str,
) -> ArtifactRef:
    digest = sha256_bytes(content)
    relative = Path("artifacts") / "sha256" / digest[:2] / digest
    destination = instance / relative
    if destination.exists():
        if sha256_bytes(destination.read_bytes()) != digest:
            raise StateLoopError(f"Artifact collision or corruption: {destination}")
    else:
        atomic_write(destination, content)
    connection.execute(
        "INSERT OR IGNORE INTO artifacts(sha256,size,media_type,relative_path,created_at) VALUES(?,?,?,?,?)",
        (digest, len(content), media_type, str(relative), utc_now()),
    )
    return ArtifactRef(digest, len(content), str(relative))


def put_json_artifact(
    connection: sqlite3.Connection, instance: Path, value: Any, media_type: str = "application/json"
) -> ArtifactRef:
    return put_artifact(connection, instance, (canonical_json(value) + "\n").encode("utf-8"), media_type)


def read_artifact(connection: sqlite3.Connection, instance: Path, digest: str) -> bytes:
    row = connection.execute("SELECT relative_path FROM artifacts WHERE sha256 = ?", (digest,)).fetchone()
    if row is None:
        raise StateLoopError(f"Unknown artifact: {digest}")
    content = (instance / row["relative_path"]).read_bytes()
    if sha256_bytes(content) != digest:
        raise StateLoopError(f"Artifact hash mismatch: {digest}")
    return content


def read_json_artifact(connection: sqlite3.Connection, instance: Path, digest: str) -> dict[str, Any]:
    value = json.loads(read_artifact(connection, instance, digest))
    if not isinstance(value, dict):
        raise StateLoopError(f"Artifact is not an object: {digest}")
    return value


def _event_fingerprint(
    stream_id: str,
    event_type: str,
    actor_type: str,
    actor_id: str,
    payload: dict[str, Any],
    input_refs: Sequence[str],
    output_refs: Sequence[str],
) -> str:
    return sha256_json(
        {
            "stream_id": stream_id,
            "event_type": event_type,
            "actor_type": actor_type,
            "actor_id": actor_id,
            "payload": payload,
            "input_refs": list(input_refs),
            "output_refs": list(output_refs),
        }
    )


def append_event_tx(
    connection: sqlite3.Connection,
    *,
    stream_id: str,
    event_type: str,
    actor_type: str,
    actor_id: str,
    payload: dict[str, Any],
    idempotency_key: str,
    expected_stream_version: int | None = None,
    input_refs: Sequence[str] = (),
    output_refs: Sequence[str] = (),
    correlation_id: str | None = None,
    causation_id: str | None = None,
    iteration_id: str | None = None,
    run_id: str | None = None,
    candidate_id: str | None = None,
    base_snapshot_id: str | None = None,
    surface_snapshot_id: str | None = None,
    policy_snapshot_sha256: str | None = None,
    session_id: str | None = None,
    occurred_at: str | None = None,
    event_id: str | None = None,
) -> dict[str, Any]:
    if actor_type not in ALLOWED_ACTORS:
        raise StateLoopError(f"Unknown actor type: {actor_type}")
    existing = connection.execute(
        "SELECT * FROM events WHERE idempotency_key = ?", (idempotency_key,)
    ).fetchone()
    fingerprint = _event_fingerprint(
        stream_id, event_type, actor_type, actor_id, payload, input_refs, output_refs
    )
    if existing is not None:
        prior_fingerprint = _event_fingerprint(
            existing["stream_id"],
            existing["event_type"],
            existing["actor_type"],
            existing["actor_id"],
            json.loads(existing["payload_json"]),
            json.loads(existing["input_refs_json"]),
            json.loads(existing["output_refs_json"]),
        )
        if prior_fingerprint != fingerprint:
            raise ConflictError(f"Conflicting reuse of idempotency key: {idempotency_key}")
        return event_row_to_dict(existing)

    stream = connection.execute("SELECT version,tail_hash FROM streams WHERE stream_id = ?", (stream_id,)).fetchone()
    version = 0 if stream is None else int(stream["version"])
    previous_hash = GENESIS_HASH if stream is None else str(stream["tail_hash"])
    if expected_stream_version is not None and version != expected_stream_version:
        raise ConflictError(
            f"Stream {stream_id} expected version {expected_stream_version}, found {version}"
        )
    next_version = version + 1
    recorded_at = utc_now()
    event = {
        "event_id": event_id or f"EVT-{uuid.uuid4().hex.upper()}",
        "stream_id": stream_id,
        "stream_version": next_version,
        "event_type": event_type,
        "occurred_at": occurred_at or recorded_at,
        "recorded_at": recorded_at,
        "actor_type": actor_type,
        "actor_id": actor_id,
        "session_id": session_id,
        "correlation_id": correlation_id or f"CORR-{uuid.uuid4().hex.upper()}",
        "causation_id": causation_id,
        "iteration_id": iteration_id,
        "run_id": run_id,
        "candidate_id": candidate_id,
        "base_snapshot_id": base_snapshot_id,
        "surface_snapshot_id": surface_snapshot_id,
        "policy_snapshot_sha256": policy_snapshot_sha256,
        "payload": payload,
        "input_refs": list(input_refs),
        "output_refs": list(output_refs),
        "previous_event_hash": previous_hash,
        "idempotency_key": idempotency_key,
    }
    event_hash = sha256_bytes((previous_hash + canonical_json(event)).encode("utf-8"))
    event["event_hash"] = event_hash
    connection.execute(
        """
        INSERT INTO events(
            event_id,stream_id,stream_version,event_type,occurred_at,recorded_at,
            actor_type,actor_id,session_id,correlation_id,causation_id,iteration_id,
            run_id,candidate_id,base_snapshot_id,surface_snapshot_id,policy_snapshot_sha256,
            payload_json,input_refs_json,output_refs_json,previous_event_hash,event_hash,idempotency_key
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            event["event_id"], stream_id, next_version, event_type, event["occurred_at"],
            recorded_at, actor_type, actor_id, session_id, event["correlation_id"],
            causation_id, iteration_id, run_id, candidate_id, base_snapshot_id,
            surface_snapshot_id, policy_snapshot_sha256, canonical_json(payload),
            canonical_json(list(input_refs)), canonical_json(list(output_refs)),
            previous_hash, event_hash, idempotency_key,
        ),
    )
    connection.execute(
        "INSERT INTO streams(stream_id,version,tail_hash) VALUES(?,?,?) "
        "ON CONFLICT(stream_id) DO UPDATE SET version=excluded.version,tail_hash=excluded.tail_hash",
        (stream_id, next_version, event_hash),
    )
    return event


def append_event(connection: sqlite3.Connection, **kwargs: Any) -> dict[str, Any]:
    connection.execute("BEGIN IMMEDIATE")
    try:
        event = append_event_tx(connection, **kwargs)
        connection.commit()
        return event
    except Exception:
        connection.rollback()
        raise


def event_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "event_id": row["event_id"],
        "stream_id": row["stream_id"],
        "stream_version": row["stream_version"],
        "event_type": row["event_type"],
        "occurred_at": row["occurred_at"],
        "recorded_at": row["recorded_at"],
        "actor_type": row["actor_type"],
        "actor_id": row["actor_id"],
        "session_id": row["session_id"],
        "correlation_id": row["correlation_id"],
        "causation_id": row["causation_id"],
        "iteration_id": row["iteration_id"],
        "run_id": row["run_id"],
        "candidate_id": row["candidate_id"],
        "base_snapshot_id": row["base_snapshot_id"],
        "surface_snapshot_id": row["surface_snapshot_id"],
        "policy_snapshot_sha256": row["policy_snapshot_sha256"],
        "payload": json.loads(row["payload_json"]),
        "input_refs": json.loads(row["input_refs_json"]),
        "output_refs": json.loads(row["output_refs_json"]),
        "previous_event_hash": row["previous_event_hash"],
        "event_hash": row["event_hash"],
        "idempotency_key": row["idempotency_key"],
    }


def initialize_instance(instance: Path) -> dict[str, Any]:
    if instance.exists() and any(instance.iterdir()):
        raise StateLoopError(f"Refusing to initialize non-empty instance: {instance}")
    instance.mkdir(parents=True, exist_ok=True)
    database = instance / "state.db"
    connection = sqlite3.connect(database, timeout=30, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = FULL")
    initialize_schema(connection)
    config = load_json(CONFIG_PATH)
    seed = load_json(SEED_STATE_PATH)
    validate_state(seed, allow_empty=True)
    connection.execute("BEGIN IMMEDIATE")
    try:
        config_ref = put_json_artifact(connection, instance, config)
        seed_event_id = f"EVT-{uuid.uuid4().hex.upper()}"
        seed["created_by_event"] = seed_event_id
        seed_ref = put_json_artifact(connection, instance, seed)
        event = append_event_tx(
            connection,
            stream_id="system",
            event_type="instance_initialized",
            actor_type="harness",
            actor_id="state-loop-v1",
            payload={
                "process_id": config["process_id"],
                "evidence_state": config["evidence_state"],
                "live_execution_authorized": config["live_execution"]["authorized"],
            },
            idempotency_key="instance:init",
            input_refs=(config_ref.sha256,),
            output_refs=(seed_ref.sha256,),
            event_id=seed_event_id,
            policy_snapshot_sha256=config_ref.sha256,
        )
        connection.execute(
            "INSERT INTO snapshots(snapshot_id,parent_snapshot_id,revision,status,owner,artifact_sha256,created_event_id,created_at,rollback_snapshot_id) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                seed["snapshot_id"], None, seed["revision"], seed["status"], seed["owner"],
                seed_ref.sha256, event["event_id"], seed["created_at"], None,
            ),
        )
        connection.execute(
            "INSERT INTO active_state(singleton,snapshot_id,version) VALUES(1,?,1)",
            (seed["snapshot_id"],),
        )
        for key, value in {
            "process_id": config["process_id"],
            "config_sha256": config_ref.sha256,
            "seed_sha256": seed_ref.sha256,
            "created_at": utc_now(),
        }.items():
            connection.execute("INSERT INTO metadata(key,value) VALUES(?,?)", (key, value))
        connection.commit()
    except Exception:
        connection.rollback()
        connection.close()
        raise
    export_events(connection, instance)
    result = {
        "instance": str(instance),
        "active_snapshot_id": seed["snapshot_id"],
        "config_sha256": config_ref.sha256,
        "event_id": event["event_id"],
    }
    connection.close()
    return result


def export_events(connection: sqlite3.Connection, instance: Path) -> Path:
    rows = connection.execute("SELECT * FROM events ORDER BY recorded_at,event_id").fetchall()
    content = "".join(canonical_json(event_row_to_dict(row)) + "\n" for row in rows)
    destination = instance / "exports" / "events.jsonl"
    atomic_write(destination, content.encode("utf-8"))
    return destination


def get_snapshot(connection: sqlite3.Connection, instance: Path, snapshot_id: str) -> dict[str, Any]:
    row = connection.execute("SELECT artifact_sha256 FROM snapshots WHERE snapshot_id = ?", (snapshot_id,)).fetchone()
    if row is None:
        raise StateLoopError(f"Unknown context snapshot: {snapshot_id}")
    return read_json_artifact(connection, instance, row["artifact_sha256"])


def get_active_snapshot_id(connection: sqlite3.Connection) -> tuple[str, int]:
    row = connection.execute("SELECT snapshot_id,version FROM active_state WHERE singleton = 1").fetchone()
    if row is None:
        raise StateLoopError("Active state pointer is missing")
    return str(row["snapshot_id"]), int(row["version"])


def contains_secret(value: str) -> bool:
    return any(pattern.search(value) for pattern in SECRET_PATTERNS)


def validate_entry(entry: dict[str, Any]) -> None:
    required = {
        "entry_id", "kind", "content", "scope", "source_event_ids", "evidence_state",
        "confidence", "priority", "sensitivity", "allowed_surfaces", "authority_effect",
        "owner", "valid_from", "expires_at", "refresh_trigger", "status", "supersedes",
    }
    missing = required - set(entry)
    if missing:
        raise StateLoopError(f"Context entry missing fields: {sorted(missing)}")
    if entry["kind"] not in ALLOWED_ENTRY_KINDS:
        raise StateLoopError(f"Unknown entry kind: {entry['kind']}")
    if not isinstance(entry["content"], str) or not entry["content"].strip():
        raise StateLoopError("Context entry content is empty")
    if len(entry["content"]) > 2000:
        raise StateLoopError("Context entry exceeds 2000 characters")
    if contains_secret(entry["content"]):
        raise StateLoopError("Context entry resembles credential or secret material")
    if entry["authority_effect"] != "none":
        raise StateLoopError("Agent-proposed context cannot change authority")
    if entry["sensitivity"] not in {"public", "internal"}:
        raise StateLoopError("Restricted content cannot enter durable agent context")
    if entry["evidence_state"] not in ALLOWED_EVIDENCE_STATES:
        raise StateLoopError(f"Unknown evidence state: {entry['evidence_state']}")
    confidence = entry["confidence"]
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
        raise StateLoopError("Context confidence must be between 0 and 1")
    priority = entry["priority"]
    if not isinstance(priority, int) or isinstance(priority, bool) or not 0 <= priority <= 100:
        raise StateLoopError("Context priority must be an integer from 0 to 100")
    scope = entry["scope"]
    if not isinstance(scope, dict) or not scope.get("domains") or "task_tags" not in scope:
        raise StateLoopError("Context entry needs domain and task-tag scope")
    if not entry["source_event_ids"]:
        raise StateLoopError("Context entry needs provenance events")
    if not entry["allowed_surfaces"]:
        raise StateLoopError("Context entry needs allowed surfaces")
    if entry["status"] not in {"active", "superseded", "retired"}:
        raise StateLoopError(f"Unknown entry status: {entry['status']}")
    parse_time(entry["valid_from"])
    if entry["expires_at"] is not None:
        parse_time(entry["expires_at"])
    if "volatile" in scope.get("task_tags", []) and not (
        entry["expires_at"] or entry["refresh_trigger"]
    ):
        raise StateLoopError("Volatile context needs expiry or a refresh trigger")


def validate_state(state: dict[str, Any], *, allow_empty: bool = False) -> None:
    required = {
        "schema_version", "snapshot_id", "parent_snapshot_id", "revision", "status",
        "owner", "created_at", "created_by_event", "policy_version", "rollback_snapshot_id", "entries",
    }
    missing = required - set(state)
    if missing:
        raise StateLoopError(f"Context state missing fields: {sorted(missing)}")
    if not isinstance(state["entries"], list):
        raise StateLoopError("Context entries must be a list")
    if not allow_empty and not state["entries"]:
        raise StateLoopError("Candidate state must contain at least one entry")
    seen_ids: set[str] = set()
    seen_active_content: set[tuple[str, str]] = set()
    for entry in state["entries"]:
        validate_entry(entry)
        if entry["entry_id"] in seen_ids:
            raise StateLoopError(f"Duplicate entry ID: {entry['entry_id']}")
        seen_ids.add(entry["entry_id"])
        signature = (entry["content"].strip().lower(), canonical_json(entry["scope"]))
        if entry["status"] == "active" and signature in seen_active_content:
            raise StateLoopError("Duplicate active context content and scope")
        if entry["status"] == "active":
            seen_active_content.add(signature)


def register_observations(
    connection: sqlite3.Connection, instance: Path, observations: Iterable[dict[str, Any]]
) -> list[str]:
    event_ids: list[str] = []
    for observation in observations:
        required = {"observation_id", "episode_id", "split", "actor_type", "payload"}
        missing = required - set(observation)
        if missing:
            raise StateLoopError(f"Observation missing fields: {sorted(missing)}")
        if observation["split"] != "dev":
            raise StateLoopError("Fresh holdout observations cannot enter the optimizer-visible store")
        payload = {
            "observation_id": observation["observation_id"],
            "episode_id": observation["episode_id"],
            "split": observation["split"],
            "data": observation["payload"],
        }
        event = append_event(
            connection,
            stream_id=f"episode:{observation['episode_id']}",
            event_type="development_observation_recorded",
            actor_type=observation["actor_type"],
            actor_id=observation.get("actor_id", observation["actor_type"]),
            payload=payload,
            idempotency_key=f"observation:{observation['observation_id']}",
        )
        event_ids.append(event["event_id"])
    export_events(connection, instance)
    return event_ids


def _source_event(connection: sqlite3.Connection, event_id: str) -> sqlite3.Row:
    row = connection.execute("SELECT * FROM events WHERE event_id = ?", (event_id,)).fetchone()
    if row is None:
        raise StateLoopError(f"Unknown source event: {event_id}")
    payload = json.loads(row["payload_json"])
    if payload.get("split") != "dev":
        raise StateLoopError(f"Only development events may support a proposal: {event_id}")
    return row


def apply_proposal(
    connection: sqlite3.Connection, instance: Path, proposal: dict[str, Any]
) -> dict[str, Any]:
    required = {
        "schema_version", "proposal_id", "base_snapshot_id", "created_by", "created_at",
        "source_event_ids", "hypothesis", "changed_mechanism", "predicted_benefit",
        "predicted_regressions", "counterexamples", "operations",
    }
    missing = required - set(proposal)
    if missing:
        raise StateLoopError(f"Proposal missing fields: {sorted(missing)}")
    if not proposal["operations"]:
        raise StateLoopError("Proposal needs at least one operation")
    if connection.execute(
        "SELECT 1 FROM proposals WHERE proposal_id = ?", (proposal["proposal_id"],)
    ).fetchone():
        raise ConflictError(f"Proposal already exists: {proposal['proposal_id']}")
    source_ids = set(proposal["source_event_ids"])
    if not source_ids:
        raise StateLoopError("Proposal needs development provenance")
    for event_id in source_ids:
        _source_event(connection, event_id)

    base = get_snapshot(connection, instance, proposal["base_snapshot_id"])
    candidate = copy.deepcopy(base)
    entries = candidate["entries"]
    by_id = {entry["entry_id"]: entry for entry in entries}
    for operation in proposal["operations"]:
        op = operation.get("op")
        if op == "add":
            entry = copy.deepcopy(operation["entry"])
            validate_entry(entry)
            if not set(entry["source_event_ids"]).issubset(source_ids):
                raise StateLoopError("Entry provenance must be included in proposal source events")
            if entry["entry_id"] in by_id:
                raise ConflictError(f"Entry already exists: {entry['entry_id']}")
            entries.append(entry)
            by_id[entry["entry_id"]] = entry
        elif op == "supersede":
            target = by_id.get(operation.get("target_entry_id"))
            if target is None or target["status"] != "active":
                raise StateLoopError("Supersede target must be an active entry")
            entry = copy.deepcopy(operation["entry"])
            validate_entry(entry)
            if not set(entry["source_event_ids"]).issubset(source_ids):
                raise StateLoopError("Entry provenance must be included in proposal source events")
            if entry["entry_id"] in by_id:
                raise ConflictError(f"Entry already exists: {entry['entry_id']}")
            target["status"] = "superseded"
            entry["supersedes"] = sorted(set(entry.get("supersedes", [])) | {target["entry_id"]})
            entries.append(entry)
            by_id[entry["entry_id"]] = entry
        elif op == "retire":
            target = by_id.get(operation.get("target_entry_id"))
            if target is None or target["status"] != "active":
                raise StateLoopError("Retire target must be an active entry")
            target["status"] = "retired"
        else:
            raise StateLoopError(f"Unknown proposal operation: {op}")

    proposal_digest = sha256_json(proposal)
    candidate_id = f"CTX-STATE-CAND-{proposal_digest[:12].upper()}"
    event_id = f"EVT-{uuid.uuid4().hex.upper()}"
    candidate.update(
        {
            "snapshot_id": candidate_id,
            "parent_snapshot_id": base["snapshot_id"],
            "revision": int(base["revision"]) + 1,
            "status": "candidate",
            "created_at": utc_now(),
            "created_by_event": event_id,
            "rollback_snapshot_id": base["snapshot_id"],
        }
    )
    validate_state(candidate)
    connection.execute("BEGIN IMMEDIATE")
    try:
        proposal_ref = put_json_artifact(connection, instance, proposal)
        candidate_ref = put_json_artifact(connection, instance, candidate)
        event = append_event_tx(
            connection,
            stream_id=f"state:{base['snapshot_id']}",
            event_type="context_candidate_proposed",
            actor_type="optimizer",
            actor_id=proposal["created_by"],
            payload={
                "proposal_id": proposal["proposal_id"],
                "candidate_snapshot_id": candidate_id,
                "changed_mechanism": proposal["changed_mechanism"],
                "source_event_ids": sorted(source_ids),
            },
            idempotency_key=f"proposal:{proposal['proposal_id']}",
            input_refs=(proposal_ref.sha256,),
            output_refs=(candidate_ref.sha256,),
            candidate_id=candidate_id,
            base_snapshot_id=base["snapshot_id"],
            event_id=event_id,
        )
        connection.execute(
            "INSERT INTO snapshots(snapshot_id,parent_snapshot_id,revision,status,owner,artifact_sha256,created_event_id,created_at,rollback_snapshot_id) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                candidate_id, base["snapshot_id"], candidate["revision"], "candidate",
                candidate["owner"], candidate_ref.sha256, event["event_id"], candidate["created_at"],
                base["snapshot_id"],
            ),
        )
        connection.execute(
            "INSERT INTO proposals(proposal_id,base_snapshot_id,candidate_snapshot_id,artifact_sha256,status,created_event_id) VALUES(?,?,?,?,?,?)",
            (
                proposal["proposal_id"], base["snapshot_id"], candidate_id,
                proposal_ref.sha256, "candidate", event["event_id"],
            ),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    export_events(connection, instance)
    return {"proposal_id": proposal["proposal_id"], "candidate_snapshot_id": candidate_id}


def _entry_match(entry: dict[str, Any], task: dict[str, Any], now: datetime) -> tuple[bool, str, tuple[Any, ...]]:
    if entry["status"] != "active":
        return False, f"status:{entry['status']}", ()
    if entry["expires_at"] and parse_time(entry["expires_at"]) <= now:
        return False, "expired", ()
    if entry["confidence"] < 0.5:
        return False, "below-confidence-floor", ()
    surface = task.get("surface", "codex")
    if "*" not in entry["allowed_surfaces"] and surface not in entry["allowed_surfaces"]:
        return False, "surface-mismatch", ()
    domains = set(entry["scope"]["domains"])
    domain = task.get("domain", "")
    if "*" not in domains and domain not in domains:
        return False, "domain-mismatch", ()
    task_tags = set(task.get("tags", []))
    entry_tags = set(entry["scope"].get("task_tags", []))
    if entry_tags and not entry_tags.intersection(task_tags):
        return False, "tag-mismatch", ()
    domain_specificity = 2 if domain in domains else 1
    tag_overlap = len(entry_tags.intersection(task_tags))
    valid_from = parse_time(entry["valid_from"]).timestamp()
    rank = (
        domain_specificity,
        tag_overlap,
        int(entry["priority"]),
        float(entry["confidence"]),
        valid_from,
        entry["entry_id"],
    )
    return True, "eligible", rank


def compile_context(
    connection: sqlite3.Connection,
    instance: Path,
    snapshot_id: str,
    task: dict[str, Any],
    *,
    condition_id: str = "B3_RETRIEVAL_ONLY",
    log_event: bool = True,
) -> tuple[dict[str, Any], ArtifactRef]:
    config = load_json(CONFIG_PATH)
    state = get_snapshot(connection, instance, snapshot_id)
    now = parse_time(task.get("now", utc_now()))
    mode = next(
        (item["context_mode"] for item in config["conditions"] if item["condition_id"] == condition_id),
        None,
    )
    if mode is None:
        raise StateLoopError(f"Unknown condition: {condition_id}")
    included: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    excluded: list[dict[str, str]] = []
    if mode == "none":
        excluded = [{"entry_id": entry["entry_id"], "reason": "condition-no-context"} for entry in state["entries"]]
    elif mode in {"full-frozen", "raw-history"}:
        for entry in state["entries"]:
            if entry["status"] == "active":
                included.append(((0,), entry))
            else:
                excluded.append({"entry_id": entry["entry_id"], "reason": f"status:{entry['status']}"})
    else:
        for entry in state["entries"]:
            eligible, reason, rank = _entry_match(entry, task, now)
            if eligible:
                included.append((rank, entry))
            else:
                excluded.append({"entry_id": entry["entry_id"], "reason": reason})
        included.sort(key=lambda item: item[0], reverse=True)

    limits = config["context_selection"]
    selected: list[dict[str, Any]] = []
    used_chars = 0
    for _, entry in included:
        size = len(entry["content"])
        if len(selected) >= limits["max_entries"]:
            excluded.append({"entry_id": entry["entry_id"], "reason": "entry-budget"})
            continue
        if used_chars + size > limits["max_chars"]:
            excluded.append({"entry_id": entry["entry_id"], "reason": "character-budget"})
            continue
        selected.append(
            {
                "entry_id": entry["entry_id"],
                "kind": entry["kind"],
                "content": entry["content"],
                "scope": entry["scope"],
                "evidence_state": entry["evidence_state"],
                "source_event_ids": entry["source_event_ids"],
            }
        )
        used_chars += size

    pack = {
        "schema_version": "1.0",
        "task_id": task["task_id"],
        "snapshot_id": snapshot_id,
        "condition_id": condition_id,
        "compiled_at": utc_now(),
        "immutable_rules": config["immutable_rules"],
        "entries": selected,
        "trace": {
            "included_entry_ids": [entry["entry_id"] for entry in selected],
            "excluded": sorted(excluded, key=lambda item: item["entry_id"]),
            "entry_count": len(selected),
            "content_chars": used_chars,
            "max_entries": limits["max_entries"],
            "max_chars": limits["max_chars"],
        },
    }
    pack_ref = put_json_artifact(connection, instance, pack)
    if log_event:
        append_event(
            connection,
            stream_id=f"task:{task['task_id']}",
            event_type="context_pack_compiled",
            actor_type="harness",
            actor_id="context-compiler-v1",
            payload={
                "task_id": task["task_id"],
                "snapshot_id": snapshot_id,
                "condition_id": condition_id,
                "included_entry_ids": pack["trace"]["included_entry_ids"],
                "excluded": pack["trace"]["excluded"],
                "content_chars": used_chars,
            },
            idempotency_key=f"context:{task['task_id']}:{snapshot_id}:{condition_id}:{pack_ref.sha256}",
            output_refs=(pack_ref.sha256,),
            base_snapshot_id=snapshot_id,
        )
        export_events(connection, instance)
    return pack, pack_ref


def _condition_instruction(condition_id: str) -> str:
    return {
        "B0_STATELESS_RAW": "Use no persistent context and emit no durable-state observations.",
        "B1_FROZEN_CONTEXT": "Use the supplied frozen context as a fixed packet; do not retrieve or update it.",
        "B2_APPEND_ONLY": "Use the supplied raw prior history; append observations but do not curate or supersede.",
        "B3_RETRIEVAL_ONLY": "Use the retrieved accepted context; do not propose updates.",
        "B4_HUMAN_MAINTAINED": "Use the blinded human-maintained context supplied for this episode.",
        "C1_GATED_EVOLVING": "Use the retrieved candidate context and emit observations for a later gated optimizer; do not edit state directly.",
    }[condition_id]


def create_plan(
    connection: sqlite3.Connection,
    instance: Path,
    *,
    stage: str,
    candidate_snapshot_id: str,
    epoch_id: str | None = None,
) -> dict[str, Any]:
    config = load_json(CONFIG_PATH)
    if stage == "full":
        raise StateLoopError(
            "Full planning requires a fresh evaluator-owned sealed holdout outside this optimizer-visible harness"
        )
    if stage not in {"smoke", "pilot"}:
        raise StateLoopError(f"Unsupported stage: {stage}")
    candidate_row = connection.execute(
        "SELECT status FROM snapshots WHERE snapshot_id = ?", (candidate_snapshot_id,)
    ).fetchone()
    if candidate_row is None or candidate_row["status"] != "candidate":
        raise StateLoopError("Plan requires a registered candidate snapshot")
    baseline_snapshot_id, _ = get_active_snapshot_id(connection)
    stage_config = config["stages"][stage]
    episodes_by_id = {row["episode_id"]: row for row in load_jsonl(DEV_EPISODES_PATH)}
    episodes = [episodes_by_id[episode_id] for episode_id in stage_config["episode_ids"]]
    conditions = list(stage_config["condition_ids"])
    subject_prompt = SUBJECT_PROMPT_PATH.read_text(encoding="utf-8")
    subject_prompt_ref = put_artifact(
        connection, instance, subject_prompt.encode("utf-8"), "text/markdown"
    )
    subject_prompt_sha = subject_prompt_ref.sha256
    epoch_id = epoch_id or f"EPOCH-{stage.upper()}-{uuid.uuid4().hex[:12].upper()}"
    if connection.execute("SELECT 1 FROM epochs WHERE epoch_id = ?", (epoch_id,)).fetchone():
        raise ConflictError(f"Epoch already exists: {epoch_id}")

    private_rows: list[dict[str, Any]] = []
    blind_rows: list[dict[str, Any]] = []
    for episode_index, episode in enumerate(episodes):
        for trial in range(1, int(stage_config["trials"]) + 1):
            rotation = (episode_index + trial - 1) % len(conditions)
            ordered = conditions[rotation:] + conditions[:rotation]
            for latin_position, condition_id in enumerate(ordered, start=1):
                token = f"{epoch_id}:{episode['episode_id']}:{condition_id}:{trial}:{config['seeds']['execution']}"
                cell_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
                cell_id = f"CELL-{cell_hash[:16].upper()}"
                anonymous_hash = hashlib.sha256(
                    f"{cell_id}:{config['seeds']['anonymization']}".encode("utf-8")
                ).hexdigest()
                anonymous_id = f"ANON-{anonymous_hash[:12].upper()}"
                state_id = (
                    candidate_snapshot_id
                    if condition_id == "C1_GATED_EVOLVING"
                    else baseline_snapshot_id
                )
                task = {
                    "task_id": f"{cell_id}-EPISODE",
                    "domain": episode["domain"],
                    "tags": episode["tags"],
                    "surface": "codex",
                    "now": utc_now(),
                }
                _, context_ref = compile_context(
                    connection,
                    instance,
                    state_id,
                    task,
                    condition_id=condition_id,
                    log_event=False,
                )
                packet = {
                    "schema_version": "1.0",
                    "cell_id": cell_id,
                    "anonymous_id": anonymous_id,
                    "subject_prompt": subject_prompt,
                    "subject_prompt_sha256": subject_prompt_sha,
                    "condition_instruction": _condition_instruction(condition_id),
                    "context_pack_sha256": context_ref.sha256,
                    "episode": episode,
                    "completion_contract": {
                        "explicit_completion_required": True,
                        "output": "JSON object with turn_results, state_observations, status, and evidence_refs",
                    },
                }
                packet_ref = put_json_artifact(connection, instance, packet)
                row = {
                    "cell_id": cell_id,
                    "anonymous_id": anonymous_id,
                    "episode_id": episode["episode_id"],
                    "family": episode["family"],
                    "condition_id": condition_id,
                    "trial": trial,
                    "latin_position": latin_position,
                    "packet_sha256": packet_ref.sha256,
                    "state_snapshot_id": state_id,
                }
                private_rows.append(row)
                blind_rows.append(
                    {
                        "anonymous_id": anonymous_id,
                        "episode_id": episode["episode_id"],
                        "family": episode["family"],
                        "trial": trial,
                        "packet_sha256": packet_ref.sha256,
                    }
                )
    private_rows.sort(key=lambda row: (row["episode_id"], row["trial"], row["latin_position"]))
    blind_rng = random.Random(config["seeds"]["anonymization"])
    blind_rng.shuffle(blind_rows)
    plan = {
        "schema_version": "1.0",
        "epoch_id": epoch_id,
        "stage": stage,
        "created_at": utc_now(),
        "baseline_snapshot_id": baseline_snapshot_id,
        "candidate_snapshot_id": candidate_snapshot_id,
        "cell_count": len(private_rows),
        "rows": private_rows,
    }
    blind_plan = {
        "schema_version": "1.0",
        "epoch_id": epoch_id,
        "stage": stage,
        "cell_count": len(blind_rows),
        "rows": blind_rows,
    }
    connection.execute("BEGIN IMMEDIATE")
    try:
        plan_ref = put_json_artifact(connection, instance, plan)
        blind_ref = put_json_artifact(connection, instance, blind_plan)
        event = append_event_tx(
            connection,
            stream_id=f"epoch:{epoch_id}",
            event_type="epoch_planned",
            actor_type="harness",
            actor_id="planner-v1",
            payload={
                "epoch_id": epoch_id,
                "stage": stage,
                "cell_count": len(private_rows),
                "baseline_snapshot_id": baseline_snapshot_id,
                "candidate_snapshot_id": candidate_snapshot_id,
            },
            idempotency_key=f"epoch-plan:{epoch_id}",
            input_refs=(subject_prompt_sha,),
            output_refs=(plan_ref.sha256, blind_ref.sha256),
            iteration_id=epoch_id,
            candidate_id=candidate_snapshot_id,
            base_snapshot_id=baseline_snapshot_id,
        )
        connection.execute(
            "INSERT INTO epochs(epoch_id,stage,baseline_snapshot_id,candidate_snapshot_id,plan_sha256,blind_plan_sha256,status,created_event_id) VALUES(?,?,?,?,?,?,?,?)",
            (
                epoch_id, stage, baseline_snapshot_id, candidate_snapshot_id,
                plan_ref.sha256, blind_ref.sha256, "planned", event["event_id"],
            ),
        )
        for ordinal, row in enumerate(private_rows, start=1):
            connection.execute(
                "INSERT INTO cells(cell_id,epoch_id,anonymous_id,episode_id,family,condition_id,trial,ordinal,packet_sha256,status) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    row["cell_id"], epoch_id, row["anonymous_id"], row["episode_id"],
                    row["family"], row["condition_id"], row["trial"], ordinal,
                    row["packet_sha256"], "planned",
                ),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    export_events(connection, instance)
    return {
        "epoch_id": epoch_id,
        "stage": stage,
        "cell_count": len(private_rows),
        "plan_sha256": plan_ref.sha256,
        "blind_plan_sha256": blind_ref.sha256,
    }


def validate_evaluation_record(record: dict[str, Any]) -> None:
    required = {
        "schema_version", "record_id", "cell_id", "anonymous_id", "episode_id", "family",
        "trial", "grader_id", "record_status", "scores", "critical_gate", "gate_reasons",
        "pairwise", "evidence_refs", "graded_at",
    }
    missing = required - set(record)
    if missing:
        raise StateLoopError(f"Evaluation record missing fields: {sorted(missing)}")
    scores = record["scores"]
    bounds = load_json(CONFIG_PATH)["score_channels"]
    for name, rule in bounds.items():
        if name not in scores:
            raise StateLoopError(f"Evaluation record missing score: {name}")
        value = scores[name]
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
            raise StateLoopError(f"Invalid score {name}: {value}")
        if value < rule["minimum"] or ("maximum" in rule and value > rule["maximum"]):
            raise StateLoopError(f"Score {name} outside bounds: {value}")
    parse_time(record["graded_at"])


def ingest_evaluations(
    connection: sqlite3.Connection,
    instance: Path,
    epoch_id: str,
    records: Iterable[dict[str, Any]],
) -> int:
    epoch = connection.execute("SELECT * FROM epochs WHERE epoch_id = ?", (epoch_id,)).fetchone()
    if epoch is None:
        raise StateLoopError(f"Unknown epoch: {epoch_id}")
    count = 0
    for record in records:
        validate_evaluation_record(record)
        cell = connection.execute("SELECT * FROM cells WHERE cell_id = ? AND epoch_id = ?", (record["cell_id"], epoch_id)).fetchone()
        if cell is None:
            raise StateLoopError(f"Evaluation references unknown cell: {record['cell_id']}")
        for field in ("anonymous_id", "episode_id", "family", "trial"):
            if record[field] != cell[field]:
                raise StateLoopError(f"Evaluation {field} does not match frozen cell")
        connection.execute("BEGIN IMMEDIATE")
        try:
            record_ref = put_json_artifact(connection, instance, record)
            event = append_event_tx(
                connection,
                stream_id=f"epoch:{epoch_id}",
                event_type="evaluation_record_ingested",
                actor_type="grader",
                actor_id=record["grader_id"],
                payload={
                    "record_id": record["record_id"],
                    "cell_id": record["cell_id"],
                    "record_status": record["record_status"],
                    "critical_gate": record["critical_gate"],
                },
                idempotency_key=f"evaluation:{record['record_id']}",
                input_refs=(record_ref.sha256,),
                iteration_id=epoch_id,
                candidate_id=epoch["candidate_snapshot_id"],
                base_snapshot_id=epoch["baseline_snapshot_id"],
            )
            connection.execute(
                "INSERT INTO evaluations(record_id,cell_id,artifact_sha256,record_status,created_event_id) VALUES(?,?,?,?,?)",
                (
                    record["record_id"], record["cell_id"], record_ref.sha256,
                    record["record_status"], event["event_id"],
                ),
            )
            connection.commit()
        except sqlite3.IntegrityError as error:
            connection.rollback()
            raise ConflictError(f"Duplicate evaluation record: {record['record_id']}") from error
        except Exception:
            connection.rollback()
            raise
        count += 1
    export_events(connection, instance)
    return count


def _bootstrap_lcb(values_by_family: dict[str, list[float]], seed: int, iterations: int = 2000) -> float | None:
    if not values_by_family or not all(values_by_family.values()):
        return None
    rng = random.Random(seed)
    draws: list[float] = []
    families = sorted(values_by_family)
    for _ in range(iterations):
        sampled: list[float] = []
        for family in families:
            values = values_by_family[family]
            sampled.extend(rng.choice(values) for _ in range(len(values)))
        draws.append(statistics.fmean(sampled))
    draws.sort()
    return draws[max(0, int(0.025 * len(draws)) - 1)]


def _mean(values: Sequence[float]) -> float | None:
    return statistics.fmean(values) if values else None


def evaluate_epoch(connection: sqlite3.Connection, instance: Path, epoch_id: str) -> dict[str, Any]:
    config = load_json(CONFIG_PATH)
    epoch = connection.execute("SELECT * FROM epochs WHERE epoch_id = ?", (epoch_id,)).fetchone()
    if epoch is None:
        raise StateLoopError(f"Unknown epoch: {epoch_id}")
    cells = connection.execute("SELECT * FROM cells WHERE epoch_id = ?", (epoch_id,)).fetchall()
    records_by_cell: dict[str, list[dict[str, Any]]] = {}
    for row in connection.execute(
        "SELECT e.*,c.condition_id,c.family,c.episode_id,c.trial,c.anonymous_id FROM evaluations e JOIN cells c ON c.cell_id=e.cell_id WHERE c.epoch_id=?",
        (epoch_id,),
    ):
        record = read_json_artifact(connection, instance, row["artifact_sha256"])
        record["_condition_id"] = row["condition_id"]
        records_by_cell.setdefault(row["cell_id"], []).append(record)
    missing_cells = [row["cell_id"] for row in cells if row["cell_id"] not in records_by_cell]
    if missing_cells:
        raise StateLoopError(f"Epoch has {len(missing_cells)} cells without evaluation records")

    cell_scores: dict[str, dict[str, float]] = {}
    cell_meta: dict[str, sqlite3.Row] = {row["cell_id"]: row for row in cells}
    for cell_id, records in records_by_cell.items():
        cell_scores[cell_id] = {
            metric: statistics.fmean(float(record["scores"][metric]) for record in records)
            for metric in config["score_channels"]
        }

    condition_summary: dict[str, dict[str, float | int | None]] = {}
    for condition_id in sorted({row["condition_id"] for row in cells}):
        condition_cells = [row for row in cells if row["condition_id"] == condition_id]
        condition_summary[condition_id] = {
            metric: _mean([cell_scores[row["cell_id"]][metric] for row in condition_cells])
            for metric in config["score_channels"]
        }
        condition_summary[condition_id]["cells"] = len(condition_cells)

    candidate = config["promotion_defaults"]["candidate_condition"]
    baseline = config["promotion_defaults"]["adoption_baseline"]
    paired: dict[tuple[str, int], dict[str, tuple[sqlite3.Row, dict[str, float]]]] = {}
    for row in cells:
        if row["condition_id"] in {candidate, baseline}:
            paired.setdefault((row["episode_id"], row["trial"]), {})[row["condition_id"]] = (
                row, cell_scores[row["cell_id"]]
            )
    complete_pairs = [value for value in paired.values() if candidate in value and baseline in value]
    deltas_by_family: dict[str, list[float]] = {}
    requirement_deltas: list[float] = []
    for pair in complete_pairs:
        candidate_row, candidate_scores = pair[candidate]
        _, baseline_scores = pair[baseline]
        delta = candidate_scores["task_score"] - baseline_scores["task_score"]
        deltas_by_family.setdefault(candidate_row["family"], []).append(delta)
        requirement_deltas.append(
            candidate_scores["requirement_preservation"] - baseline_scores["requirement_preservation"]
        )
    task_deltas = [value for values in deltas_by_family.values() for value in values]
    task_delta = _mean(task_deltas)
    task_lcb = _bootstrap_lcb(deltas_by_family, config["seeds"]["bootstrap"])
    family_deltas = {family: statistics.fmean(values) for family, values in sorted(deltas_by_family.items())}

    candidate_cells = [row for row in cells if row["condition_id"] == candidate]
    critical_gates = sum(
        1
        for row in candidate_cells
        for record in records_by_cell[row["cell_id"]]
        if record["critical_gate"]
    )
    all_human_final = all(
        record["record_status"] == "human-final"
        for row in candidate_cells
        for record in records_by_cell[row["cell_id"]]
    )
    candidate_summary = condition_summary.get(candidate, {})
    baseline_summary = condition_summary.get(baseline, {})
    baseline_cost = baseline_summary.get("cost_units")
    candidate_cost = candidate_summary.get("cost_units")
    cost_ratio = (
        float(candidate_cost) / float(baseline_cost)
        if isinstance(candidate_cost, (int, float)) and isinstance(baseline_cost, (int, float)) and baseline_cost > 0
        else None
    )
    pairwise_values: list[float] = []
    anonymous_to_condition = {row["anonymous_id"]: row["condition_id"] for row in cells}
    for records in records_by_cell.values():
        for record in records:
            comparison = record.get("pairwise")
            if not comparison:
                continue
            left = anonymous_to_condition.get(comparison.get("left_anonymous_id"))
            right = anonymous_to_condition.get(comparison.get("right_anonymous_id"))
            if {left, right} != {candidate, baseline}:
                continue
            winner = comparison.get("winner")
            if winner == "tie":
                pairwise_values.append(0.5)
            else:
                winning_condition = left if winner == "left" else right
                pairwise_values.append(1.0 if winning_condition == candidate else 0.0)
    pairwise_lcb = (
        _bootstrap_lcb({"all": pairwise_values}, config["seeds"]["bootstrap"] + 1)
        if pairwise_values else None
    )

    thresholds = config["promotion_defaults"]
    gates = {
        "stage_is_full": epoch["stage"] == thresholds["eligible_stage"],
        "human_final": all_human_final,
        "no_critical_gates": critical_gates <= thresholds["maximum_critical_gates"],
        "task_delta_lcb": task_lcb is not None and task_lcb >= thresholds["minimum_task_delta_lcb95"],
        "pairwise_lcb": pairwise_lcb is not None and pairwise_lcb > thresholds["minimum_pairwise_win_lcb95"],
        "family_floor": bool(family_deltas) and min(family_deltas.values()) >= thresholds["minimum_family_delta"],
        "requirement_preservation": bool(requirement_deltas) and statistics.fmean(requirement_deltas) >= 0,
        "context_precision": isinstance(candidate_summary.get("context_precision"), (int, float)) and candidate_summary["context_precision"] >= thresholds["minimum_context_precision"],
        "stale_rate": isinstance(candidate_summary.get("stale_or_irrelevant_rate"), (int, float)) and candidate_summary["stale_or_irrelevant_rate"] <= thresholds["maximum_stale_or_irrelevant_rate"],
        "cost": cost_ratio is not None and (
            cost_ratio <= thresholds["maximum_cost_ratio"]
            or (task_delta is not None and task_delta >= thresholds["cost_exception_minimum_task_delta"])
        ),
    }
    status = (
        "eligible_for_human_review"
        if all(gates.values())
        else "development_only"
        if epoch["stage"] in {"smoke", "pilot"}
        else "not_eligible"
    )
    summary = {
        "schema_version": "1.0",
        "epoch_id": epoch_id,
        "stage": epoch["stage"],
        "evaluated_at": utc_now(),
        "record_count": sum(len(records) for records in records_by_cell.values()),
        "cell_count": len(cells),
        "missing_cells": [],
        "condition_summary": condition_summary,
        "primary_comparison": {
            "candidate": candidate,
            "baseline": baseline,
            "paired_episode_trials": len(complete_pairs),
            "mean_task_delta": task_delta,
            "task_delta_lcb95": task_lcb,
            "pairwise_comparisons": len(pairwise_values),
            "pairwise_win_lcb95": pairwise_lcb,
            "family_deltas": family_deltas,
            "mean_requirement_delta": _mean(requirement_deltas),
            "cost_ratio": cost_ratio,
            "critical_gates": critical_gates,
        },
        "promotion_gates": gates,
        "status": status,
        "evidence_state": "provisional" if not all_human_final else "human-final",
        "claim_boundary": "Development results cannot establish promotion; a fresh blinded holdout and named-human approval are required.",
    }
    connection.execute("BEGIN IMMEDIATE")
    try:
        summary_ref = put_json_artifact(connection, instance, summary)
        event = append_event_tx(
            connection,
            stream_id=f"epoch:{epoch_id}",
            event_type="epoch_evaluated",
            actor_type="harness",
            actor_id="evaluator-v1",
            payload={"epoch_id": epoch_id, "status": status, "gates": gates},
            idempotency_key=f"epoch-evaluate:{epoch_id}:{summary_ref.sha256}",
            input_refs=tuple(
                sorted(
                    row["artifact_sha256"]
                    for row in connection.execute(
                        "SELECT e.artifact_sha256 FROM evaluations e JOIN cells c ON c.cell_id=e.cell_id WHERE c.epoch_id=?",
                        (epoch_id,),
                    )
                )
            ),
            output_refs=(summary_ref.sha256,),
            iteration_id=epoch_id,
            candidate_id=epoch["candidate_snapshot_id"],
            base_snapshot_id=epoch["baseline_snapshot_id"],
        )
        connection.execute(
            "UPDATE epochs SET status=?,summary_sha256=? WHERE epoch_id=?",
            (status, summary_ref.sha256, epoch_id),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    export_events(connection, instance)
    summary["summary_sha256"] = summary_ref.sha256
    summary["event_id"] = event["event_id"]
    return summary


def _validate_human_approval(approval: dict[str, Any], decision: str) -> str:
    required = {
        "schema_version",
        "approval_id",
        "decision",
        "human_approved",
        "approved_by",
        "approved_at",
        "expires_at",
        "expected_active_snapshot_id",
        "expected_active_version",
    }
    missing = sorted(required - approval.keys())
    if missing:
        raise StateLoopError(f"Approval is missing required fields: {missing}")
    if approval["schema_version"] != "1.0" or approval["decision"] != decision:
        raise StateLoopError(f"Approval must be schema 1.0 for decision {decision}")
    if approval["human_approved"] is not True:
        raise StateLoopError("A named human must explicitly approve this transition")
    approved_by = str(approval["approved_by"]).strip()
    blocked = {"agent", "codex", "grader", "harness", "model", "optimizer", "subject"}
    if not approved_by or approved_by.casefold() in blocked:
        raise StateLoopError("approved_by must identify a human, not an agent role")
    approved_at = parse_time(str(approval["approved_at"]))
    expires_at = parse_time(str(approval["expires_at"]))
    if approved_at.tzinfo is None or expires_at.tzinfo is None:
        raise StateLoopError("Approval timestamps must include a timezone")
    now = datetime.now(timezone.utc)
    if approved_at > now or expires_at <= now or expires_at <= approved_at:
        raise StateLoopError("Approval is not currently valid")
    if not isinstance(approval["expected_active_version"], int):
        raise StateLoopError("expected_active_version must be an integer")
    return approved_by


def _require_artifact_refs(
    connection: sqlite3.Connection, instance: Path, references: Iterable[str]
) -> None:
    for reference in references:
        if not re.fullmatch(r"[0-9a-f]{64}", str(reference)):
            raise StateLoopError(f"Invalid artifact reference: {reference}")
        read_artifact(connection, instance, str(reference))


def promote_candidate(
    connection: sqlite3.Connection,
    instance: Path,
    epoch_id: str,
    approval: dict[str, Any],
) -> dict[str, Any]:
    """Promote only a human-final, fresh-holdout winner with tested recovery."""
    approved_by = _validate_human_approval(approval, "promote")
    promotion_required = {
        "epoch_id",
        "summary_sha256",
        "candidate_snapshot_id",
        "holdout_manifest_sha256",
        "canary_evidence_sha256",
        "rollback_evidence_sha256",
        "fresh_holdout_attested",
        "grader_independence_attested",
        "canary_completed",
        "rollback_tested",
    }
    missing = sorted(promotion_required - approval.keys())
    if missing:
        raise StateLoopError(f"Promotion approval is missing required fields: {missing}")
    if approval["epoch_id"] != epoch_id:
        raise StateLoopError("Approval epoch does not match the requested epoch")
    for field in (
        "fresh_holdout_attested",
        "grader_independence_attested",
        "canary_completed",
        "rollback_tested",
    ):
        if approval[field] is not True:
            raise StateLoopError(f"Promotion gate is not attested: {field}")

    epoch = connection.execute("SELECT * FROM epochs WHERE epoch_id=?", (epoch_id,)).fetchone()
    if epoch is None:
        raise StateLoopError(f"Unknown epoch: {epoch_id}")
    if epoch["stage"] != "full" or epoch["status"] != "eligible_for_human_review":
        raise StateLoopError("Only a completed eligible full holdout may be promoted")
    if not epoch["summary_sha256"] or epoch["summary_sha256"] != approval["summary_sha256"]:
        raise StateLoopError("Approval summary hash does not match the evaluated epoch")
    if epoch["candidate_snapshot_id"] != approval["candidate_snapshot_id"]:
        raise StateLoopError("Approval candidate does not match the evaluated epoch")

    active_id, active_version = get_active_snapshot_id(connection)
    if (
        active_id != approval["expected_active_snapshot_id"]
        or active_version != approval["expected_active_version"]
        or active_id != epoch["baseline_snapshot_id"]
    ):
        raise ConflictError("Active context changed after the promotion decision")

    summary = read_json_artifact(connection, instance, epoch["summary_sha256"])
    gates = summary.get("promotion_gates")
    holdout = summary.get("holdout")
    if (
        summary.get("status") != "eligible_for_human_review"
        or summary.get("evidence_state") != "human-final"
        or not isinstance(gates, dict)
        or not gates
        or not all(value is True for value in gates.values())
    ):
        raise StateLoopError("Evaluation summary does not satisfy every promotion gate")
    expected_holdout = {
        "fresh": True,
        "sealed_before_run": True,
        "optimizer_visible": False,
        "spent_after_reveal": True,
        "grader_independent": True,
        "manifest_sha256": approval["holdout_manifest_sha256"],
    }
    if not isinstance(holdout, dict) or any(holdout.get(k) != v for k, v in expected_holdout.items()):
        raise StateLoopError("Fresh sealed holdout attestations are absent or inconsistent")

    evidence_refs = (
        approval["summary_sha256"],
        approval["holdout_manifest_sha256"],
        approval["canary_evidence_sha256"],
        approval["rollback_evidence_sha256"],
    )
    _require_artifact_refs(connection, instance, evidence_refs)
    candidate_row = connection.execute(
        "SELECT * FROM snapshots WHERE snapshot_id=?", (epoch["candidate_snapshot_id"],)
    ).fetchone()
    active_row = connection.execute("SELECT * FROM snapshots WHERE snapshot_id=?", (active_id,)).fetchone()
    if candidate_row is None or candidate_row["status"] != "candidate" or active_row is None:
        raise StateLoopError("Promotion candidate or active snapshot is not in a promotable state")

    approval_digest = sha256_json(approval)
    accepted_id = f"CTX-STATE-ACCEPTED-{approval_digest[:12].upper()}"
    event_id = f"EVT-{uuid.uuid4().hex.upper()}"
    accepted = copy.deepcopy(get_snapshot(connection, instance, candidate_row["snapshot_id"]))
    accepted.update(
        {
            "snapshot_id": accepted_id,
            "parent_snapshot_id": active_id,
            "revision": int(active_row["revision"]) + 1,
            "status": "accepted",
            "created_at": utc_now(),
            "created_by_event": event_id,
            "rollback_snapshot_id": active_id,
        }
    )
    validate_state(accepted)

    connection.execute("BEGIN IMMEDIATE")
    try:
        approval_ref = put_json_artifact(connection, instance, approval)
        accepted_ref = put_json_artifact(connection, instance, accepted)
        event = append_event_tx(
            connection,
            stream_id=f"state:{active_id}",
            event_type="context_candidate_promoted",
            actor_type="human",
            actor_id=approved_by,
            payload={
                "approval_id": approval["approval_id"],
                "epoch_id": epoch_id,
                "candidate_snapshot_id": candidate_row["snapshot_id"],
                "accepted_snapshot_id": accepted_id,
                "previous_snapshot_id": active_id,
            },
            idempotency_key=f"promotion:{approval['approval_id']}",
            input_refs=tuple(sorted((approval_ref.sha256, *evidence_refs))),
            output_refs=(accepted_ref.sha256,),
            iteration_id=epoch_id,
            candidate_id=candidate_row["snapshot_id"],
            base_snapshot_id=active_id,
            event_id=event_id,
        )
        connection.execute(
            "INSERT INTO snapshots(snapshot_id,parent_snapshot_id,revision,status,owner,artifact_sha256,created_event_id,created_at,rollback_snapshot_id) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                accepted_id,
                active_id,
                accepted["revision"],
                "accepted",
                accepted["owner"],
                accepted_ref.sha256,
                event["event_id"],
                accepted["created_at"],
                active_id,
            ),
        )
        cursor = connection.execute(
            "UPDATE active_state SET snapshot_id=?,version=version+1 WHERE singleton=1 AND snapshot_id=? AND version=?",
            (accepted_id, active_id, active_version),
        )
        if cursor.rowcount != 1:
            raise ConflictError("Active context changed during promotion")
        connection.execute("UPDATE snapshots SET status='superseded' WHERE snapshot_id=?", (active_id,))
        connection.execute(
            "UPDATE snapshots SET status='promoted' WHERE snapshot_id=?", (candidate_row["snapshot_id"],)
        )
        connection.execute(
            "UPDATE proposals SET status='promoted' WHERE candidate_snapshot_id=?",
            (candidate_row["snapshot_id"],),
        )
        connection.execute("UPDATE epochs SET status='promoted' WHERE epoch_id=?", (epoch_id,))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    export_events(connection, instance)
    return {
        "status": "promoted",
        "epoch_id": epoch_id,
        "accepted_snapshot_id": accepted_id,
        "previous_snapshot_id": active_id,
        "active_pointer_version": active_version + 1,
        "event_id": event["event_id"],
    }


def _is_ancestor(connection: sqlite3.Connection, descendant_id: str, ancestor_id: str) -> bool:
    seen: set[str] = set()
    current: str | None = descendant_id
    while current is not None and current not in seen:
        if current == ancestor_id:
            return True
        seen.add(current)
        row = connection.execute(
            "SELECT parent_snapshot_id FROM snapshots WHERE snapshot_id=?", (current,)
        ).fetchone()
        current = str(row["parent_snapshot_id"]) if row and row["parent_snapshot_id"] else None
    return False


def rollback_context(
    connection: sqlite3.Connection, instance: Path, approval: dict[str, Any]
) -> dict[str, Any]:
    """Move the active pointer to a verified ancestor under human approval and CAS."""
    approved_by = _validate_human_approval(approval, "rollback")
    for field in ("rollback_snapshot_id", "reason"):
        if not str(approval.get(field, "")).strip():
            raise StateLoopError(f"Rollback approval is missing: {field}")
    active_id, active_version = get_active_snapshot_id(connection)
    if active_id != approval["expected_active_snapshot_id"] or active_version != approval["expected_active_version"]:
        raise ConflictError("Active context changed after the rollback decision")
    target_id = str(approval["rollback_snapshot_id"])
    if target_id == active_id or not _is_ancestor(connection, active_id, target_id):
        raise StateLoopError("Rollback target must be a prior ancestor of the active snapshot")
    target_row = connection.execute("SELECT * FROM snapshots WHERE snapshot_id=?", (target_id,)).fetchone()
    if target_row is None or target_row["status"] not in {"accepted", "superseded", "rolled_back"}:
        raise StateLoopError("Rollback target is not an accepted historical snapshot")
    target_ref = target_row["artifact_sha256"]
    read_artifact(connection, instance, target_ref)

    connection.execute("BEGIN IMMEDIATE")
    try:
        approval_ref = put_json_artifact(connection, instance, approval)
        event = append_event_tx(
            connection,
            stream_id=f"state:{active_id}",
            event_type="context_state_rolled_back",
            actor_type="human",
            actor_id=approved_by,
            payload={
                "approval_id": approval["approval_id"],
                "from_snapshot_id": active_id,
                "to_snapshot_id": target_id,
                "reason": approval["reason"],
            },
            idempotency_key=f"rollback:{approval['approval_id']}",
            input_refs=(approval_ref.sha256, target_ref),
            output_refs=(target_ref,),
            candidate_id=active_id,
            base_snapshot_id=target_id,
        )
        cursor = connection.execute(
            "UPDATE active_state SET snapshot_id=?,version=version+1 WHERE singleton=1 AND snapshot_id=? AND version=?",
            (target_id, active_id, active_version),
        )
        if cursor.rowcount != 1:
            raise ConflictError("Active context changed during rollback")
        connection.execute("UPDATE snapshots SET status='rolled_back' WHERE snapshot_id=?", (active_id,))
        connection.execute("UPDATE snapshots SET status='accepted' WHERE snapshot_id=?", (target_id,))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    export_events(connection, instance)
    return {
        "status": "rolled_back",
        "from_snapshot_id": active_id,
        "active_snapshot_id": target_id,
        "active_pointer_version": active_version + 1,
        "event_id": event["event_id"],
    }


def audit_instance(connection: sqlite3.Connection, instance: Path) -> dict[str, Any]:
    errors: list[str] = []
    event_count = 0
    for stream in connection.execute("SELECT * FROM streams ORDER BY stream_id"):
        previous = GENESIS_HASH
        expected_version = 1
        rows = connection.execute(
            "SELECT * FROM events WHERE stream_id=? ORDER BY stream_version", (stream["stream_id"],)
        ).fetchall()
        for row in rows:
            event_count += 1
            event = event_row_to_dict(row)
            stored_hash = event.pop("event_hash")
            if event["stream_version"] != expected_version:
                errors.append(f"stream version gap: {stream['stream_id']}")
            if event["previous_event_hash"] != previous:
                errors.append(f"previous hash mismatch: {event['event_id']}")
            calculated = sha256_bytes((previous + canonical_json(event)).encode("utf-8"))
            if calculated != stored_hash:
                errors.append(f"event hash mismatch: {event['event_id']}")
            previous = stored_hash
            expected_version += 1
        if previous != stream["tail_hash"] or len(rows) != stream["version"]:
            errors.append(f"stream tail mismatch: {stream['stream_id']}")
    artifact_count = 0
    for row in connection.execute("SELECT * FROM artifacts"):
        artifact_count += 1
        path = instance / row["relative_path"]
        if not path.is_file():
            errors.append(f"missing artifact: {row['sha256']}")
        elif sha256_bytes(path.read_bytes()) != row["sha256"]:
            errors.append(f"artifact hash mismatch: {row['sha256']}")
    foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_keys:
        errors.append(f"foreign key failures: {len(foreign_keys)}")
    active_id, active_version = get_active_snapshot_id(connection)
    result = {
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "event_count": event_count,
        "artifact_count": artifact_count,
        "active_snapshot_id": active_id,
        "active_pointer_version": active_version,
    }
    return result


def instance_status(connection: sqlite3.Connection) -> dict[str, Any]:
    active_id, active_version = get_active_snapshot_id(connection)
    return {
        "process_id": connection.execute("SELECT value FROM metadata WHERE key='process_id'").fetchone()[0],
        "active_snapshot_id": active_id,
        "active_pointer_version": active_version,
        "snapshots": connection.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0],
        "candidates": connection.execute("SELECT COUNT(*) FROM snapshots WHERE status='candidate'").fetchone()[0],
        "events": connection.execute("SELECT COUNT(*) FROM events").fetchone()[0],
        "epochs": connection.execute("SELECT COUNT(*) FROM epochs").fetchone()[0],
        "evaluation_records": connection.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0],
        "live_execution_authorized": load_json(CONFIG_PATH)["live_execution"]["authorized"],
        "behavioral_efficacy": "Unknown" if connection.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0] == 0 else "Provisional only",
    }


def demo(instance: Path) -> dict[str, Any]:
    initialized = initialize_instance(instance)
    connection = connect(instance)
    observation = {
        "observation_id": "DEMO-OBS-001",
        "episode_id": "EP-D-001",
        "split": "dev",
        "actor_type": "human",
        "actor_id": "synthetic-demo",
        "payload": {
            "feedback": "For synthetic launch notes, use exactly three bullets under 18 words.",
            "mechanical_demo": True,
        },
    }
    event_id = register_observations(connection, instance, [observation])[0]
    proposal = {
        "schema_version": "1.0",
        "proposal_id": "PROP-DEMO-001",
        "base_snapshot_id": initialized["active_snapshot_id"],
        "created_by": "codex-optimizer-synthetic-demo",
        "created_at": utc_now(),
        "source_event_ids": [event_id],
        "hypothesis": "A narrowly scoped launch-note preference improves later launch-note compliance without affecting unrelated editing.",
        "changed_mechanism": "add one scoped preference entry",
        "predicted_benefit": "better recall on same-scope tasks",
        "predicted_regressions": ["format may leak to unrelated editing"],
        "counterexamples": ["personal bio", "policy summary"],
        "operations": [
            {
                "op": "add",
                "entry": {
                    "entry_id": "CTX-DEMO-001",
                    "kind": "preference",
                    "content": "For synthetic launch notes, use exactly three bullets and keep each under 18 words.",
                    "scope": {"domains": ["editing"], "task_tags": ["launch-note"]},
                    "source_event_ids": [event_id],
                    "evidence_state": "Experimental",
                    "confidence": 0.8,
                    "priority": 60,
                    "sensitivity": "internal",
                    "allowed_surfaces": ["codex"],
                    "authority_effect": "none",
                    "owner": "Project owner (identity unresolved)",
                    "valid_from": utc_now(),
                    "expires_at": None,
                    "refresh_trigger": "user correction or three failed same-scope uses",
                    "status": "active",
                    "supersedes": [],
                },
            }
        ],
    }
    candidate = apply_proposal(connection, instance, proposal)
    context, context_ref = compile_context(
        connection,
        instance,
        candidate["candidate_snapshot_id"],
        {"task_id": "DEMO-TASK-001", "domain": "editing", "tags": ["launch-note"], "surface": "codex"},
        condition_id="C1_GATED_EVOLVING",
    )
    plan = create_plan(
        connection,
        instance,
        stage="smoke",
        candidate_snapshot_id=candidate["candidate_snapshot_id"],
        epoch_id="EPOCH-SMOKE-DEMO",
    )
    audit = audit_instance(connection, instance)
    result = {
        "mechanical_demo": True,
        "behavioral_efficacy": "Unknown — no model calls or behavioral grades were produced",
        "candidate_snapshot_id": candidate["candidate_snapshot_id"],
        "selected_context_entries": context["trace"]["included_entry_ids"],
        "context_pack_sha256": context_ref.sha256,
        "smoke_plan": plan,
        "audit": audit,
    }
    atomic_write(instance / "exports" / "demo-summary.json", (json.dumps(result, indent=2) + "\n").encode("utf-8"))
    connection.close()
    return result


def _load_records_argument(path: Path) -> list[dict[str, Any]]:
    return load_jsonl(path) if path.suffix == ".jsonl" else [load_json(path)]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("init", "status", "audit", "export", "demo"):
        child = subparsers.add_parser(name)
        child.add_argument("--instance", type=Path, required=True)
    observations = subparsers.add_parser("observe")
    observations.add_argument("--instance", type=Path, required=True)
    observations.add_argument("--input", type=Path, required=True)
    proposal = subparsers.add_parser("propose")
    proposal.add_argument("--instance", type=Path, required=True)
    proposal.add_argument("--proposal", type=Path, required=True)
    context = subparsers.add_parser("context")
    context.add_argument("--instance", type=Path, required=True)
    context.add_argument("--snapshot-id", required=True)
    context.add_argument("--task", type=Path, required=True)
    context.add_argument("--condition", default="B3_RETRIEVAL_ONLY")
    plan = subparsers.add_parser("plan")
    plan.add_argument("--instance", type=Path, required=True)
    plan.add_argument("--candidate-snapshot-id", required=True)
    plan.add_argument("--stage", choices=("smoke", "pilot", "full"), required=True)
    plan.add_argument("--epoch-id")
    ingest = subparsers.add_parser("ingest-evaluations")
    ingest.add_argument("--instance", type=Path, required=True)
    ingest.add_argument("--epoch-id", required=True)
    ingest.add_argument("--input", type=Path, required=True)
    evaluate = subparsers.add_parser("evaluate")
    evaluate.add_argument("--instance", type=Path, required=True)
    evaluate.add_argument("--epoch-id", required=True)
    promote = subparsers.add_parser("promote")
    promote.add_argument("--instance", type=Path, required=True)
    promote.add_argument("--epoch-id", required=True)
    promote.add_argument("--approval", type=Path, required=True)
    rollback = subparsers.add_parser("rollback")
    rollback.add_argument("--instance", type=Path, required=True)
    rollback.add_argument("--approval", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init":
            result = initialize_instance(args.instance.resolve())
        elif args.command == "demo":
            result = demo(args.instance.resolve())
        else:
            instance = args.instance.resolve()
            connection = connect(instance)
            try:
                if args.command == "status":
                    result = instance_status(connection)
                elif args.command == "audit":
                    result = audit_instance(connection, instance)
                elif args.command == "export":
                    result = {"events": str(export_events(connection, instance))}
                elif args.command == "observe":
                    result = {"event_ids": register_observations(connection, instance, _load_records_argument(args.input))}
                elif args.command == "propose":
                    result = apply_proposal(connection, instance, load_json(args.proposal))
                elif args.command == "context":
                    pack, reference = compile_context(
                        connection, instance, args.snapshot_id, load_json(args.task), condition_id=args.condition
                    )
                    result = {"context_pack_sha256": reference.sha256, "trace": pack["trace"]}
                elif args.command == "plan":
                    result = create_plan(
                        connection,
                        instance,
                        stage=args.stage,
                        candidate_snapshot_id=args.candidate_snapshot_id,
                        epoch_id=args.epoch_id,
                    )
                elif args.command == "ingest-evaluations":
                    result = {
                        "ingested": ingest_evaluations(
                            connection, instance, args.epoch_id, _load_records_argument(args.input)
                        )
                    }
                elif args.command == "evaluate":
                    result = evaluate_epoch(connection, instance, args.epoch_id)
                elif args.command == "promote":
                    result = promote_candidate(
                        connection, instance, args.epoch_id, load_json(args.approval)
                    )
                elif args.command == "rollback":
                    result = rollback_context(connection, instance, load_json(args.approval))
                else:
                    raise AssertionError(args.command)
            finally:
                connection.close()
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (StateLoopError, OSError, json.JSONDecodeError, sqlite3.Error) as error:
        print(json.dumps({"status": "error", "error": str(error)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
