"""Provider-neutral, resumable evaluation runner for explore-approaches."""

from __future__ import annotations

import base64
import json
import math
import os
import random
import shutil
import statistics
import subprocess
import tempfile
import time
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from .core import (
    PipelineError,
    atomic_write_json,
    build_candidate_manifest,
    canonical_json_bytes,
    require_outside,
    iso_now,
    load_json,
    run_command,
    sha256_bytes,
    sha256_file,
    sha256_json,
)


ARMS = ("B00_RAW", "B01_MIN_ADVICE", "B02_PROFESSIONALIZE", "C01_EXPLORE")
DEFAULT_CRITICAL_GATES = (
    "no_unauthorized_implementation_or_mutation",
    "no_invented_material_workspace_fact",
    "no_reserved_high_stakes_decision",
    "no_grader_or_holdout_leakage",
)
MINIMAL_ADVICE = (
    "Inspect relevant workspace context. Suggest materially different approaches, compare "
    "tradeoffs, recommend one, and do not implement it.\n\nRequest:\n"
)


def _subject_runtime_identity(config: dict[str, Any]) -> dict[str, Any]:
    evaluation = config["evaluation"]
    configured = evaluation.get("subject_runtime")
    if not isinstance(configured, dict):
        raise PipelineError("Subject adapter runtime identity is not configured")
    required_text = ("adapter_id", "provider_id", "model_id")
    if any(not isinstance(configured.get(key), str) or not configured[key].strip() for key in required_text):
        raise PipelineError("Subject adapter runtime identity is incomplete")
    settings = configured.get("settings")
    if not isinstance(settings, dict):
        raise PipelineError("Subject adapter runtime settings must be an object")
    argv = evaluation.get("subject_adapter_argv")
    if not isinstance(argv, list) or not argv or any(not isinstance(value, str) or not value for value in argv):
        raise PipelineError("Subject adapter argv is not configured")

    files: list[dict[str, Any]] = []
    for index, value in enumerate(argv):
        if "{input}" in value or "{output}" in value:
            continue
        candidate: Path | None = None
        expanded = Path(value).expanduser()
        if expanded.is_file():
            candidate = expanded.resolve()
        elif index == 0:
            resolved = shutil.which(value)
            if resolved:
                candidate = Path(resolved).resolve()
        if candidate is None and (
            index == 0 or expanded.is_absolute() or value.startswith("./") or value.startswith("../")
        ):
            raise PipelineError(f"Subject adapter artifact is unavailable: {value}")
        if candidate is not None:
            if not candidate.is_file():
                raise PipelineError(f"Subject adapter artifact is unavailable: {candidate}")
            files.append({"path": str(candidate), "sha256": sha256_file(candidate)})
    if not files:
        raise PipelineError("Subject adapter runtime has no hashable executable artifact")
    body = {
        "schema_version": "1.0",
        "adapter_id": configured["adapter_id"],
        "provider_id": configured["provider_id"],
        "model_id": configured["model_id"],
        "settings": settings,
        "settings_sha256": sha256_json(settings),
        "argv": argv,
        "argv_sha256": sha256_json(argv),
        "files": files,
    }
    return {**body, "sha256": sha256_json(body)}


def _runtime_response_contract(runtime: dict[str, Any]) -> dict[str, Any]:
    return {
        "adapter_id": runtime["adapter_id"],
        "adapter_runtime_sha256": runtime["sha256"],
        "provider_id": runtime["provider_id"],
        "model_id": runtime["model_id"],
        "settings_sha256": runtime["settings_sha256"],
        "fresh_session": True,
    }


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file() or path.is_symlink():
        raise PipelineError(f"JSONL input is missing or unsafe: {path}")
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise PipelineError(f"Invalid JSONL at {path}:{line_number}: {exc}") from exc
        if not isinstance(value, dict):
            raise PipelineError(f"JSONL row must be an object at {path}:{line_number}")
        rows.append(value)
    return rows


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")
            handle.flush()
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def validate_holdout(
    repo_root: Path,
    holdout_path: Path,
    minimum_tasks: int,
    required_domains: Sequence[str],
) -> list[dict[str, Any]]:
    require_outside(holdout_path, repo_root, "Private holdout")
    rows = read_jsonl(holdout_path)
    if len(rows) < minimum_tasks:
        raise PipelineError(f"Holdout has {len(rows)} tasks; at least {minimum_tasks} are required")
    identifiers: set[str] = set()
    domains: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, row in enumerate(rows, 1):
        identifier = row.get("task_id") or row.get("fixture_id")
        required = (
            identifier,
            row.get("domain"),
            row.get("request"),
            row.get("workspace_context"),
            row.get("expected"),
            row.get("forbidden"),
        )
        if not all(isinstance(value, str) and value.strip() for value in required):
            raise PipelineError(f"Holdout row {index} lacks a required task, context, or grader field")
        if not isinstance(row.get("hard_gates"), list) or not row["hard_gates"] or any(not isinstance(value, str) or not value for value in row["hard_gates"]):
            raise PipelineError(f"Holdout row {index} lacks grader-only hard gates")
        if identifier in identifiers:
            raise PipelineError(f"Duplicate holdout task id: {identifier}")
        identifiers.add(identifier)
        domains.add(str(row["domain"]))
        normalized.append({**row, "task_id": identifier})
    if not set(required_domains).issubset(domains):
        raise PipelineError(f"Holdout lacks required domains: {sorted(set(required_domains) - domains)}")
    return normalized


def holdout_manifest_payload(manifest: dict[str, Any]) -> bytes:
    """Return the canonical detached-signature payload for a holdout seal."""

    return canonical_json_bytes({key: value for key, value in manifest.items() if key != "signature"})


def _candidate_manifest_digest(candidate_manifest: dict[str, Any]) -> str:
    digest = candidate_manifest.get("manifest_sha256")
    body = {key: value for key, value in candidate_manifest.items() if key != "manifest_sha256"}
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
        or digest != sha256_json(body)
    ):
        raise PipelineError("Candidate manifest is missing a valid canonical manifest_sha256")
    return digest


def _build_arm_materials(repo_root: Path, config: dict[str, Any]) -> dict[str, Any]:
    professionalize_path = Path(config["candidate"]["professionalize_skill_path"]).expanduser()
    candidate_skill_path = repo_root / config["candidate"]["skill_path"] / "SKILL.md"
    for label, path in (("professionalize baseline", professionalize_path), ("candidate skill", candidate_skill_path)):
        if not path.is_file() or path.is_symlink():
            raise PipelineError(f"Frozen {label} is missing or unsafe: {path}")
    body = {
        "schema_version": "1.0",
        "B01_MIN_ADVICE": MINIMAL_ADVICE,
        "B02_PROFESSIONALIZE": professionalize_path.read_text(encoding="utf-8"),
        "C01_EXPLORE": candidate_skill_path.read_text(encoding="utf-8"),
    }
    return {**body, "sha256": sha256_json(body)}


def build_holdout_manifest_template(
    repo_root: Path,
    holdout_path: Path,
    config: dict[str, Any],
    candidate_manifest: dict[str, Any],
    *,
    manifest_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build the exact unsigned v2 seal; only its detached signature remains absent."""

    settings = config.get("holdout_verification", {})
    identity = str(settings.get("expected_identity", ""))
    namespace = str(settings.get("namespace", ""))
    if not identity or not namespace:
        raise PipelineError("Holdout signer identity and namespace must be configured before templating")
    evaluation = config["evaluation"]
    rows = validate_holdout(
        repo_root,
        holdout_path,
        int(evaluation["minimum_holdout_tasks"]),
        tuple(evaluation["required_holdout_domains"]),
    )
    protocol_path = repo_root / config["candidate"]["protocol_path"]
    rubric_path = repo_root / config["candidate"]["rubric_path"]
    for label, path in (("protocol", protocol_path), ("rubric", rubric_path)):
        if not path.is_file() or path.is_symlink():
            raise PipelineError(f"Holdout seal {label} is missing or unsafe: {path}")
    rubric = load_json(rubric_path)
    rebuilt_manifest = build_candidate_manifest(repo_root, config)
    if rebuilt_manifest != candidate_manifest:
        raise PipelineError("Candidate manifest does not match the current repository artifacts")
    arm_materials = _build_arm_materials(repo_root, config)
    subject_runtime = _subject_runtime_identity(config)
    return {
        "schema_version": "2.0",
        "manifest_id": manifest_id or f"HM-{uuid.uuid4().hex[:16]}",
        "created_at": created_at or iso_now(),
        "created_by": identity,
        "private": True,
        "sealed": True,
        "task_count": len(rows),
        "domains": sorted({str(row["domain"]) for row in rows}),
        "holdout_sha256": sha256_file(holdout_path),
        "candidate_manifest_sha256": _candidate_manifest_digest(candidate_manifest),
        "config_sha256": sha256_json(config),
        "protocol_sha256": sha256_file(protocol_path),
        "rubric_sha256": sha256_file(rubric_path),
        "rubric_content_sha256": sha256_json(rubric),
        "arm_materials_sha256": arm_materials["sha256"],
        "subject_runtime_sha256": subject_runtime["sha256"],
        "signature": {
            "algorithm": "ssh-keygen-y",
            "identity": identity,
            "namespace": namespace,
            "value": "",
        },
    }


def verify_holdout_ssh_signature(manifest: dict[str, Any], config: dict[str, Any]) -> None:
    """Verify a named holdout owner's detached OpenSSH signature."""

    settings = config.get("holdout_verification", {})
    allowed_signers = Path(str(settings.get("allowed_signers_path", "")))
    expected_identity = str(settings.get("expected_identity", ""))
    namespace = str(settings.get("namespace", ""))
    signature = manifest.get("signature", {})
    if not expected_identity or not namespace or not allowed_signers.is_file() or allowed_signers.is_symlink():
        raise PipelineError("SSH holdout verification is not fully configured")
    if signature.get("algorithm") != "ssh-keygen-y":
        raise PipelineError("Holdout signature algorithm is unsupported")
    if signature.get("identity") != expected_identity or signature.get("namespace") != namespace:
        raise PipelineError("Holdout signer identity or namespace does not match configuration")
    try:
        decoded = base64.b64decode(signature.get("value", ""), validate=True)
    except (ValueError, TypeError) as exc:
        raise PipelineError("Holdout signature is not valid base64") from exc
    with tempfile.TemporaryDirectory(prefix="explore-holdout-") as temporary:
        signature_path = Path(temporary) / "holdout.sig"
        signature_path.write_bytes(decoded)
        result = run_command(
            [
                "ssh-keygen",
                "-Y",
                "verify",
                "-f",
                str(allowed_signers),
                "-I",
                expected_identity,
                "-n",
                namespace,
                "-s",
                str(signature_path),
            ],
            input_text=holdout_manifest_payload(manifest).decode("utf-8"),
            check=False,
        )
    if result.returncode != 0:
        raise PipelineError(f"SSH holdout signature verification failed: {result.stderr.strip()}")


def _validate_external_holdout_manifest(
    repo_root: Path,
    holdout_path: Path,
    holdout_manifest_path: Path,
    rows: Sequence[dict[str, Any]],
    config: dict[str, Any],
    candidate_manifest: dict[str, Any],
    rubric: dict[str, Any],
    arm_materials: dict[str, Any],
    subject_runtime: dict[str, Any],
    *,
    signature_verifier: Callable[[dict[str, Any], dict[str, Any]], None],
) -> dict[str, Any]:
    require_outside(holdout_manifest_path, repo_root, "Signed holdout manifest")
    if not holdout_manifest_path.is_file() or holdout_manifest_path.is_symlink():
        raise PipelineError(f"Signed holdout manifest is missing or unsafe: {holdout_manifest_path}")
    manifest = load_json(holdout_manifest_path)
    required = {
        "schema_version",
        "manifest_id",
        "created_at",
        "created_by",
        "private",
        "sealed",
        "task_count",
        "domains",
        "holdout_sha256",
        "candidate_manifest_sha256",
        "config_sha256",
        "protocol_sha256",
        "rubric_sha256",
        "rubric_content_sha256",
        "arm_materials_sha256",
        "subject_runtime_sha256",
        "signature",
    }
    if set(manifest) != required:
        raise PipelineError(f"Holdout manifest fields differ from the sealed contract: {sorted(set(manifest) ^ required)}")
    if manifest.get("schema_version") != "2.0" or manifest.get("private") is not True or manifest.get("sealed") is not True:
        raise PipelineError("Holdout manifest must be a private, sealed v2 manifest")
    for key in ("manifest_id", "created_at", "created_by"):
        if not isinstance(manifest.get(key), str) or not manifest[key].strip():
            raise PipelineError(f"Holdout manifest {key} must be a non-empty string")
    signature = manifest.get("signature")
    signature_fields = {"algorithm", "identity", "namespace", "value"}
    if not isinstance(signature, dict) or set(signature) != signature_fields:
        raise PipelineError("Holdout manifest signature differs from the detached-signature contract")
    if manifest["created_by"] != signature.get("identity"):
        raise PipelineError("Holdout manifest author must match the signature identity")

    expected = {
        "task_count": len(rows),
        "domains": sorted({str(row["domain"]) for row in rows}),
        "holdout_sha256": sha256_file(holdout_path),
        "candidate_manifest_sha256": _candidate_manifest_digest(candidate_manifest),
        "config_sha256": sha256_json(config),
        "protocol_sha256": sha256_file(repo_root / config["candidate"]["protocol_path"]),
        "rubric_sha256": sha256_file(repo_root / config["candidate"]["rubric_path"]),
        "rubric_content_sha256": sha256_json(rubric),
        "arm_materials_sha256": arm_materials["sha256"],
        "subject_runtime_sha256": subject_runtime["sha256"],
    }
    for key, expected_value in expected.items():
        if manifest.get(key) != expected_value:
            raise PipelineError(f"Holdout manifest {key} does not match the frozen evidence")
    signature_verifier(manifest, config)
    return manifest


def _copy_exact(source: Path, destination: Path) -> None:
    """Atomically copy an already verified file without reserializing it."""

    if destination.exists() or destination.is_symlink():
        if (
            not destination.is_file()
            or destination.is_symlink()
            or sha256_file(destination) != sha256_file(source)
        ):
            raise PipelineError(f"Existing frozen file differs from verified input: {destination}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        shutil.copyfile(source, temporary)
        temporary.replace(destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def _persist_frozen_json(path: Path, value: dict[str, Any], label: str) -> None:
    if path.exists() or path.is_symlink():
        if not path.is_file() or path.is_symlink() or load_json(path) != value:
            raise PipelineError(f"Existing {label} does not match the input being frozen")
        return
    atomic_write_json(path, value)


def freeze_plan(
    repo_root: Path,
    run_dir: Path,
    holdout_path: Path,
    holdout_manifest_path: Path,
    config: dict[str, Any],
    candidate_manifest: dict[str, Any],
    *,
    base_commit: str,
    signature_verifier: Callable[[dict[str, Any], dict[str, Any]], None] = verify_holdout_ssh_signature,
) -> dict[str, Any]:
    require_outside(run_dir, repo_root, "Evaluation run directory")
    run_dir.mkdir(parents=True, exist_ok=True)
    if (run_dir / "plan.json").exists():
        raise PipelineError("Run directory already contains a frozen plan")
    frozen_holdout_manifest_path = run_dir / "holdout-manifest.json"
    candidate_manifest_sha256 = _candidate_manifest_digest(candidate_manifest)
    evaluation = config["evaluation"]
    rows = validate_holdout(
        repo_root,
        holdout_path,
        int(evaluation["minimum_holdout_tasks"]),
        tuple(evaluation["required_holdout_domains"]),
    )
    arms = tuple(evaluation["arms"])
    if arms != ARMS:
        raise PipelineError(f"Evaluation arms must remain {ARMS}")
    cells: list[dict[str, Any]] = []
    for task in rows:
        for trial in range(1, int(evaluation["trials_per_task"]) + 1):
            for arm in arms:
                key = f"{task['task_id']}:{trial}:{arm}"
                cells.append(
                    {
                        "cell_id": sha256_bytes(key.encode("utf-8"))[:24],
                        "task_id": task["task_id"],
                        "domain": task["domain"],
                        "trial": trial,
                        "arm": arm,
                    }
                )
    random.Random(int(evaluation["plan_seed"])).shuffle(cells)
    rubric_path = repo_root / config["candidate"]["rubric_path"]
    for label, path in (("rubric", rubric_path),):
        if not path.is_file() or path.is_symlink():
            raise PipelineError(f"Frozen {label} is missing or unsafe: {path}")
    rebuilt_manifest = build_candidate_manifest(repo_root, config)
    if rebuilt_manifest != candidate_manifest:
        raise PipelineError("Candidate manifest does not match the current repository artifacts")
    arm_materials = _build_arm_materials(repo_root, config)
    subject_runtime = _subject_runtime_identity(config)
    rubric = load_json(rubric_path)
    holdout_manifest = _validate_external_holdout_manifest(
        repo_root,
        holdout_path,
        holdout_manifest_path,
        rows,
        config,
        candidate_manifest,
        rubric,
        arm_materials,
        subject_runtime,
        signature_verifier=signature_verifier,
    )
    holdout_manifest_sha256 = sha256_file(holdout_manifest_path)
    _persist_frozen_json(run_dir / "candidate-manifest.json", candidate_manifest, "candidate manifest")
    _persist_frozen_json(run_dir / "frozen" / "config.json", config, "pipeline configuration")
    atomic_write_json(run_dir / "frozen" / "arm-materials.json", arm_materials)
    atomic_write_json(run_dir / "frozen" / "subject-runtime.json", subject_runtime)
    atomic_write_json(run_dir / "frozen" / "rubric.json", rubric)
    plan = {
        "schema_version": "1.0",
        "run_id": f"EA-{uuid.uuid4().hex[:16]}",
        "frozen_at": iso_now(),
        "base_commit": base_commit,
        "candidate_manifest_sha256": candidate_manifest_sha256,
        "holdout": {
            "path": str(holdout_path.resolve()),
            "sha256": holdout_manifest["holdout_sha256"],
            "task_count": holdout_manifest["task_count"],
            "domains": holdout_manifest["domains"],
        },
        "protocol_sha256": holdout_manifest["protocol_sha256"],
        "rubric_sha256": holdout_manifest["rubric_sha256"],
        "rubric_content_sha256": holdout_manifest["rubric_content_sha256"],
        "config_sha256": holdout_manifest["config_sha256"],
        "holdout_manifest_sha256": holdout_manifest_sha256,
        "arm_materials_sha256": arm_materials["sha256"],
        "subject_runtime_sha256": subject_runtime["sha256"],
        "trials_per_task": int(evaluation["trials_per_task"]),
        "arms": list(arms),
        "cells": cells,
    }
    plan["plan_sha256"] = sha256_json(plan)
    _copy_exact(holdout_manifest_path, frozen_holdout_manifest_path)
    if (
        sha256_file(frozen_holdout_manifest_path) != holdout_manifest_sha256
        or load_json(frozen_holdout_manifest_path) != holdout_manifest
    ):
        raise PipelineError("Frozen holdout manifest changed while it was copied")
    if sha256_file(holdout_path) != holdout_manifest["holdout_sha256"]:
        raise PipelineError("Private holdout changed while the plan was frozen")
    atomic_write_json(run_dir / "plan.json", plan)
    return plan


def _verified_plan(run_dir: Path, config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    plan = load_json(run_dir / "plan.json")
    if plan.get("plan_sha256") != sha256_json({key: value for key, value in plan.items() if key != "plan_sha256"}):
        raise PipelineError("Frozen plan hash mismatch")
    if plan.get("config_sha256") != sha256_json(config):
        raise PipelineError("Pipeline configuration or thresholds changed after freeze")
    frozen_config_path = run_dir / "frozen" / "config.json"
    if not frozen_config_path.is_file() or frozen_config_path.is_symlink():
        raise PipelineError("Frozen pipeline configuration is missing or unsafe")
    frozen_config = load_json(frozen_config_path)
    if sha256_json(frozen_config) != plan.get("config_sha256") or frozen_config != config:
        raise PipelineError("Frozen pipeline configuration changed after freeze")
    candidate_manifest_path = run_dir / "candidate-manifest.json"
    if not candidate_manifest_path.is_file() or candidate_manifest_path.is_symlink():
        raise PipelineError("Frozen candidate manifest is missing or unsafe")
    candidate_manifest = load_json(candidate_manifest_path)
    if _candidate_manifest_digest(candidate_manifest) != plan.get("candidate_manifest_sha256"):
        raise PipelineError("Frozen candidate manifest changed after freeze")
    holdout_manifest_path = run_dir / "holdout-manifest.json"
    if sha256_file(holdout_manifest_path) != plan.get("holdout_manifest_sha256"):
        raise PipelineError("Signed holdout manifest changed after freeze")
    holdout_manifest = load_json(holdout_manifest_path)
    manifest_bindings = {
        "task_count": plan["holdout"]["task_count"],
        "domains": plan["holdout"]["domains"],
        "holdout_sha256": plan["holdout"]["sha256"],
        "candidate_manifest_sha256": plan["candidate_manifest_sha256"],
        "config_sha256": plan["config_sha256"],
        "protocol_sha256": plan["protocol_sha256"],
        "rubric_sha256": plan["rubric_sha256"],
        "rubric_content_sha256": plan["rubric_content_sha256"],
        "arm_materials_sha256": plan["arm_materials_sha256"],
        "subject_runtime_sha256": plan["subject_runtime_sha256"],
    }
    for key, expected_value in manifest_bindings.items():
        if holdout_manifest.get(key) != expected_value:
            raise PipelineError(f"Signed holdout manifest {key} changed after freeze")
    arm_materials = load_json(run_dir / "frozen" / "arm-materials.json")
    arm_body = {key: value for key, value in arm_materials.items() if key != "sha256"}
    if arm_materials.get("sha256") != sha256_json(arm_body) or arm_materials.get("sha256") != plan.get("arm_materials_sha256"):
        raise PipelineError("Frozen arm materials changed after freeze")
    runtime_path = run_dir / "frozen" / "subject-runtime.json"
    if not runtime_path.is_file() or runtime_path.is_symlink():
        raise PipelineError("Frozen subject runtime is missing or unsafe")
    subject_runtime = load_json(runtime_path)
    runtime_body = {key: value for key, value in subject_runtime.items() if key != "sha256"}
    if (
        subject_runtime.get("sha256") != sha256_json(runtime_body)
        or subject_runtime.get("sha256") != plan.get("subject_runtime_sha256")
        or subject_runtime != _subject_runtime_identity(config)
    ):
        raise PipelineError("Frozen subject runtime or adapter artifact changed after freeze")
    rubric = load_json(run_dir / "frozen" / "rubric.json")
    if sha256_json(rubric) != plan.get("rubric_content_sha256"):
        raise PipelineError("Frozen rubric changed after freeze")
    holdout_path = Path(plan["holdout"]["path"])
    if sha256_file(holdout_path) != plan["holdout"]["sha256"]:
        raise PipelineError("Private holdout changed after freeze")
    return plan, arm_materials


def verify_frozen_holdout_signature(
    run_dir: Path,
    config: dict[str, Any],
    *,
    signature_verifier: Callable[[dict[str, Any], dict[str, Any]], None] = verify_holdout_ssh_signature,
) -> None:
    """Recheck custody authority using the operator-supplied trust policy."""

    _verified_plan(run_dir, config)
    manifest = load_json(run_dir / "holdout-manifest.json")
    if manifest.get("created_by") != (manifest.get("signature") or {}).get("identity"):
        raise PipelineError("Frozen holdout author and signature identity differ")
    signature_verifier(manifest, config)


def _task_index(holdout_path: Path) -> dict[str, dict[str, Any]]:
    rows = read_jsonl(holdout_path)
    return {str(row.get("task_id") or row.get("fixture_id")): row for row in rows}


def _arm_prompt(arm: str, task: dict[str, Any], arm_materials: dict[str, Any]) -> str:
    request = str(task["request"])
    if arm == "B00_RAW":
        return request
    if arm == "B01_MIN_ADVICE":
        return str(arm_materials["B01_MIN_ADVICE"]) + request
    if arm == "B02_PROFESSIONALIZE":
        return str(arm_materials["B02_PROFESSIONALIZE"]) + "\n\nUser request:\n" + request
    if arm == "C01_EXPLORE":
        return str(arm_materials["C01_EXPLORE"]) + "\n\nUser request:\n" + request
    raise PipelineError(f"Unknown arm: {arm}")


def _adapter_argv(template: Sequence[str], request_path: Path, response_path: Path) -> list[str]:
    if not template:
        raise PipelineError("Adapter argv is not configured")
    replacements = {"{input}": str(request_path), "{output}": str(response_path)}
    return [replacements.get(part, part) for part in template]


def _subject_request(
    plan: dict[str, Any],
    cell: dict[str, Any],
    task: dict[str, Any],
    arm_materials: dict[str, Any],
    subject_runtime: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "adapter_kind": "subject",
        "run_id": plan["run_id"],
        "plan_sha256": plan["plan_sha256"],
        "cell": {key: value for key, value in cell.items() if key != "arm"},
        "prompt": _arm_prompt(cell["arm"], task, arm_materials),
        "workspace_context": task["workspace_context"],
        "expected_runtime": _runtime_response_contract(subject_runtime),
    }


def _artifact_file(value: Any, root: Path, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise PipelineError(f"Persisted {label} path is missing")
    path = Path(value)
    resolved_root = root.resolve()
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise PipelineError(f"Persisted {label} is missing or unsafe: {path}")
    resolved = path.resolve()
    if path != resolved:
        raise PipelineError(f"Persisted {label} traverses a symlink or alias: {path}")
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise PipelineError(f"Persisted {label} escapes its attempt directory: {path}") from exc
    return resolved


def _verify_attempt_artifacts(
    attempts: Any,
    attempt_root: Path,
    *,
    expected_request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(attempts, list) or not attempts:
        raise PipelineError("Result has no persisted adapter attempts")
    final_response: dict[str, Any] | None = None
    for expected_attempt, returned_record in enumerate(attempts, 1):
        if not isinstance(returned_record, dict) or returned_record.get("attempt") != expected_attempt:
            raise PipelineError("Persisted adapter attempts are malformed or out of order")
        record_path = _artifact_file(returned_record.get("record_path"), attempt_root, "attempt record")
        if returned_record.get("record_sha256") != sha256_file(record_path):
            raise PipelineError(f"Persisted adapter attempt record hash mismatch: {record_path}")
        stored_record = load_json(record_path)
        expected_record = {
            key: value
            for key, value in returned_record.items()
            if key not in {"record_path", "record_sha256"}
        }
        if stored_record != expected_record:
            raise PipelineError(f"Persisted adapter attempt record differs from the result envelope: {record_path}")

        request_path = _artifact_file(stored_record.get("request_path"), attempt_root, "adapter request")
        if request_path.parent != record_path.parent:
            raise PipelineError(f"Persisted adapter request and attempt record are not colocated: {request_path}")
        if stored_record.get("request_sha256") != sha256_file(request_path):
            raise PipelineError(f"Persisted adapter request hash mismatch: {request_path}")
        request_record = load_json(request_path)
        if (
            request_record.get("request_id") != stored_record.get("request_id")
            or request_record.get("attempt") != expected_attempt
        ):
            raise PipelineError(f"Persisted adapter request binding mismatch: {request_path}")
        if expected_request is not None:
            request_body = {
                key: value
                for key, value in request_record.items()
                if key not in {"attempt", "request_id"}
            }
            if request_body != expected_request:
                raise PipelineError(f"Persisted adapter request differs from the frozen cell request: {request_path}")

        normalized_path = _artifact_file(
            stored_record.get("normalized_response_path"), attempt_root, "normalized adapter response"
        )
        if normalized_path.parent != record_path.parent:
            raise PipelineError(f"Persisted normalized response and attempt record are not colocated: {normalized_path}")
        if stored_record.get("normalized_response_sha256") != sha256_file(normalized_path):
            raise PipelineError(f"Persisted normalized adapter response hash mismatch: {normalized_path}")
        normalized = load_json(normalized_path)
        if (
            normalized.get("status") != stored_record.get("status")
            or (normalized.get("telemetry") if isinstance(normalized.get("telemetry"), dict) else None)
            != stored_record.get("telemetry")
        ):
            raise PipelineError(f"Persisted normalized adapter response disagrees with its attempt record: {normalized_path}")

        raw_path_value = stored_record.get("raw_response_path")
        raw_hash = stored_record.get("raw_response_sha256")
        if raw_path_value is None:
            expected_raw_path = request_path.parent / "response.json"
            if raw_hash is not None or expected_raw_path.exists() or expected_raw_path.is_symlink():
                raise PipelineError(f"Persisted raw adapter response presence is inconsistent: {request_path.parent}")
        else:
            raw_path = _artifact_file(raw_path_value, attempt_root, "raw adapter response")
            if raw_path.parent != record_path.parent:
                raise PipelineError(f"Persisted raw response and attempt record are not colocated: {raw_path}")
            if raw_hash != sha256_file(raw_path) or stored_record.get("response_sha256") != raw_hash:
                raise PipelineError(f"Persisted raw adapter response hash mismatch: {raw_path}")
            if normalized.get("status") == "completed":
                raw_response = load_json(raw_path)
                if raw_response != normalized:
                    raise PipelineError(f"Completed raw and normalized adapter responses differ: {raw_path}")

        if normalized.get("status") == "completed":
            if stored_record.get("returncode") != 0 or not isinstance(normalized.get("output"), dict):
                raise PipelineError(f"Completed adapter response has an invalid process outcome: {normalized_path}")
            if (
                normalized.get("request_id") != stored_record.get("request_id")
                or normalized.get("request_sha256") != stored_record.get("request_sha256")
            ):
                raise PipelineError(f"Completed adapter response is not bound to its persisted request: {normalized_path}")
            runtime_contract = request_record.get("expected_runtime")
            if runtime_contract is not None and normalized.get("runtime") != runtime_contract:
                raise PipelineError(f"Completed adapter response runtime identity mismatch: {normalized_path}")
        final_response = normalized
    if final_response is None:
        raise PipelineError("Result has no verifiable final adapter response")
    return final_response


def _verify_result_cell(
    run_dir: Path,
    plan: dict[str, Any],
    cell: dict[str, Any],
    result: dict[str, Any],
    expected_request: dict[str, Any],
) -> None:
    result_body = {key: value for key, value in result.items() if key != "result_sha256"}
    if result.get("result_sha256") != sha256_json(result_body):
        raise PipelineError(f"Result envelope hash mismatch: {cell['cell_id']}")
    if result.get("plan_sha256") != plan["plan_sha256"] or result.get("cell") != cell:
        raise PipelineError(f"Result cell is not bound to the frozen plan: {cell['cell_id']}")
    final_response = _verify_attempt_artifacts(
        result.get("attempts"),
        run_dir / "attempts" / cell["cell_id"],
        expected_request=expected_request,
    )
    if result.get("response") != final_response:
        raise PipelineError(f"Result response differs from the persisted final attempt: {cell['cell_id']}")
    expected_status = "completed" if final_response.get("status") == "completed" else "failed"
    if result.get("status") != expected_status:
        raise PipelineError(f"Result status differs from the persisted final attempt: {cell['cell_id']}")


def invoke_adapter(
    template: Sequence[str],
    request: dict[str, Any],
    attempt_dir: Path,
    *,
    timeout_seconds: float,
    max_transient_retries: int,
    max_output_bytes: int = 1_000_000,
    env_allowlist: Sequence[str] = ("PATH", "TMPDIR", "LANG", "LC_ALL"),
) -> dict[str, Any]:
    attempt_dir = attempt_dir.resolve()
    attempt_dir.mkdir(parents=True, exist_ok=True)
    attempts: list[dict[str, Any]] = []
    for attempt in range(1, max_transient_retries + 2):
        invocation_id = uuid.uuid4().hex
        invocation_dir = (attempt_dir / f"attempt-{attempt}-{invocation_id}").resolve()
        invocation_dir.mkdir(parents=True, exist_ok=False)
        request_path = invocation_dir / "request.json"
        response_path = invocation_dir / "response.json"
        request_id = f"REQ-{uuid.uuid4().hex}"
        request_record = {**request, "attempt": attempt, "request_id": request_id}
        atomic_write_json(request_path, request_record)
        request_sha256 = sha256_file(request_path)
        started = time.monotonic()
        argv = _adapter_argv(template, request_path, response_path)
        try:
            completed = run_command(
                argv,
                cwd=invocation_dir,
                timeout=timeout_seconds,
                check=False,
                env={key: os.environ[key] for key in env_allowlist if key in os.environ},
                inherit_env=False,
            )
        except subprocess.TimeoutExpired as exc:
            completed = subprocess.CompletedProcess(argv, 124, exc.stdout or "", exc.stderr or "adapter timed out")
        except OSError as exc:
            completed = subprocess.CompletedProcess(argv, 127, "", str(exc))
        elapsed_ms = round((time.monotonic() - started) * 1000, 3)
        response: dict[str, Any]
        if response_path.is_symlink():
            raise PipelineError(f"Adapter produced an unsafe response path: {response_path}")
        raw_response_path = str(response_path.resolve()) if response_path.is_file() else None
        raw_response_sha256 = sha256_file(response_path) if response_path.is_file() else None
        error_prefix = {
            "schema_version": "1.0",
            "request_id": request_id,
            "request_sha256": request_sha256,
        }
        if response_path.is_file() and response_path.stat().st_size > max_output_bytes:
            response = {**error_prefix, "status": "permanent_error", "error": "adapter response exceeds max_output_bytes"}
        elif response_path.is_file() and not response_path.is_symlink():
            try:
                response = load_json(response_path)
            except (json.JSONDecodeError, OSError, PipelineError) as exc:
                response = {**error_prefix, "status": "permanent_error", "error": str(exc)}
        else:
            response = {
                **error_prefix,
                "status": "transient_error" if completed.returncode in {75, 124} else "permanent_error",
                "error": (completed.stderr or completed.stdout or "adapter produced no response")[-4000:],
            }
        if response_path.is_file() and (
            response.get("request_id") != request_id or response.get("request_sha256") != request_sha256
        ):
            response = {
                **error_prefix,
                "status": "permanent_error",
                "error": "adapter response is not bound to the fresh request",
            }
        expected_runtime = request.get("expected_runtime")
        if response.get("status") == "completed" and expected_runtime is not None and response.get("runtime") != expected_runtime:
            response = {
                **error_prefix,
                "status": "permanent_error",
                "error": "adapter response does not prove the frozen runtime and a fresh session",
            }
        if response.get("status") == "completed" and completed.returncode != 0:
            response = {
                **error_prefix,
                "status": "permanent_error",
                "error": "adapter reported completion with a nonzero process exit",
            }
        if response.get("status") == "completed" and not isinstance(response.get("output"), dict):
            response = {
                **error_prefix,
                "status": "permanent_error",
                "error": "completed adapter response must contain an output object",
            }
        if response.get("status") not in {"completed", "transient_error", "permanent_error"}:
            response = {
                **error_prefix,
                "status": "permanent_error",
                "error": "adapter response has an invalid status",
            }
        status = response.get("status")
        normalized_response_path = invocation_dir / "normalized-response.json"
        atomic_write_json(normalized_response_path, response)
        record = {
            "attempt": attempt,
            "returncode": completed.returncode,
            "elapsed_ms": elapsed_ms,
            "request_id": request_id,
            "request_path": str(request_path.resolve()),
            "request_sha256": request_sha256,
            "raw_response_path": raw_response_path,
            "raw_response_sha256": raw_response_sha256,
            "response_sha256": raw_response_sha256,
            "normalized_response_path": str(normalized_response_path.resolve()),
            "normalized_response_sha256": sha256_file(normalized_response_path),
            "status": status,
            "telemetry": response.get("telemetry") if isinstance(response.get("telemetry"), dict) else None,
        }
        record_path = invocation_dir / "attempt-record.json"
        atomic_write_json(record_path, record)
        attempts.append(
            {
                **record,
                "record_path": str(record_path.resolve()),
                "record_sha256": sha256_file(record_path),
            }
        )
        if status == "completed" and completed.returncode == 0:
            return {"status": "completed", "response": response, "attempts": attempts}
        if status != "transient_error" or attempt > max_transient_retries:
            return {"status": "failed", "response": response, "attempts": attempts}
    raise AssertionError("unreachable")


def run_subjects(repo_root: Path, run_dir: Path, config: dict[str, Any]) -> dict[str, int]:
    plan, arm_materials = _verified_plan(run_dir, config)
    holdout_path = Path(plan["holdout"]["path"])
    tasks = _task_index(holdout_path)
    subject_runtime = load_json(run_dir / "frozen" / "subject-runtime.json")
    result_dir = run_dir / "results" / "cells"
    completed_count = failed_count = resumed_count = 0
    for cell in plan["cells"]:
        target = result_dir / f"{cell['cell_id']}.json"
        task = tasks[cell["task_id"]]
        request = _subject_request(plan, cell, task, arm_materials, subject_runtime)
        if target.is_symlink():
            raise PipelineError(f"Existing result cell is unsafe: {target}")
        if target.is_file():
            existing = load_json(target)
            _verify_result_cell(run_dir, plan, cell, existing, request)
            if existing.get("status") == "completed":
                resumed_count += 1
            else:
                failed_count += 1
            continue
        result = invoke_adapter(
            config["evaluation"]["subject_adapter_argv"],
            request,
            run_dir / "attempts" / cell["cell_id"],
            timeout_seconds=float(config["evaluation"]["timeout_ms"]) / 1000,
            max_transient_retries=int(config["evaluation"]["max_transient_retries"]),
            max_output_bytes=int(config["evaluation"].get("max_output_bytes", 1_000_000)),
            env_allowlist=tuple(config["evaluation"].get("adapter_env_allowlist", ("PATH", "TMPDIR", "LANG", "LC_ALL"))),
        )
        result_body = {
            "schema_version": "1.0",
            "plan_sha256": plan["plan_sha256"],
            "cell": cell,
            **result,
        }
        result_record = {**result_body, "result_sha256": sha256_json(result_body)}
        atomic_write_json(target, result_record)
        _verify_result_cell(run_dir, plan, cell, result_record, request)
        if result["status"] == "completed":
            completed_count += 1
        else:
            failed_count += 1
    return {"completed": completed_count, "failed": failed_count, "resumed": resumed_count}


def build_blind_bundle(run_dir: Path, config: dict[str, Any]) -> dict[str, Any]:
    plan, arm_materials = _verified_plan(run_dir, config)
    tasks = _task_index(Path(plan["holdout"]["path"]))
    subject_runtime = load_json(run_dir / "frozen" / "subject-runtime.json")
    groups: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for cell in plan["cells"]:
        groups[(cell["task_id"], int(cell["trial"]))].append(cell)
    records: list[dict[str, Any]] = []
    mapping: list[dict[str, Any]] = []
    for (task_id, trial), cells in sorted(groups.items()):
        if {cell["arm"] for cell in cells} != set(ARMS):
            raise PipelineError(f"Blind group lacks a complete four-arm match: {task_id}:{trial}")
        packet_id = sha256_bytes(f"packet:{config['evaluation']['blind_seed']}:{task_id}:{trial}".encode())[:24]
        candidates: list[dict[str, Any]] = []
        for cell in cells:
            result_path = run_dir / "results" / "cells" / f"{cell['cell_id']}.json"
            if not result_path.is_file() or result_path.is_symlink():
                raise PipelineError(f"Missing result cell: {cell['cell_id']}")
            result = load_json(result_path)
            request = _subject_request(plan, cell, tasks[cell["task_id"]], arm_materials, subject_runtime)
            _verify_result_cell(run_dir, plan, cell, result, request)
            if result.get("status") != "completed":
                raise PipelineError(f"Cannot blind invalid result cell: {cell['cell_id']}")
            candidate_id = sha256_bytes(f"candidate:{config['evaluation']['blind_seed']}:{cell['cell_id']}".encode())[:24]
            candidates.append({"candidate_id": candidate_id, "output": result["response"]["output"]})
            mapping.append(
                {
                    "packet_id": packet_id,
                    "candidate_id": candidate_id,
                    "cell_id": cell["cell_id"],
                    "task_id": task_id,
                    "trial": trial,
                    "arm": cell["arm"],
                }
            )
        random.Random(f"{config['evaluation']['blind_seed']}:{packet_id}").shuffle(candidates)
        task = tasks[task_id]
        records.append(
            {
                "schema_version": "2.0",
                "packet_id": packet_id,
                "task_id": task_id,
                "domain": cells[0]["domain"],
                "trial": trial,
                "request": task["request"],
                "workspace_context": task["workspace_context"],
                "grader_context": {
                    "expected": task["expected"],
                    "hard_gates": task["hard_gates"],
                    "forbidden": task["forbidden"],
                },
                "candidates": candidates,
            }
        )
    random.Random(int(config["evaluation"]["blind_seed"])).shuffle(records)
    write_jsonl(run_dir / "grading" / "blind-packet.jsonl", records)
    write_jsonl(run_dir / "private" / "blind-map.jsonl", mapping)
    return {
        "records": len(records),
        "candidates": len(mapping),
        "packet_sha256": sha256_file(run_dir / "grading" / "blind-packet.jsonl"),
    }


def run_provisional_grading(run_dir: Path, config: dict[str, Any]) -> dict[str, int]:
    plan, _ = _verified_plan(run_dir, config)
    packet = read_jsonl(run_dir / "grading" / "blind-packet.jsonl")
    rubric = load_json(run_dir / "frozen" / "rubric.json")
    output: list[dict[str, Any]] = []
    failures = 0
    for record in packet:
        for replicate in range(1, int(config["evaluation"]["grader_replicates"]) + 1):
            request = {
                "schema_version": "1.0",
                "adapter_kind": "grader",
                "blind_record": record,
                "rubric": rubric,
                "replicate": replicate,
            }
            result = invoke_adapter(
                config["evaluation"]["grader_adapter_argv"],
                request,
                run_dir / "grading" / "attempts" / record["blind_id"] / str(replicate),
                timeout_seconds=float(config["evaluation"]["timeout_ms"]) / 1000,
                max_transient_retries=int(config["evaluation"]["max_transient_retries"]),
                max_output_bytes=int(config["evaluation"].get("max_output_bytes", 1_000_000)),
                env_allowlist=tuple(config["evaluation"].get("adapter_env_allowlist", ("PATH", "TMPDIR", "LANG", "LC_ALL"))),
            )
            if result["status"] != "completed":
                failures += 1
            output.append({"blind_id": record["blind_id"], "replicate": replicate, **result})
    write_jsonl(run_dir / "grading" / "provisional-grades.jsonl", output)
    return {"grades": len(output), "failures": failures}


def _percentile(values: list[float], q: float) -> float:
    if not values:
        raise PipelineError("Cannot compute a percentile without observations")
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] * (upper - position) + ordered[upper] * (position - lower)


def _cluster_interval(
    task_values: dict[str, float],
    *,
    seed: int,
    samples: int,
    statistic: Callable[[Iterable[float]], float] = statistics.fmean,
) -> dict[str, float]:
    if len(task_values) < 2:
        raise PipelineError("At least two task clusters are required for confidence bounds")
    keys = sorted(task_values)
    rng = random.Random(seed)
    draws = [statistic(task_values[rng.choice(keys)] for _ in keys) for _ in range(samples)]
    return {
        "estimate": statistic(task_values.values()),
        "lower95": _percentile(draws, 0.025),
        "upper95": _percentile(draws, 0.975),
    }


def _attempt_resource(result: dict[str, Any], resource: str) -> float | None:
    attempts = result.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        return None
    if resource == "latency":
        values = [attempt.get("elapsed_ms") for attempt in attempts]
    elif resource == "tokens":
        values = []
        for attempt in attempts:
            telemetry = attempt.get("telemetry")
            if not isinstance(telemetry, dict):
                return None
            input_tokens = telemetry.get("input_tokens")
            output_tokens = telemetry.get("output_tokens")
            if not isinstance(input_tokens, (int, float)) or isinstance(input_tokens, bool) or not isinstance(output_tokens, (int, float)) or isinstance(output_tokens, bool):
                return None
            values.append(float(input_tokens) + float(output_tokens))
    else:
        raise PipelineError(f"Unknown attempt resource: {resource}")
    if any(not isinstance(value, (int, float)) or isinstance(value, bool) for value in values):
        return None
    return sum(float(value) for value in values)


def _rubric_dimension_weights(rubric: dict[str, Any]) -> dict[str, float]:
    dimensions = rubric.get("dimensions")
    if not isinstance(dimensions, list) or not dimensions:
        raise PipelineError("Frozen rubric has no scored dimensions")
    weights: dict[str, float] = {}
    for dimension in dimensions:
        identifier = dimension.get("id") if isinstance(dimension, dict) else None
        weight = dimension.get("weight") if isinstance(dimension, dict) else None
        if (
            not isinstance(identifier, str)
            or not identifier
            or identifier in weights
            or not isinstance(weight, (int, float))
            or isinstance(weight, bool)
            or not math.isfinite(float(weight))
            or float(weight) <= 0
        ):
            raise PipelineError("Frozen rubric dimensions or weights are invalid")
        weights[identifier] = float(weight)
    return weights


def _computed_grade_score(grade: dict[str, Any], weights: dict[str, float], candidate_id: str) -> float:
    dimension_scores = grade.get("dimension_scores")
    if not isinstance(dimension_scores, dict) or set(dimension_scores) != set(weights):
        raise PipelineError(f"Final grade lacks the exact rubric dimension map: {candidate_id}")
    ordered_ids = sorted(weights)
    scores: list[float] = []
    for identifier in ordered_ids:
        value = dimension_scores[identifier]
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(float(value))
            or not 0 <= float(value) <= 4
        ):
            raise PipelineError(f"Final grade has an invalid 0-4 dimension score: {candidate_id}:{identifier}")
        scores.append(float(value))
    computed = math.fsum(scores[index] * weights[identifier] for index, identifier in enumerate(ordered_ids)) / math.fsum(
        weights[identifier] for identifier in ordered_ids
    )
    supplied = grade.get("score")
    if supplied is not None and (
        not isinstance(supplied, (int, float))
        or isinstance(supplied, bool)
        or not math.isfinite(float(supplied))
        or not math.isclose(float(supplied), computed, rel_tol=0.0, abs_tol=1e-12)
    ):
        raise PipelineError(f"Final aggregate score disagrees with the rubric dimensions: {candidate_id}")
    return computed


def _interval_or_empty(
    task_values: dict[str, float],
    *,
    seed: int,
    samples: int,
    statistic: Callable[[Iterable[float]], float] = statistics.fmean,
) -> dict[str, float]:
    try:
        return _cluster_interval(task_values, seed=seed, samples=samples, statistic=statistic)
    except (PipelineError, statistics.StatisticsError, ZeroDivisionError):
        return {}


def build_summary(run_dir: Path, config: dict[str, Any], final_grades_path: Path, review_path: Path) -> dict[str, Any]:
    plan, arm_materials = _verified_plan(run_dir, config)
    tasks = _task_index(Path(plan["holdout"]["path"]))
    subject_runtime = load_json(run_dir / "frozen" / "subject-runtime.json")
    mapping_rows = read_jsonl(run_dir / "private" / "blind-map.jsonl")
    expected_cells = {cell["cell_id"]: cell for cell in plan["cells"]}
    expected_packets = {
        sha256_bytes(f"packet:{config['evaluation']['blind_seed']}:{cell['task_id']}:{cell['trial']}".encode())[:24]
        for cell in plan["cells"]
    }
    mapping: dict[str, dict[str, Any]] = {}
    mapped_cells: set[str] = set()
    packet_candidates: dict[str, set[str]] = defaultdict(set)
    for row in mapping_rows:
        candidate_id = row.get("candidate_id")
        packet_id = row.get("packet_id")
        cell_id = row.get("cell_id")
        cell = expected_cells.get(str(cell_id))
        expected_candidate_id = sha256_bytes(f"candidate:{config['evaluation']['blind_seed']}:{cell_id}".encode())[:24]
        expected_packet_id = (
            sha256_bytes(f"packet:{config['evaluation']['blind_seed']}:{cell['task_id']}:{cell['trial']}".encode())[:24]
            if cell is not None
            else None
        )
        if (
            cell is None
            or candidate_id != expected_candidate_id
            or packet_id != expected_packet_id
            or row.get("arm") != cell["arm"]
            or row.get("task_id") != cell["task_id"]
            or row.get("trial") != cell["trial"]
        ):
            raise PipelineError("Blind mapping is inconsistent with the frozen plan")
        if candidate_id in mapping or str(cell_id) in mapped_cells:
            raise PipelineError("Blind mapping contains a duplicate")
        mapping[str(candidate_id)] = row
        packet_candidates[str(packet_id)].add(str(candidate_id))
        mapped_cells.add(str(cell_id))
    if mapped_cells != set(expected_cells) or set(packet_candidates) != expected_packets or any(len(values) != len(ARMS) for values in packet_candidates.values()):
        raise PipelineError("Blind mapping does not cover every frozen four-arm packet")
    grades = read_jsonl(final_grades_path)
    review = load_json(review_path)
    if review.get("grades_sha256") != sha256_file(final_grades_path):
        raise PipelineError("Human review is not bound to the final grade file")
    if not isinstance(review.get("reviewer"), str) or not review["reviewer"].strip():
        raise PipelineError("Human review lacks a named reviewer")
    rubric = load_json(run_dir / "frozen" / "rubric.json")
    dimension_weights = _rubric_dimension_weights(rubric)
    required_gates = set(rubric.get("hard_gates", []))
    critical_gates = set(config["evaluation"].get("critical_gate_ids", DEFAULT_CRITICAL_GATES))
    if not required_gates or not critical_gates or not critical_gates.issubset(required_gates):
        raise PipelineError("Frozen rubric or critical-gate configuration is invalid")
    grade_by_cell: dict[str, dict[str, Any]] = {}
    explicit_preferences: dict[tuple[str, int], float | None] = {}
    graded_packets: set[str] = set()
    for group_grade in grades:
        packet_id = group_grade.get("packet_id")
        if packet_id not in packet_candidates or packet_id in graded_packets:
            raise PipelineError(f"Unknown or duplicate final grade packet: {packet_id}")
        if group_grade.get("adjudicated") is not True:
            raise PipelineError(f"Final grade packet is not adjudicated: {packet_id}")
        candidate_grades = group_grade.get("candidate_grades")
        if not isinstance(candidate_grades, list):
            raise PipelineError(f"Final packet lacks candidate grades: {packet_id}")
        seen_candidates: set[str] = set()
        for grade in candidate_grades:
            candidate_id = grade.get("candidate_id") if isinstance(grade, dict) else None
            if candidate_id not in packet_candidates[packet_id] or candidate_id in seen_candidates:
                raise PipelineError(f"Unknown or duplicate candidate grade: {candidate_id}")
            computed_score = _computed_grade_score(grade, dimension_weights, str(candidate_id))
            gates = grade.get("hard_gates")
            if not isinstance(gates, dict) or set(gates) != required_gates or any(not isinstance(value, bool) for value in gates.values()):
                raise PipelineError(f"Final grade lacks the exact boolean hard gates: {candidate_id}")
            expected_critical = any(gates[name] is False for name in critical_gates)
            if grade.get("critical_failure") is not expected_critical:
                raise PipelineError(f"Critical failure flag disagrees with hard gates: {candidate_id}")
            if not isinstance(grade.get("rationale"), str) or not grade["rationale"].strip():
                raise PipelineError(f"Final grade lacks rationale: {candidate_id}")
            cell_id = mapping[candidate_id]["cell_id"]
            grade_by_cell[cell_id] = {**grade, "score": computed_score, **mapping[candidate_id]}
            seen_candidates.add(candidate_id)
        if seen_candidates != packet_candidates[packet_id]:
            raise PipelineError(f"Final packet does not grade all four candidates: {packet_id}")
        ranking = group_grade.get("ranking")
        if not isinstance(ranking, list) or not ranking or any(not isinstance(tier, list) or not tier for tier in ranking):
            raise PipelineError(f"Final packet lacks an explicit ranking: {packet_id}")
        flattened = [candidate_id for tier in ranking for candidate_id in tier]
        if len(flattened) != len(set(flattened)) or set(flattened) != packet_candidates[packet_id]:
            raise PipelineError(f"Final packet ranking is incomplete or duplicated: {packet_id}")
        rank_by_candidate = {candidate_id: rank for rank, tier in enumerate(ranking) for candidate_id in tier}
        by_arm = {mapping[candidate_id]["arm"]: candidate_id for candidate_id in packet_candidates[packet_id]}
        left_rank = rank_by_candidate[by_arm["C01_EXPLORE"]]
        right_rank = rank_by_candidate[by_arm["B01_MIN_ADVICE"]]
        first_mapping = mapping[next(iter(packet_candidates[packet_id]))]
        explicit_preferences[(first_mapping["task_id"], int(first_mapping["trial"]))] = (
            None if left_rank == right_rank else float(left_rank < right_rank)
        )
        graded_packets.add(str(packet_id))

    results: dict[str, dict[str, Any]] = {}
    failed = 0
    usage_complete = True
    for cell in plan["cells"]:
        path = run_dir / "results" / "cells" / f"{cell['cell_id']}.json"
        if not path.is_file() or path.is_symlink():
            failed += 1
            continue
        result = load_json(path)
        request = _subject_request(plan, cell, tasks[cell["task_id"]], arm_materials, subject_runtime)
        _verify_result_cell(run_dir, plan, cell, result, request)
        results[cell["cell_id"]] = result
        if result.get("status") != "completed":
            failed += 1
        attempts = result.get("attempts")
        usage_complete = usage_complete and isinstance(attempts, list) and bool(attempts)
        if isinstance(attempts, list):
            for attempt in attempts:
                telemetry = attempt.get("telemetry")
                usage_complete = usage_complete and isinstance(attempt.get("elapsed_ms"), (int, float)) and isinstance(telemetry, dict)
                if isinstance(telemetry, dict):
                    usage_complete = usage_complete and all(
                        isinstance(telemetry.get(key), (int, float)) and not isinstance(telemetry.get(key), bool)
                        for key in ("input_tokens", "output_tokens", "cost_usd")
                    )

    task_arm_scores: dict[tuple[str, str], list[float]] = defaultdict(list)
    domain_arm_scores: dict[tuple[str, str], list[float]] = defaultdict(list)
    critical_failures = 0
    other_gate_trials = other_gate_passes = 0
    for cell in plan["cells"]:
        grade = grade_by_cell.get(cell["cell_id"])
        if grade is None:
            continue
        task_arm_scores[(cell["task_id"], cell["arm"])].append(float(grade["score"]))
        domain_arm_scores[(cell["domain"], cell["arm"])].append(float(grade["score"]))
        if cell["arm"] == "C01_EXPLORE":
            if grade.get("critical_failure") is True:
                critical_failures += 1
            gates = grade.get("hard_gates")
            if isinstance(gates, dict):
                noncritical = [passed for name, passed in gates.items() if name not in critical_gates]
                other_gate_trials += 1
                other_gate_passes += int(bool(noncritical) and all(noncritical))

    task_diff_b01: dict[str, float] = {}
    task_diff_b02: dict[str, float] = {}
    task_preference: dict[str, float] = {}
    for task_id in sorted({cell["task_id"] for cell in plan["cells"]}):
        c01 = task_arm_scores.get((task_id, "C01_EXPLORE"), [])
        b01 = task_arm_scores.get((task_id, "B01_MIN_ADVICE"), [])
        b02 = task_arm_scores.get((task_id, "B02_PROFESSIONALIZE"), [])
        if c01 and b01 and b02:
            task_diff_b01[task_id] = statistics.fmean(c01) - statistics.fmean(b01)
            task_diff_b02[task_id] = statistics.fmean(c01) - statistics.fmean(b02)
            preferences = []
            for trial in range(1, int(plan["trials_per_task"]) + 1):
                preference = explicit_preferences.get((task_id, trial))
                if preference is not None:
                    preferences.append(preference)
            if preferences:
                task_preference[task_id] = statistics.fmean(preferences)

    resource_ratios: dict[str, dict[str, float]] = {"latency": {}, "tokens": {}}
    expected_trials = int(plan["trials_per_task"])
    for task_id in sorted({cell["task_id"] for cell in plan["cells"]}):
        for key in ("latency", "tokens"):
            values: dict[str, list[float]] = defaultdict(list)
            for cell in plan["cells"]:
                if cell["task_id"] != task_id or cell["arm"] not in {"C01_EXPLORE", "B01_MIN_ADVICE"}:
                    continue
                value = _attempt_resource(results.get(cell["cell_id"], {}), key)
                if isinstance(value, (int, float)):
                    values[cell["arm"]].append(float(value))
            if len(values["C01_EXPLORE"]) != expected_trials or len(values["B01_MIN_ADVICE"]) != expected_trials:
                usage_complete = False
                continue
            denominator = statistics.fmean(values["B01_MIN_ADVICE"])
            if not math.isfinite(denominator) or denominator <= 0:
                usage_complete = False
                continue
            numerator = statistics.fmean(values["C01_EXPLORE"])
            if not math.isfinite(numerator) or numerator < 0:
                usage_complete = False
                continue
            resource_ratios[key][task_id] = numerator / denominator

    seed = int(config["evaluation"]["bootstrap_seed"])
    samples = int(config["evaluation"]["bootstrap_resamples"])
    preference_interval = _interval_or_empty(task_preference, seed=seed + 2, samples=samples)
    latency_interval = _interval_or_empty(
        resource_ratios["latency"], seed=seed + 3, samples=samples, statistic=statistics.median
    )
    token_interval = _interval_or_empty(
        resource_ratios["tokens"], seed=seed + 4, samples=samples, statistic=statistics.median
    )
    quality = {
        "critical_candidate_failures": critical_failures,
        "other_hard_gate_pass_rate": other_gate_passes / other_gate_trials if other_gate_trials else None,
        "c01_minus_b01": _interval_or_empty(task_diff_b01, seed=seed, samples=samples),
        "c01_minus_b02": _interval_or_empty(task_diff_b02, seed=seed + 1, samples=samples),
        "c01_vs_b01_preference": {
            **preference_interval,
            **({"rate": statistics.fmean(task_preference.values())} if task_preference else {}),
        },
        "domain_deltas": {
            domain: statistics.fmean(domain_arm_scores[(domain, "C01_EXPLORE")])
            - statistics.fmean(domain_arm_scores[(domain, "B01_MIN_ADVICE")])
            for domain in plan["holdout"]["domains"]
            if domain_arm_scores[(domain, "C01_EXPLORE")] and domain_arm_scores[(domain, "B01_MIN_ADVICE")]
        },
    }
    resources = {
        "usage_complete": usage_complete,
        "latency_ratio": {
            **latency_interval,
            **({"median": statistics.median(resource_ratios["latency"].values())} if resource_ratios["latency"] else {}),
        },
        "token_ratio": {
            **token_interval,
            **({"median": statistics.median(resource_ratios["tokens"].values())} if resource_ratios["tokens"] else {}),
        },
    }
    analysis_coverage = {
        "expected_task_clusters": int(plan["holdout"]["task_count"]),
        "c01_minus_b01_task_clusters": len(task_diff_b01),
        "c01_minus_b02_task_clusters": len(task_diff_b02),
        "preference_task_clusters": len(task_preference),
        "latency_ratio_task_clusters": len(resource_ratios["latency"]),
        "token_ratio_task_clusters": len(resource_ratios["tokens"]),
    }

    summary = {
        "schema_version": "1.0",
        "run_id": plan["run_id"],
        "completed_at": iso_now(),
        "plan_sha256": plan["plan_sha256"],
        "integrity": {
            "valid": review.get("integrity_valid") is True,
            "contamination_detected": review.get("contamination_detected") is True,
        },
        "coverage": {
            "tasks": plan["holdout"]["task_count"],
            "trials_per_task": plan["trials_per_task"],
            "expected_cells": len(plan["cells"]),
            "complete_cells": len(results),
            "final_graded_cells": len(grade_by_cell),
            "expected_comparisons": plan["holdout"]["task_count"] * plan["trials_per_task"],
            "final_comparisons": len(graded_packets),
            "failed_cells": failed,
            "expected_domains": plan["holdout"]["domains"],
            "human_final": review.get("human_final") is True,
            "adjudication_complete": review.get("adjudication_complete") is True,
        },
        "quality": quality,
        "resources": resources,
        "analysis_coverage": analysis_coverage,
        "evidence": {
            "final_grades_sha256": sha256_file(final_grades_path),
            "human_review_sha256": sha256_file(review_path),
            "holdout_manifest_sha256": sha256_file(run_dir / "holdout-manifest.json"),
        },
    }
    atomic_write_json(run_dir / "evaluation-summary.json", summary)
    return summary
