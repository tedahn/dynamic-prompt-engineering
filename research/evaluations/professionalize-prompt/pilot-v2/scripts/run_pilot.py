#!/usr/bin/env python3
"""Execute the frozen professionalize-prompt Pilot V2 without grading it.

The runner is deliberately limited to experiment planning, isolated Codex CLI
execution, and content-addressed evidence capture.  It never interprets answer
quality or computes rubric scores.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import difflib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import random
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterable, NamedTuple, Sequence


SCHEMA_VERSION = "2.0"
PILOT_ROOT = Path(__file__).resolve().parents[1]
LAB_ROOT = PILOT_ROOT.parent
FIXTURES_PATH = PILOT_ROOT / "fixtures" / "pilot-fixtures-v2.jsonl"
ARTIFACTS_PATH = PILOT_ROOT / "fixtures" / "pilot-artifacts-v2.json"
WORKFLOWS_PATH = PILOT_ROOT / "workflows" / "workflows-pilot-v2.json"
RUBRIC_PATH = PILOT_ROOT / "rubrics" / "pilot-rubric-v2.json"
EXPERIMENT_PATH = PILOT_ROOT / "experiments" / "EXP-PP-V2-PILOT.json"
SPEC_PATH = PILOT_ROOT / "PILOT_EXECUTION_SPEC.md"
README_PATH = PILOT_ROOT / "README.md"
SNAPSHOT_DIR = LAB_ROOT / "snapshots" / "2026-07-28-eec246d1"
SNAPSHOT_MANIFEST_PATH = SNAPSHOT_DIR / "snapshot-manifest.json"

DEFAULT_CLI_PATH = Path("/Applications/ChatGPT.app/Contents/Resources/codex")
NO_TOOL_CWD = Path("/private/var/empty")
REQUESTED_MODEL = "gpt-5.6-sol"
REASONING_EFFORT = "high"
DEFAULT_PLAN_SEED = 20260728
DEFAULT_BLIND_SEED = 7282026
MAX_ALLOWED_RETRIES = 2
DEFAULT_TIMEOUT_SECONDS = 600.0
RETRY_BACKOFF_SECONDS = (5.0, 15.0)
PLAN_CANONICALIZATION = "pilot-v2-scored-plan-execution-v1"
WORKFLOW_IDS = ("B00_RAW_1CALL", "B01_STATIC_MIN_1CALL", "B04_PRO_INLINE_1CALL")
FIXTURE_IDS = ("FX-ED-01", "FX-CD-02", "FX-RS-03", "FX-DA-03", "FX-CR-04")
FIXED_CLI_FLAGS = (
    "--ephemeral",
    "--ignore-user-config",
    "--ignore-rules",
    "--skip-git-repo-check",
    "--json",
    "--ask-for-approval=never",
)
FROZEN_ARTIFACT_PATHS = (
    "PILOT_EXECUTION_SPEC.md",
    "PROTOCOL_AMENDMENT.md",
    "README.md",
    "fixtures/pilot-fixtures-v2.jsonl",
    "fixtures/pilot-artifacts-v2.json",
    "workflows/workflows-pilot-v2.json",
    "rubrics/pilot-rubric-v2.json",
    "rubrics/model-grader-output-schema-v2.json",
    "scripts/run_pilot.py",
    "scripts/grade_pilot.py",
    "tests/test_run_pilot.py",
    "tests/test_grade_pilot.py",
)

# Frozen with the Pilot V2 owner.  Workspace-policy cells keep only the three
# shell features below; no-tool cells disable those as well.
COMMON_FEATURE_DISABLES = (
    "apps",
    "auth_elicitation",
    "browser_use",
    "browser_use_external",
    "browser_use_full_cdp_access",
    "code_mode_host",
    "computer_use",
    "goals",
    "guardian_approval",
    "hooks",
    "image_generation",
    "in_app_browser",
    "memories",
    "multi_agent",
    "plugin_sharing",
    "plugins",
    "remote_plugin",
    "skill_mcp_dependency_install",
    "skill_search",
    "tool_call_mcp_elicitation",
    "tool_search_always_defer_mcp_tools",
    "tool_suggest",
    "workspace_dependencies",
)
NONE_POLICY_FEATURE_DISABLES = ("shell_snapshot", "shell_tool", "unified_exec")

TRANSIENT_PATTERNS = (
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b429\b",
        r"rate[ -]?limit",
        r"temporar(?:y|ily) unavailable",
        r"try again",
        r"timed? out",
        r"timeout",
        r"connection (?:reset|refused|closed)",
        r"network error",
        r"transport error",
        r"stream (?:disconnected|closed)",
        r"overloaded",
        r"\b50[0234]\b",
    )
)
TRANSIENT_PATTERNS = tuple(TRANSIENT_PATTERNS)
FATAL_RUNTIME_PATTERNS = (
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"model .* not found",
        r"unsupported model",
        r"authentication",
        r"unauthorized",
        r"login required",
        r"invalid configuration",
        r"unknown feature",
        r"unrecognized feature",
    )
)
FATAL_RUNTIME_PATTERNS = tuple(FATAL_RUNTIME_PATTERNS)
MAX_DIFF_TEXT_BYTES = 1_000_000


class PilotError(RuntimeError):
    """A frozen-run invariant failed."""


class PilotInputs(NamedTuple):
    fixtures: list[dict[str, Any]]
    artifacts: dict[str, dict[str, Any]]
    workflows: list[dict[str, Any]]
    common_envelope: str
    rubric: dict[str, Any]
    workflow_registry: dict[str, Any]
    artifact_registry: dict[str, Any]
    snapshot_manifest: dict[str, Any]
    snapshot_skill: str
    snapshot_reference: str
    experiment: dict[str, Any]


class WorkspaceCapture(NamedTuple):
    public: dict[str, Any]
    contents: dict[str, bytes | None]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PilotError(f"Expected JSON object: {path}")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise PilotError(f"Expected object on {path}:{line_number}")
        rows.append(value)
    return rows


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_bytes(path, canonical_json_bytes(value))


def atomic_write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    material = b"".join(canonical_json_bytes(row) for row in rows)
    atomic_write_bytes(path, material)


def load_pilot_inputs() -> PilotInputs:
    fixtures = load_jsonl(FIXTURES_PATH)
    artifact_registry = load_json(ARTIFACTS_PATH)
    workflow_registry = load_json(WORKFLOWS_PATH)
    rubric = load_json(RUBRIC_PATH)
    experiment = load_json(EXPERIMENT_PATH)
    snapshot_manifest = load_json(SNAPSHOT_MANIFEST_PATH)
    workflows = workflow_registry.get("workflows")
    artifacts = artifact_registry.get("artifacts")
    if not isinstance(workflows, list) or not isinstance(artifacts, dict):
        raise PilotError("Malformed Pilot V2 workflow or artifact registry")
    return PilotInputs(
        fixtures=fixtures,
        artifacts=artifacts,
        workflows=workflows,
        common_envelope=str(workflow_registry.get("common_envelope", "")),
        rubric=rubric,
        workflow_registry=workflow_registry,
        artifact_registry=artifact_registry,
        snapshot_manifest=snapshot_manifest,
        snapshot_skill=(SNAPSHOT_DIR / "SKILL.md").read_text(encoding="utf-8"),
        snapshot_reference=(
            SNAPSHOT_DIR / "references" / "gpt-5p6-sol-prompting.md"
        ).read_text(encoding="utf-8"),
        experiment=experiment,
    )


def _safe_artifact_path(value: str) -> bool:
    path = PurePosixPath(value)
    return bool(value) and not path.is_absolute() and ".." not in path.parts and "." not in path.parts


def canonical_scored_plan_sha256(rows: Sequence[dict[str, Any]]) -> str:
    """Hash execution order and cell content while excluding run/blinding identities."""
    excluded = {"run_id", "cell_dir", "blind_id", "blind_order"}
    canonical_rows = [
        {key: value for key, value in row.items() if key not in excluded}
        for row in rows
    ]
    payload = {
        "canonicalization": PLAN_CANONICALIZATION,
        "rows": canonical_rows,
    }
    return sha256_bytes(canonical_json_bytes(payload))


def _frozen_artifact_errors(experiment: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    entries = experiment.get("frozen_artifacts")
    if not isinstance(entries, list):
        return ["Experiment frozen_artifacts must be an ordered list"]
    paths: list[str] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"Frozen artifact entry {index} must be an object")
            continue
        if set(entry) != {"path", "sha256", "bytes"}:
            errors.append(
                f"Frozen artifact entry {index} must contain exactly path, sha256, and bytes"
            )
        relative = entry.get("path")
        if not isinstance(relative, str) or not _safe_artifact_path(relative):
            errors.append(f"Unsafe frozen artifact path: {relative}")
            continue
        paths.append(relative)
        if relative == EXPERIMENT_PATH.relative_to(PILOT_ROOT).as_posix():
            errors.append("Experiment must not self-freeze in frozen_artifacts")
            continue
        path = PILOT_ROOT / PurePosixPath(relative)
        if path.is_symlink() or not path.is_file():
            errors.append(f"Missing or symlinked frozen artifact: {relative}")
            continue
        expected_hash = entry.get("sha256")
        expected_bytes = entry.get("bytes")
        if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            errors.append(f"Frozen artifact has invalid SHA-256: {relative}")
        elif sha256_file(path) != expected_hash:
            errors.append(f"Frozen artifact hash mismatch: {relative}")
        if not isinstance(expected_bytes, int) or isinstance(expected_bytes, bool):
            errors.append(f"Frozen artifact has invalid byte count: {relative}")
        elif path.stat().st_size != expected_bytes:
            errors.append(f"Frozen artifact byte-count mismatch: {relative}")
    if len(paths) != len(set(paths)):
        errors.append("Frozen artifact paths must be unique")
    if paths != list(FROZEN_ARTIFACT_PATHS):
        errors.append("Frozen artifact paths do not match the required ordered V2 package")
    return errors


def _experiment_errors(inputs: PilotInputs) -> list[str]:
    experiment = inputs.experiment
    errors: list[str] = []
    if experiment.get("schema_version") != SCHEMA_VERSION:
        errors.append("Experiment schema version mismatch")
    if experiment.get("experiment_id") != "EXP-PP-V2-PILOT":
        errors.append("Unexpected experiment ID")
    if experiment.get("status") != "pilot-authorized-frozen":
        errors.append("Experiment is not pilot-authorized-frozen")
    for field in ("authorized_at", "authorization_evidence", "owner", "pilot_approver"):
        if not isinstance(experiment.get(field), str) or not experiment[field].strip():
            errors.append(f"Experiment authorization field is missing: {field}")
    boundary = experiment.get("execution_boundary")
    if not isinstance(boundary, dict):
        errors.append("Experiment execution_boundary must be an object")
        boundary = {}
    if boundary.get("data_boundary_approved") is not True:
        errors.append("Experiment data boundary is not approved")
    if boundary.get("budget_approved") is not True:
        errors.append("Experiment budget is not approved")
    if boundary.get("network") != "Forbidden":
        errors.append("Experiment must forbid network access")
    if boundary.get("external_side_effects") != "Forbidden":
        errors.append("Experiment must forbid external side effects")
    if experiment.get("full_study_authorized") is not False:
        errors.append("Pilot runner requires full_study_authorized=false")

    target = experiment.get("target_surface")
    if not isinstance(target, dict):
        errors.append("Experiment target_surface must be an object")
        target = {}
    if target.get("model_alias") != REQUESTED_MODEL:
        errors.append("Experiment model alias drift")
    if target.get("reasoning_effort") != REASONING_EFFORT:
        errors.append("Experiment reasoning effort drift")
    if target.get("fixed_cli_flags") != list(FIXED_CLI_FLAGS):
        errors.append("Experiment fixed CLI flags drift")
    if target.get("common_disabled_features") != list(COMMON_FEATURE_DISABLES):
        errors.append("Experiment common disabled features drift")
    if target.get("additional_no_tool_disabled_features") != list(
        NONE_POLICY_FEATURE_DISABLES
    ):
        errors.append("Experiment no-tool disabled features drift")

    pilot = experiment.get("pilot")
    if not isinstance(pilot, dict):
        errors.append("Experiment pilot must be an object")
        pilot = {}
    expected_pilot = {
        "fixture_ids": list(FIXTURE_IDS),
        "workflow_ids": list(WORKFLOW_IDS),
        "trials": 3,
        "execution_cells": 45,
        "execution_seed": DEFAULT_PLAN_SEED,
        "grade_seed": DEFAULT_BLIND_SEED,
        "concurrency": 1,
    }
    for key, expected in expected_pilot.items():
        if pilot.get(key) != expected:
            errors.append(f"Experiment pilot field drift: {key}")
    preflight = experiment.get("preflight")
    if not isinstance(preflight, dict):
        errors.append("Experiment preflight must be an object")
        preflight = {}
    expected_preflight = generate_preflight_plan(inputs, "CANONICAL-PREFLIGHT")
    expected_fixture_ids = [row["fixture_id"] for row in expected_preflight]
    expected_pairs = [
        {"workflow_id": row["workflow_id"], "fixture_id": row["fixture_id"]}
        for row in expected_preflight
    ]
    expected_tool_policies = [row["tool_policy"] for row in expected_preflight]
    if preflight.get("fixture_ids") != expected_fixture_ids:
        errors.append("Experiment preflight fixture order drift")
    if preflight.get("workflow_ids") != [row["workflow_id"] for row in expected_preflight]:
        errors.append("Experiment preflight workflow order drift")
    if preflight.get("workflow_fixture_pairs") != expected_pairs:
        errors.append("Experiment preflight workflow-fixture pair drift")
    if preflight.get("tool_policies") != expected_tool_policies:
        errors.append("Experiment preflight tool-policy drift")
    if preflight.get("cells") != 3 or preflight.get("excluded_from_scores") is not True:
        errors.append("Experiment preflight count or exclusion drift")
    retry = experiment.get("retry_policy")
    if not isinstance(retry, dict):
        errors.append("Experiment retry_policy must be an object")
        retry = {}
    if retry.get("maximum_retries") != MAX_ALLOWED_RETRIES:
        errors.append("Experiment maximum retries drift")
    if retry.get("maximum_attempts") != MAX_ALLOWED_RETRIES + 1:
        errors.append("Experiment maximum attempts drift")
    if retry.get("per_attempt_timeout_seconds") != DEFAULT_TIMEOUT_SECONDS:
        errors.append("Experiment per-attempt timeout drift")
    if retry.get("backoff_seconds") != list(RETRY_BACKOFF_SECONDS):
        errors.append("Experiment retry backoff drift")

    expected_hash = pilot.get("expected_plan_sha256")
    if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        errors.append("Experiment expected_plan_sha256 is not frozen")
    else:
        rows, _ = generate_scored_plan(
            inputs,
            "CANONICAL-RUN",
            plan_seed=DEFAULT_PLAN_SEED,
            blind_seed=DEFAULT_BLIND_SEED,
        )
        if canonical_scored_plan_sha256(rows) != expected_hash:
            errors.append("Experiment canonical scored-plan hash mismatch")
    if experiment.get("skill_snapshot_id") != inputs.snapshot_manifest.get("snapshot_id"):
        errors.append("Experiment skill snapshot ID drift")
    if experiment.get("skill_bundle_sha256") != inputs.snapshot_manifest.get("bundle_sha256"):
        errors.append("Experiment skill bundle hash drift")
    errors.extend(_frozen_artifact_errors(experiment))
    return errors


def validate_pilot_inputs(inputs: PilotInputs) -> list[str]:
    errors: list[str] = []
    if len(inputs.fixtures) != 5:
        errors.append("Pilot V2 must contain exactly five fixtures")
    fixture_ids = [row.get("fixture_id") for row in inputs.fixtures]
    if len(set(fixture_ids)) != len(fixture_ids):
        errors.append("Fixture IDs must be unique")
    workflow_ids = [row.get("workflow_id") for row in inputs.workflows]
    if tuple(workflow_ids) != WORKFLOW_IDS:
        errors.append(f"Workflow registry must contain exactly {WORKFLOW_IDS!r} in order")
    if any(row.get("calls") != 1 for row in inputs.workflows):
        errors.append("Every Pilot V2 workflow must be a one-call workflow")
    if not inputs.common_envelope.strip():
        errors.append("Workflow common envelope is empty")
    if {row.get("mode") for row in inputs.fixtures} != {"default", "prompt-only", "execute-only"}:
        errors.append("Fixtures must cover default, prompt-only, and execute-only modes")
    if {row.get("tool_policy") for row in inputs.fixtures} != {"none", "workspace"}:
        errors.append("Fixtures must cover none and workspace tool policies")
    if len({row.get("domain") for row in inputs.fixtures}) != 5:
        errors.append("Pilot fixtures must cover five distinct domains")
    rubric_checks = {
        row.get("id")
        for row in inputs.rubric.get("task_checks", [])
        if isinstance(row, dict)
    }
    for fixture in inputs.fixtures:
        fixture_id = fixture.get("fixture_id", "<unknown>")
        artifact_key = fixture.get("artifact_key")
        if artifact_key not in inputs.artifacts:
            errors.append(f"{fixture_id} references unknown artifact key: {artifact_key}")
            continue
        files = inputs.artifacts[artifact_key].get("files", {})
        if not isinstance(files, dict):
            errors.append(f"Artifact {artifact_key} files must be an object")
        else:
            for relative_path, content in files.items():
                if not _safe_artifact_path(relative_path):
                    errors.append(f"Unsafe artifact path: {relative_path}")
                if not isinstance(content, str):
                    errors.append(f"Artifact content must be text: {relative_path}")
        missing_checks = set(fixture.get("task_checks", [])) - rubric_checks
        if missing_checks:
            errors.append(f"{fixture_id} has checks absent from rubric: {sorted(missing_checks)}")

    manifest = inputs.snapshot_manifest
    if manifest.get("snapshot_id") != "professionalize-prompt@2026-07-28-eec246d1":
        errors.append("Unexpected frozen skill snapshot ID")
    bundle_lines: list[str] = []
    for entry in manifest.get("files", []):
        if not isinstance(entry, dict):
            errors.append("Snapshot file entry must be an object")
            continue
        relative = entry.get("snapshot_path")
        if not isinstance(relative, str) or not _safe_artifact_path(relative):
            errors.append(f"Unsafe snapshot path: {relative}")
            continue
        path = SNAPSHOT_DIR / relative
        if not path.is_file():
            errors.append(f"Missing snapshot file: {relative}")
            continue
        actual = sha256_file(path)
        if actual != entry.get("sha256"):
            errors.append(f"Snapshot hash mismatch: {relative}")
        bundle_lines.append(f"{relative}:{actual}")
    if bundle_lines:
        bundle = sha256_bytes("\n".join(sorted(bundle_lines)).encode("utf-8"))
        if bundle != manifest.get("bundle_sha256"):
            errors.append("Snapshot bundle hash mismatch")

    pro = next(
        (row for row in inputs.workflows if row.get("workflow_id") == "B04_PRO_INLINE_1CALL"),
        None,
    )
    if pro is None or pro.get("skill_snapshot_id") != manifest.get("snapshot_id"):
        errors.append("B04 does not reference the frozen snapshot")
    elif pro:
        for key in ("skill_entrypoint", "skill_reference"):
            value = pro.get(key)
            path = (WORKFLOWS_PATH.parent / str(value)).resolve()
            if not path.is_file() or not path.is_relative_to(SNAPSHOT_DIR.resolve()):
                errors.append(f"B04 {key} escapes or misses frozen snapshot")
    errors.extend(_experiment_errors(inputs))
    return errors


def source_paths(inputs: PilotInputs) -> list[Path]:
    paths = [EXPERIMENT_PATH, SNAPSHOT_MANIFEST_PATH]
    paths.extend(PILOT_ROOT / PurePosixPath(relative) for relative in FROZEN_ARTIFACT_PATHS)
    for entry in inputs.snapshot_manifest.get("files", []):
        if isinstance(entry, dict) and isinstance(entry.get("snapshot_path"), str):
            paths.append(SNAPSHOT_DIR / entry["snapshot_path"])
    return list(dict.fromkeys(paths))


def compute_source_hashes(inputs: PilotInputs) -> dict[str, str]:
    return {
        path.resolve().relative_to(LAB_ROOT.resolve()).as_posix(): sha256_file(path)
        for path in sorted(source_paths(inputs))
    }


def build_prompt(
    inputs: PilotInputs, fixture: dict[str, Any], workflow: dict[str, Any]
) -> str:
    parts = [inputs.common_envelope.strip()]
    artifact = inputs.artifacts[fixture["artifact_key"]]
    authorized_paths = sorted(artifact.get("files", {}))
    if fixture["tool_policy"] == "none":
        parts.append(
            "<tool_policy>Do not call tools, execute commands, inspect files, or use network "
            "services. Work only from the supplied request and context.</tool_policy>"
        )
    else:
        path_list = ", ".join(authorized_paths) if authorized_paths else "(none)"
        parts.append(
            "<tool_policy>The current directory is an isolated synthetic workspace. You may use "
            f"shell commands only to read these authorized paths: {path_list}. Do not write, "
            "edit, delete, upload, or access network or external services.</tool_policy>"
        )
    instruction = str(workflow.get("condition_instruction", "")).strip()
    if instruction:
        parts.append(f"<condition_instruction>\n{instruction}\n</condition_instruction>")
    if workflow["workflow_id"] == "B04_PRO_INLINE_1CALL":
        parts.append(f"<frozen_skill>\n{inputs.snapshot_skill.rstrip()}\n</frozen_skill>")
        parts.append(
            f"<frozen_model_reference>\n{inputs.snapshot_reference.rstrip()}\n"
            "</frozen_model_reference>"
        )
    parts.append(f"<user_request>\n{fixture['request']}\n</user_request>")
    parts.append(f"<user_context>\n{fixture['context']}\n</user_context>")
    return "\n\n".join(parts).rstrip() + "\n"


def generate_scored_plan(
    inputs: PilotInputs,
    run_id: str,
    plan_seed: int = DEFAULT_PLAN_SEED,
    blind_seed: int = DEFAULT_BLIND_SEED,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    fixtures = list(inputs.fixtures)
    random.Random(plan_seed).shuffle(fixtures)
    workflow_map = {row["workflow_id"]: row for row in inputs.workflows}
    rows: list[dict[str, Any]] = []
    execution_index = 0
    for fixture_index, fixture in enumerate(fixtures):
        for trial in range(1, 4):
            latin_row = (fixture_index + trial - 1) % len(WORKFLOW_IDS)
            ordered = WORKFLOW_IDS[latin_row:] + WORKFLOW_IDS[:latin_row]
            for latin_position, workflow_id in enumerate(ordered):
                execution_index += 1
                prompt = build_prompt(inputs, fixture, workflow_map[workflow_id])
                rows.append(
                    {
                        "schema_version": SCHEMA_VERSION,
                        "run_id": run_id,
                        "phase": "scored",
                        "discarded": False,
                        "execution_index": execution_index,
                        "cell_id": f"CELL-{execution_index:03d}",
                        "fixture_id": fixture["fixture_id"],
                        "fixture_revision": fixture["fixture_revision"],
                        "fixture_index": fixture_index,
                        "workflow_id": workflow_id,
                        "workflow_index": WORKFLOW_IDS.index(workflow_id),
                        "trial": trial,
                        "latin_row": latin_row,
                        "latin_position": latin_position,
                        "tool_policy": fixture["tool_policy"],
                        "artifact_key": fixture["artifact_key"],
                        "blind_id": None,
                        "blind_order": None,
                        "prompt_sha256": sha256_bytes(prompt.encode("utf-8")),
                        "cell_dir": f"cells/CELL-{execution_index:03d}",
                    }
                )

    blind_rng = random.Random(blind_seed)
    blind_ids = [f"ANON-{index:03d}" for index in range(1, len(rows) + 1)]
    blind_rng.shuffle(blind_ids)
    id_iter = iter(blind_ids)
    groups: dict[str, Any] = {}
    private_mapping: dict[str, str] = {}
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((row["fixture_id"], row["trial"]), []).append(row)
    group_keys = sorted(grouped)
    blind_rng.shuffle(group_keys)
    base_workflow_order = list(WORKFLOW_IDS)
    blind_rng.shuffle(base_workflow_order)
    for group_index, (fixture_id, trial) in enumerate(group_keys):
        latin_row = group_index % len(WORKFLOW_IDS)
        presentation_order = (
            base_workflow_order[latin_row:] + base_workflow_order[:latin_row]
        )
        rows_by_workflow = {
            row["workflow_id"]: row for row in grouped[(fixture_id, trial)]
        }
        group_rows = [rows_by_workflow[workflow_id] for workflow_id in presentation_order]
        ordered_blind_ids: list[str] = []
        mapping: dict[str, str] = {}
        for blind_order, row in enumerate(group_rows, 1):
            blind_id = next(id_iter)
            row["blind_id"] = blind_id
            row["blind_order"] = blind_order
            ordered_blind_ids.append(blind_id)
            mapping[blind_id] = row["cell_id"]
            private_mapping[blind_id] = row["cell_id"]
        group_id = f"{fixture_id}::trial-{trial}"
        groups[group_id] = {
            "fixture_id": fixture_id,
            "trial": trial,
            "ordered_blind_ids": ordered_blind_ids,
            "private_mapping": mapping,
        }
    blind_map = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "plan_seed": plan_seed,
        "blind_seed": blind_seed,
        "presentation_design": "balanced-latin-v1",
        "groups": groups,
        "private_mapping": private_mapping,
    }
    rows.sort(key=lambda row: row["execution_index"])
    return rows, blind_map


def generate_preflight_plan(inputs: PilotInputs, run_id: str) -> list[dict[str, Any]]:
    workflow_map = {row["workflow_id"]: row for row in inputs.workflows}
    none_fixture = next(row for row in inputs.fixtures if row["tool_policy"] == "none")
    workspace_fixtures = [row for row in inputs.fixtures if row["tool_policy"] == "workspace"]
    fixture_choices = (none_fixture, workspace_fixtures[0], workspace_fixtures[-1])
    rows: list[dict[str, Any]] = []
    for index, (workflow_id, fixture) in enumerate(zip(WORKFLOW_IDS, fixture_choices), 1):
        prompt = build_prompt(inputs, fixture, workflow_map[workflow_id])
        rows.append(
            {
                "schema_version": SCHEMA_VERSION,
                "run_id": run_id,
                "phase": "preflight",
                "discarded": True,
                "execution_index": index,
                "cell_id": f"PREFLIGHT-{index:03d}",
                "fixture_id": fixture["fixture_id"],
                "fixture_revision": fixture["fixture_revision"],
                "fixture_index": inputs.fixtures.index(fixture),
                "workflow_id": workflow_id,
                "workflow_index": WORKFLOW_IDS.index(workflow_id),
                "trial": 0,
                "latin_row": None,
                "latin_position": index - 1,
                "tool_policy": fixture["tool_policy"],
                "artifact_key": fixture["artifact_key"],
                "blind_id": None,
                "blind_order": None,
                "prompt_sha256": sha256_bytes(prompt.encode("utf-8")),
                "cell_dir": f"preflight/PREFLIGHT-{index:03d}",
            }
        )
    return rows


def build_codex_command(
    cli_path: Path, codex_home: Path, tool_policy: str, cwd: Path
) -> list[str]:
    del codex_home  # Authentication is selected through the process environment.
    if tool_policy not in {"none", "workspace"}:
        raise PilotError(f"Unknown tool policy: {tool_policy}")
    sandbox = "read-only" if tool_policy == "none" else "workspace-write"
    disabled = list(COMMON_FEATURE_DISABLES)
    if tool_policy == "none":
        disabled.extend(NONE_POLICY_FEATURE_DISABLES)
    command = [
        str(cli_path),
        "--ask-for-approval",
        "never",
        "exec",
        "--model",
        REQUESTED_MODEL,
        "--config",
        f'model_reasoning_effort="{REASONING_EFFORT}"',
        "--config",
        "project_doc_max_bytes=0",
        "--config",
        'shell_environment_policy.exclude=["CODEX_HOME"]',
        "--strict-config",
        "--sandbox",
        sandbox,
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--skip-git-repo-check",
        "--json",
        "--color",
        "never",
        "--cd",
        str(cwd),
    ]
    for feature in disabled:
        command.extend(("--disable", feature))
    command.append("-")
    return command


def isolated_environment(
    codex_home: Path,
    runtime_root: Path,
    *,
    temporary_dir: Path | None = None,
    tool_readable_roots: Sequence[Path] = (),
) -> dict[str, str]:
    try:
        source_home = codex_home.resolve(strict=True)
        source_auth = (source_home / "auth.json").resolve(strict=True)
        resolved_runtime_root = runtime_root.resolve(strict=True)
        resolved_tool_roots = [root.resolve(strict=True) for root in tool_readable_roots]
    except (OSError, RuntimeError) as exc:
        raise PilotError("Authentication boundary contains an unresolvable path") from exc
    if not source_auth.is_file():
        raise PilotError("Authentication source must resolve to a regular file")

    effective_home = resolved_runtime_root / "codex-home"
    tool_temp = (temporary_dir or runtime_root / "tool-tmp").resolve()
    tool_home = tool_temp / "home"

    protected_paths = (source_home, source_auth, effective_home)
    for resolved_tool_root in resolved_tool_roots:
        if any(
            candidate == resolved_tool_root
            or candidate.is_relative_to(resolved_tool_root)
            or resolved_tool_root.is_relative_to(candidate)
            for candidate in protected_paths
        ):
            raise PilotError("Authentication home overlaps a tool-readable root")
        aliases = [path for path in resolved_tool_root.rglob("*") if path.is_symlink()]
        for alias in aliases:
            try:
                target = alias.resolve(strict=True)
            except (OSError, RuntimeError) as exc:
                raise PilotError("Tool-readable root contains an unresolvable alias") from exc
            if any(
                target == protected
                or target.is_relative_to(protected)
                or protected.is_relative_to(target)
                for protected in (source_home, source_auth)
            ):
                raise PilotError(
                    "Tool-readable root contains an alias to authentication material"
                )

    effective_home.mkdir(parents=True, exist_ok=True)
    tool_home.mkdir(parents=True, exist_ok=True)
    isolated_auth = effective_home / "auth.json"
    if not isolated_auth.exists():
        isolated_auth.symlink_to((source_home / "auth.json").resolve())
    return {
        "CODEX_HOME": str(effective_home),
        "HOME": str(tool_home),
        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TERM": "dumb",
        "NO_COLOR": "1",
        "TMPDIR": str(tool_temp),
    }


def inspect_runtime(cli_path: Path, codex_home: Path) -> dict[str, Any]:
    errors: list[str] = []
    cli_path = cli_path.resolve()
    codex_home = codex_home.resolve()
    if not cli_path.is_file() or not os.access(cli_path, os.X_OK):
        errors.append(f"Codex CLI is not executable: {cli_path}")
    if not codex_home.is_dir():
        errors.append(f"CODEX_HOME is not a directory: {codex_home}")
    if codex_home == (Path.home() / ".codex").resolve():
        errors.append("CODEX_HOME must be isolated; the user's normal ~/.codex is forbidden")
    if not (codex_home / "auth.json").is_file():
        errors.append("Isolated CODEX_HOME must contain auth.json")
    forbidden_entries = ("AGENTS.md", "config.toml", "hooks.json", "skills", "plugins", "memories")
    present_forbidden = [name for name in forbidden_entries if (codex_home / name).exists()]
    if present_forbidden:
        errors.append(f"Isolated CODEX_HOME contains forbidden entries: {present_forbidden}")
    if not NO_TOOL_CWD.is_dir():
        errors.append(f"No-tool working directory is missing: {NO_TOOL_CWD}")
    else:
        if list(NO_TOOL_CWD.iterdir()):
            errors.append(f"No-tool working directory is not empty: {NO_TOOL_CWD}")
        if os.access(NO_TOOL_CWD, os.W_OK):
            errors.append(f"No-tool working directory is writable: {NO_TOOL_CWD}")
    cli_version = "unknown"
    cli_sha256: str | None = None
    cli_bytes: int | None = None
    feature_names: set[str] = set()
    auth_ready = False
    auth_mode = "unknown"
    if not errors:
        cli_sha256 = sha256_file(cli_path)
        cli_bytes = cli_path.stat().st_size
        inspection_root = Path(tempfile.mkdtemp(prefix="pilot-v2-runtime-inspect-"))
        try:
            env = isolated_environment(codex_home, inspection_root)
            version = subprocess.run(
                [str(cli_path), "--version"],
                check=False,
                capture_output=True,
                text=True,
                env=env,
                timeout=15,
            )
            if version.returncode != 0:
                errors.append("Codex CLI version check failed")
            else:
                cli_version = version.stdout.strip().splitlines()[0][:200]
            login = subprocess.run(
                [str(cli_path), "login", "status"],
                check=False,
                capture_output=True,
                text=True,
                env=env,
                timeout=15,
            )
            login_material = f"{login.stdout}\n{login.stderr}".casefold()
            auth_mode = "chatgpt" if "chatgpt" in login_material else "other"
            auth_ready = login.returncode == 0 and auth_mode == "chatgpt"
            if not auth_ready:
                errors.append("Codex CLI is not authenticated with ChatGPT in isolated CODEX_HOME")
            features = subprocess.run(
                [str(cli_path), "features", "list"],
                check=False,
                capture_output=True,
                text=True,
                env=env,
                timeout=15,
            )
            if features.returncode != 0:
                errors.append("Codex feature registry check failed")
            else:
                for line in features.stdout.splitlines():
                    match = re.match(r"^(\S+)\s+.+\s+(?:true|false)$", line.strip())
                    if match:
                        feature_names.add(match.group(1))
                required = set(COMMON_FEATURE_DISABLES) | set(NONE_POLICY_FEATURE_DISABLES)
                missing = sorted(required - feature_names)
                if missing:
                    errors.append(f"CLI feature registry is missing frozen controls: {missing}")
        except (OSError, subprocess.SubprocessError, PilotError) as exc:
            errors.append(f"Runtime readiness check failed: {type(exc).__name__}")
        finally:
            shutil.rmtree(inspection_root, ignore_errors=True)
    return {
        "ok": not errors,
        "errors": errors,
        "cli_path": str(cli_path),
        "cli_version": cli_version,
        "cli_sha256": cli_sha256,
        "cli_bytes": cli_bytes,
        "codex_home": str(codex_home),
        "auth_ready": auth_ready,
        "auth_mode": auth_mode,
        "feature_registry_sha256": sha256_bytes("\n".join(sorted(feature_names)).encode("utf-8")),
        "no_tool_cwd": str(NO_TOOL_CWD),
    }


def validate_runtime_against_experiment(
    inputs: PilotInputs, runtime: dict[str, Any]
) -> list[str]:
    errors: list[str] = []
    target = inputs.experiment.get("target_surface", {})
    if not isinstance(target, dict):
        return ["Experiment target_surface must be an object"]
    expected_path = target.get("cli_path")
    if not isinstance(expected_path, str) or Path(expected_path).resolve() != Path(
        runtime.get("cli_path", "")
    ).resolve():
        errors.append("Runtime CLI path differs from frozen experiment")
    for field in ("cli_version", "cli_sha256", "cli_bytes"):
        if runtime.get(field) != target.get(field):
            errors.append(f"Runtime {field} differs from frozen experiment")
    if runtime.get("auth_mode") != "chatgpt":
        errors.append("Runtime authentication mode is not ChatGPT")
    return errors


def capture_workspace(root: Path) -> WorkspaceCapture:
    root = root.resolve()
    files: list[dict[str, Any]] = []
    contents: dict[str, bytes | None] = {}
    if root.exists():
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                target = os.readlink(path)
                files.append(
                    {
                        "path": relative,
                        "type": "symlink",
                        "target": target,
                        "sha256": sha256_bytes(target.encode("utf-8", errors="surrogateescape")),
                    }
                )
                contents[relative] = None
            elif path.is_file():
                size = path.stat().st_size
                files.append(
                    {
                        "path": relative,
                        "type": "file",
                        "bytes": size,
                        "sha256": sha256_file(path),
                    }
                )
                contents[relative] = path.read_bytes() if size <= MAX_DIFF_TEXT_BYTES else None
    tree_material = b"".join(canonical_json_bytes(row) for row in files)
    public = {
        "schema_version": SCHEMA_VERSION,
        "root": str(root),
        "exists": root.exists(),
        "file_count": len(files),
        "tree_sha256": sha256_bytes(tree_material),
        "files": files,
    }
    return WorkspaceCapture(public=public, contents=contents)


def render_workspace_diff(
    before: WorkspaceCapture, after: WorkspaceCapture
) -> tuple[str, list[str]]:
    before_rows = {row["path"]: row for row in before.public["files"]}
    after_rows = {row["path"]: row for row in after.public["files"]}
    changed = sorted(
        path
        for path in set(before_rows) | set(after_rows)
        if before_rows.get(path) != after_rows.get(path)
    )
    chunks: list[str] = []
    for relative in changed:
        before_row = before_rows.get(relative)
        after_row = after_rows.get(relative)
        old = before.contents.get(relative)
        new = after.contents.get(relative)
        before_is_text_candidate = before_row is None or before_row.get("type") == "file"
        after_is_text_candidate = after_row is None or after_row.get("type") == "file"
        if before_is_text_candidate and after_is_text_candidate and (
            old is not None or before_row is None
        ) and (new is not None or after_row is None):
            try:
                old_lines = (old or b"").decode("utf-8").splitlines(keepends=True)
                new_lines = (new or b"").decode("utf-8").splitlines(keepends=True)
            except UnicodeDecodeError:
                chunks.append(f"Binary change: {relative}\n")
            else:
                chunks.extend(
                    difflib.unified_diff(
                        old_lines,
                        new_lines,
                        fromfile=f"before/{relative}",
                        tofile=f"after/{relative}",
                    )
                )
        elif before_row is None:
            chunks.append(f"Added file: {relative}\n")
        elif after_row is None:
            chunks.append(f"Deleted file: {relative}\n")
        else:
            chunks.append(f"Binary or large-file change: {relative}\n")
    return "".join(chunks), changed


def _extract_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [_extract_text(item) for item in value]
        return "".join(part for part in parts if part)
    if isinstance(value, dict):
        for key in ("text", "content", "output_text", "message"):
            if key in value:
                text = _extract_text(value[key])
                if text:
                    return text
    return ""


def parse_cli_events(raw_jsonl: str) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    non_json_line_count = 0
    for line in raw_jsonl.splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            non_json_line_count += 1
            continue
        if isinstance(value, dict):
            events.append(value)
    event_types: Counter[str] = Counter()
    command_traces: list[dict[str, Any]] = []
    tool_traces: list[dict[str, Any]] = []
    error_events: list[dict[str, Any]] = []
    response = ""
    thread_id: str | None = None
    usage: dict[str, Any] = {}
    for event in events:
        event_type = str(event.get("type", "unknown"))
        event_types[event_type] += 1
        if thread_id is None:
            candidate = event.get("thread_id") or event.get("threadId")
            if isinstance(candidate, str):
                thread_id = candidate
        if isinstance(event.get("usage"), dict):
            usage = event["usage"]
        item = event.get("item")
        if isinstance(item, dict):
            item_type = str(item.get("type", ""))
            if item_type == "agent_message":
                candidate = _extract_text(item)
                if candidate:
                    response = candidate
            elif "command" in item_type or item_type in {"shell", "command_execution"}:
                command_traces.append(item)
            elif item_type not in {"", "reasoning"}:
                tool_traces.append(item)
            if "error" in item_type:
                error_events.append(event)
        if "error" in event_type or event_type.endswith("failed"):
            error_events.append(event)
    return {
        "events": events,
        "event_count": len(events),
        "non_json_line_count": non_json_line_count,
        "event_types": dict(sorted(event_types.items())),
        "thread_id": thread_id,
        "usage": usage,
        "response": response,
        "command_traces": command_traces,
        "tool_traces": tool_traces,
        "error_events": error_events,
    }


def classify_attempt(
    *, exit_code: int | None, stderr: str, parsed: dict[str, Any], timed_out: bool
) -> tuple[str, bool, str | None]:
    if timed_out:
        return "transient_failed", True, "timeout"
    error_material = stderr + "\n" + json.dumps(parsed.get("error_events", []), sort_keys=True)
    if any(pattern.search(error_material) for pattern in FATAL_RUNTIME_PATTERNS):
        return "permanent_failed", False, "fatal_runtime_drift"
    structurally_complete = (
        exit_code == 0
        and isinstance(parsed.get("response"), str)
        and bool(parsed["response"].strip())
        and parsed.get("event_types", {}).get("turn.completed", 0) == 1
        and isinstance(parsed.get("thread_id"), str)
        and bool(parsed["thread_id"])
        and isinstance(parsed.get("usage"), dict)
        and bool(parsed["usage"])
        and parsed.get("non_json_line_count") == 0
    )
    # Completion is determined only from transport structure, never answer meaning.
    if structurally_complete:
        return "completed", False, None
    if any(pattern.search(error_material) for pattern in TRANSIENT_PATTERNS):
        return "transient_failed", True, "transient_runtime"
    if exit_code == 0:
        return "transient_failed", True, "incomplete_event_stream"
    if exit_code not in (0, None):
        return "permanent_failed", False, "cli_exit"
    return "transient_failed", True, "missing_final_response"


def trace_policy_error(
    tool_policy: str,
    parsed: dict[str, Any],
    workspace: Path,
    before: WorkspaceCapture,
    after: WorkspaceCapture,
) -> str | None:
    command_traces = parsed.get("command_traces", [])
    tool_traces = parsed.get("tool_traces", [])
    if tool_policy == "none":
        if command_traces or tool_traces:
            return "no_tool_trace_violation"
        if after.public.get("tree_sha256") != before.public.get("tree_sha256"):
            return "no_tool_workspace_violation"
        return None
    disallowed_types = {
        str(item.get("type", ""))
        for item in tool_traces
        if str(item.get("type", "")) not in {"file_change"}
    }
    if disallowed_types:
        return "unexpected_tool_trace"
    workspace_root = workspace.resolve()
    for row in after.public.get("files", []):
        if row.get("type") != "symlink":
            continue
        link = workspace_root / PurePosixPath(str(row.get("path", "")))
        if not link.resolve().is_relative_to(workspace_root):
            return "workspace_symlink_escape"
    return None


def _reset_workspace(cell_dir: Path, inputs: PilotInputs, row: dict[str, Any]) -> Path:
    if row["tool_policy"] == "none":
        return NO_TOOL_CWD
    workspace = cell_dir / "workspace"
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True)
    files = inputs.artifacts[row["artifact_key"]].get("files", {})
    for relative, content in sorted(files.items()):
        destination = workspace / PurePosixPath(relative)
        resolved = destination.resolve()
        if not resolved.is_relative_to(workspace.resolve()):
            raise PilotError(f"Artifact path escapes workspace: {relative}")
        atomic_write_text(destination, content)
    return workspace


def _invoke_cli(
    command: list[str], prompt: str, env: dict[str, str], cwd: Path, timeout_seconds: float
) -> dict[str, Any]:
    started = time.monotonic()
    started_at = utc_now()
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    timed_out = False
    try:
        stdout, stderr = process.communicate(prompt, timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            process.kill()
        stdout, stderr = process.communicate()
    latency_ms = round((time.monotonic() - started) * 1000, 3)
    return {
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": process.returncode,
        "timed_out": timed_out,
        "latency_ms": latency_ms,
        "started_at": started_at,
        "completed_at": utc_now(),
    }


CELL_ARTIFACT_FILES = {
    "prompt_sha256": "prompt.txt",
    "raw_events_sha256": "raw-events.jsonl",
    "stderr_sha256": "stderr.txt",
    "response_sha256": "response.txt",
    "trace_sha256": "trace.json",
    "workspace_before_sha256": "workspace-before.json",
    "workspace_after_sha256": "workspace-after.json",
    "workspace_diff_sha256": "workspace.diff",
}
ATTEMPT_ARTIFACT_FILES = {
    key: value for key, value in CELL_ARTIFACT_FILES.items() if key != "prompt_sha256"
}


def _file_hashes(cell_dir: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for key, name in CELL_ARTIFACT_FILES.items():
        path = cell_dir / name
        if path.is_symlink() or not path.is_file():
            raise PilotError(f"Missing or symlinked cell artifact: {path}")
        hashes[key] = sha256_file(path)
    return hashes


def verify_cell_artifacts(cell_dir: Path, metadata: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    expected = metadata.get("hashes", {})
    for key, name in CELL_ARTIFACT_FILES.items():
        path = cell_dir / name
        if path.is_symlink() or not path.is_file():
            errors.append(f"{cell_dir.name} missing cell artifact: {name}")
        elif expected.get(key) != sha256_file(path):
            errors.append(f"{cell_dir.name} artifact hash mismatch: {key}")
    attempts = metadata.get("attempts")
    if not isinstance(attempts, list) or metadata.get("attempt_count") != len(attempts):
        errors.append(f"{cell_dir.name} attempt ledger mismatch")
        attempts = []
    for expected_number, attempt in enumerate(attempts, 1):
        if not isinstance(attempt, dict) or attempt.get("attempt") != expected_number:
            errors.append(f"{cell_dir.name} invalid attempt record {expected_number}")
            continue
        attempt_dir = cell_dir / "attempts" / f"attempt-{expected_number:02d}"
        hashes = attempt.get("hashes", {})
        for key, name in ATTEMPT_ARTIFACT_FILES.items():
            path = attempt_dir / name
            if path.is_symlink() or not path.is_file():
                errors.append(f"{cell_dir.name} attempt {expected_number} missing artifact: {name}")
            elif hashes.get(key) != sha256_file(path):
                errors.append(
                    f"{cell_dir.name} attempt {expected_number} hash mismatch: {key}"
                )
        after_hash = attempt.get("workspace", {}).get("after_tree_sha256")
        if metadata.get("tool_policy") == "workspace":
            snapshot = attempt_dir / "workspace-final"
            if snapshot.is_symlink() or not snapshot.is_dir():
                errors.append(
                    f"{cell_dir.name} attempt {expected_number} missing workspace snapshot"
                )
            elif capture_workspace(snapshot).public["tree_sha256"] != after_hash:
                errors.append(
                    f"{cell_dir.name} attempt {expected_number} workspace snapshot drift"
                )
    workspace = NO_TOOL_CWD if metadata.get("tool_policy") == "none" else cell_dir / "workspace"
    if not workspace.is_dir():
        errors.append(f"{cell_dir.name} final workspace is missing")
    elif capture_workspace(workspace).public["tree_sha256"] != metadata.get("workspace", {}).get(
        "after_tree_sha256"
    ):
        errors.append(f"{cell_dir.name} final workspace tree drift")
    return errors


def execute_cell(
    *,
    run_dir: Path,
    inputs: PilotInputs,
    row: dict[str, Any],
    cli_path: Path,
    codex_home: Path,
    max_retries: int,
    timeout_seconds: float,
    retry_backoff_seconds: Sequence[float],
    cli_version: str,
) -> dict[str, Any]:
    cell_dir = run_dir / row["cell_dir"]
    cell_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = cell_dir / "metadata.json"
    existing: dict[str, Any] | None = load_json(metadata_path) if metadata_path.is_file() else None
    if existing:
        if existing.get("cell_id") != row["cell_id"]:
            raise PilotError(f"Cell metadata identity mismatch: {cell_dir}")
        if existing.get("status") == "completed":
            artifact_errors = verify_cell_artifacts(cell_dir, existing)
            if artifact_errors:
                raise PilotError("; ".join(artifact_errors))
            return {"status": "completed", "skipped": True, "metadata": existing}
        if existing.get("status") == "permanent_failed":
            return {"status": "permanent_failed", "skipped": True, "metadata": existing}
    attempts: list[dict[str, Any]] = list(existing.get("attempts", [])) if existing else []
    max_attempts = 1 + max_retries
    if len(attempts) >= max_attempts:
        if existing:
            existing["status"] = "permanent_failed"
            existing["error"] = {"kind": "retry_exhausted"}
            atomic_write_json(metadata_path, existing)
        return {"status": "permanent_failed", "skipped": True, "metadata": existing or {}}

    fixture = next(item for item in inputs.fixtures if item["fixture_id"] == row["fixture_id"])
    workflow = next(item for item in inputs.workflows if item["workflow_id"] == row["workflow_id"])
    prompt = build_prompt(inputs, fixture, workflow)
    prompt_hash = sha256_bytes(prompt.encode("utf-8"))
    if prompt_hash != row["prompt_sha256"]:
        raise PilotError(f"Prompt hash drift for {row['cell_id']}")
    atomic_write_text(cell_dir / "prompt.txt", prompt)
    overall_started = existing.get("started_at") if existing else utc_now()

    while len(attempts) < max_attempts:
        attempt_number = len(attempts) + 1
        attempt_dir = cell_dir / "attempts" / f"attempt-{attempt_number:02d}"
        if attempt_dir.exists():
            shutil.rmtree(attempt_dir)
        attempt_dir.mkdir(parents=True)
        workspace = _reset_workspace(cell_dir, inputs, row)
        temp_dir = (
            workspace / ".pilot-runtime-tmp"
            if row["tool_policy"] == "workspace"
            else attempt_dir / "runtime-tmp"
        )
        temp_dir.mkdir(parents=True, exist_ok=True)
        before = capture_workspace(workspace)
        atomic_write_json(attempt_dir / "workspace-before.json", before.public)
        command = build_codex_command(cli_path, codex_home, row["tool_policy"], workspace)
        runtime_root = Path(
            tempfile.mkdtemp(
                prefix="pilot-v2-cell-runtime-",
                dir=codex_home.resolve().parent,
            )
        )
        try:
            environment = isolated_environment(
                codex_home,
                runtime_root,
                temporary_dir=temp_dir,
                tool_readable_roots=(workspace, temp_dir),
            )
            invocation = _invoke_cli(
                command,
                prompt,
                environment,
                workspace,
                timeout_seconds,
            )
        finally:
            shutil.rmtree(runtime_root, ignore_errors=True)
        after = capture_workspace(workspace)
        workspace_diff, changed_paths = render_workspace_diff(before, after)
        parsed = parse_cli_events(invocation["stdout"])
        status, transient, error_kind = classify_attempt(
            exit_code=invocation["exit_code"],
            stderr=invocation["stderr"],
            parsed=parsed,
            timed_out=invocation["timed_out"],
        )
        policy_error: str | None = None
        if status == "completed":
            policy_error = trace_policy_error(
                row["tool_policy"], parsed, workspace, before, after
            )
            if policy_error:
                status, transient, error_kind = "permanent_failed", False, policy_error
        trace = {
            "schema_version": SCHEMA_VERSION,
            "event_count": parsed["event_count"],
            "non_json_line_count": parsed["non_json_line_count"],
            "event_types": parsed["event_types"],
            "thread_id": parsed["thread_id"],
            "usage": parsed["usage"],
            "command_traces": parsed["command_traces"],
            "tool_traces": parsed["tool_traces"],
            "policy_error": policy_error,
        }
        artifacts = {
            "raw-events.jsonl": invocation["stdout"],
            "stderr.txt": invocation["stderr"],
            "response.txt": parsed["response"],
            "workspace.diff": workspace_diff,
        }
        for name, text in artifacts.items():
            atomic_write_text(attempt_dir / name, text)
            atomic_write_text(cell_dir / name, text)
        for name, value in (
            ("trace.json", trace),
            ("workspace-before.json", before.public),
            ("workspace-after.json", after.public),
        ):
            atomic_write_json(attempt_dir / name, value)
            atomic_write_json(cell_dir / name, value)
        if row["tool_policy"] == "workspace":
            workspace_snapshot = attempt_dir / "workspace-final"
            if workspace_snapshot.exists():
                shutil.rmtree(workspace_snapshot)
            shutil.copytree(workspace, workspace_snapshot, symlinks=True)

        top_hashes = _file_hashes(cell_dir)
        attempt_hashes = {
            key: sha256_file(attempt_dir / name)
            for key, name in {
                "raw_events_sha256": "raw-events.jsonl",
                "stderr_sha256": "stderr.txt",
                "response_sha256": "response.txt",
                "trace_sha256": "trace.json",
                "workspace_before_sha256": "workspace-before.json",
                "workspace_after_sha256": "workspace-after.json",
                "workspace_diff_sha256": "workspace.diff",
            }.items()
        }
        attempt_record = {
            "attempt": attempt_number,
            "status": status,
            "transient": transient,
            "error_kind": error_kind,
            "started_at": invocation["started_at"],
            "completed_at": invocation["completed_at"],
            "latency_ms": invocation["latency_ms"],
            "cli_exit_code": invocation["exit_code"],
            "thread_id": parsed["thread_id"],
            "usage": parsed["usage"],
            "command": command,
            "environment_keys": sorted(environment),
            "timeout_seconds": timeout_seconds,
            "retry_backoff_seconds": list(retry_backoff_seconds),
            "hashes": attempt_hashes,
            "workspace": {
                "root": str(workspace),
                "before_tree_sha256": before.public["tree_sha256"],
                "after_tree_sha256": after.public["tree_sha256"],
                "changed": bool(changed_paths),
                "changed_paths": changed_paths,
                "diff_sha256": attempt_hashes["workspace_diff_sha256"],
            },
            "error": {"kind": error_kind} if error_kind else None,
        }
        attempts.append(attempt_record)
        final_status = status
        final_error = {"kind": error_kind} if error_kind else None
        if status == "transient_failed" and len(attempts) >= max_attempts:
            final_status = "permanent_failed"
            final_error = {"kind": "retry_exhausted", "last_error_kind": error_kind}
        metadata = {
            "schema_version": SCHEMA_VERSION,
            "run_id": row["run_id"],
            "phase": row["phase"],
            "discarded": row["discarded"],
            "cell_id": row["cell_id"],
            "blind_id": row.get("blind_id"),
            "fixture_id": row["fixture_id"],
            "workflow_id": row["workflow_id"],
            "trial": row["trial"],
            "status": final_status,
            "started_at": overall_started,
            "completed_at": invocation["completed_at"],
            "attempt_count": len(attempts),
            "retry_count": max(0, len(attempts) - 1),
            "max_retries": max_retries,
            "timeout_seconds": timeout_seconds,
            "retry_backoff_seconds": list(retry_backoff_seconds),
            "attempts": attempts,
            "requested_model": REQUESTED_MODEL,
            "reasoning_effort": REASONING_EFFORT,
            "tool_policy": row["tool_policy"],
            "sandbox": "read-only" if row["tool_policy"] == "none" else "workspace-write",
            "cwd": str(workspace),
            "cli_path": str(cli_path),
            "cli_version": cli_version,
            "cli_exit_code": invocation["exit_code"],
            "latency_ms": sum(float(item["latency_ms"]) for item in attempts),
            "thread_id": parsed["thread_id"],
            "usage": parsed["usage"],
            "command": command,
            "feature_disables": [
                command[index + 1]
                for index, value in enumerate(command)
                if value == "--disable"
            ],
            "hashes": top_hashes,
            "trace_summary": {
                "event_count": trace["event_count"],
                "command_count": len(trace["command_traces"]),
                "tool_count": len(trace["tool_traces"]),
            },
            "workspace": attempt_record["workspace"],
            "error": final_error,
        }
        atomic_write_json(metadata_path, metadata)
        if final_status != "transient_failed":
            return {"status": final_status, "skipped": False, "metadata": metadata}
        delay = retry_backoff_seconds[attempt_number - 1]
        if delay > 0:
            time.sleep(delay)
    raise AssertionError("unreachable retry loop")


def _run_artifact_hashes(run_dir: Path) -> dict[str, str]:
    mapping = {
        "plan_sha256": run_dir / "plan-private.jsonl",
        "preflight_plan_sha256": run_dir / "preflight-plan.jsonl",
        "blind_map_sha256": run_dir / "blind-map-private.json",
    }
    return {key: sha256_file(path) for key, path in mapping.items()}


def create_run_plan(
    *,
    run_dir: Path,
    run_id: str,
    inputs: PilotInputs,
    runtime: dict[str, Any],
    cli_path: Path,
    codex_home: Path,
    plan_seed: int,
    blind_seed: int,
) -> dict[str, Any]:
    if run_dir.exists() and any(run_dir.iterdir()):
        raise PilotError(f"Run directory is not empty: {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=True)
    scored_plan, blind_map = generate_scored_plan(inputs, run_id, plan_seed, blind_seed)
    preflight_plan = generate_preflight_plan(inputs, run_id)
    atomic_write_jsonl(run_dir / "plan-private.jsonl", scored_plan)
    atomic_write_jsonl(run_dir / "preflight-plan.jsonl", preflight_plan)
    atomic_write_json(run_dir / "blind-map-private.json", blind_map)
    hashes = _run_artifact_hashes(run_dir)
    source_hashes = compute_source_hashes(inputs)
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "status": "planned",
        "requested_model": REQUESTED_MODEL,
        "reasoning_effort": REASONING_EFFORT,
        "cli_path": str(cli_path.resolve()),
        "cli_version": runtime["cli_version"],
        "codex_home": str(codex_home.resolve()),
        "source_hashes": source_hashes,
        "plan_seed": plan_seed,
        "blind_seed": blind_seed,
        "hashes": hashes,
        "runtime_controls": {
            "common_feature_disables": list(COMMON_FEATURE_DISABLES),
            "none_policy_additional_disables": list(NONE_POLICY_FEATURE_DISABLES),
            "none_command": build_codex_command(
                cli_path, codex_home, "none", NO_TOOL_CWD
            ),
            "workspace_command_template": build_codex_command(
                cli_path, codex_home, "workspace", Path("<CELL_WORKSPACE>")
            ),
        },
        "preflight": {
            "status": "not_run",
            "expected_cells": 3,
            "discarded": True,
            "completed_cells": 0,
            "failed_cells": 0,
        },
        "scored": {
            "status": "not_run",
            "expected_cells": 45,
            "completed_cells": 0,
            "failed_cells": 0,
        },
    }
    atomic_write_json(run_dir / "run-manifest.json", manifest)
    return manifest


def validate_run_directory(run_dir: Path, inputs: PilotInputs) -> list[str]:
    errors: list[str] = []
    manifest_path = run_dir / "run-manifest.json"
    if not manifest_path.is_file():
        return [f"Missing run manifest: {manifest_path}"]
    manifest = load_json(manifest_path)
    try:
        actual_hashes = _run_artifact_hashes(run_dir)
    except FileNotFoundError as exc:
        errors.append(f"Missing run artifact: {exc.filename}")
        return errors
    for key, actual in actual_hashes.items():
        if manifest.get("hashes", {}).get(key) != actual:
            errors.append(f"Run artifact hash mismatch: {key}")
    if manifest.get("source_hashes") != compute_source_hashes(inputs):
        errors.append("Frozen source hash drift")
    plan = load_jsonl(run_dir / "plan-private.jsonl")
    preflight = load_jsonl(run_dir / "preflight-plan.jsonl")
    if len(plan) != 45:
        errors.append("Scored plan must contain 45 cells")
    if len(preflight) != 3 or not all(row.get("discarded") for row in preflight):
        errors.append("Preflight plan must contain three discarded cells")
    fixture_map = {row["fixture_id"]: row for row in inputs.fixtures}
    workflow_map = {row["workflow_id"]: row for row in inputs.workflows}
    for row in plan + preflight:
        fixture = fixture_map.get(row.get("fixture_id"))
        workflow = workflow_map.get(row.get("workflow_id"))
        if fixture is None or workflow is None:
            errors.append(f"Unknown plan member: {row.get('cell_id')}")
            continue
        actual_prompt_hash = sha256_bytes(build_prompt(inputs, fixture, workflow).encode("utf-8"))
        if actual_prompt_hash != row.get("prompt_sha256"):
            errors.append(f"Plan prompt hash mismatch: {row.get('cell_id')}")
    controls = manifest.get("runtime_controls", {})
    if controls.get("common_feature_disables") != list(COMMON_FEATURE_DISABLES):
        errors.append("Manifest common feature controls drifted")
    if controls.get("none_policy_additional_disables") != list(NONE_POLICY_FEATURE_DISABLES):
        errors.append("Manifest no-tool feature controls drifted")
    return errors


def _phase_counts(run_dir: Path, rows: Sequence[dict[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for row in rows:
        path = run_dir / row["cell_dir"] / "metadata.json"
        if path.is_file():
            counts[str(load_json(path).get("status", "missing"))] += 1
        else:
            counts["missing"] += 1
    return dict(counts)


def _update_manifest_phase(
    run_dir: Path, phase: str, rows: Sequence[dict[str, Any]]
) -> dict[str, Any]:
    manifest_path = run_dir / "run-manifest.json"
    manifest = load_json(manifest_path)
    counts = _phase_counts(run_dir, rows)
    completed = counts.get("completed", 0)
    failed = sum(value for key, value in counts.items() if key not in {"completed", "missing"})
    if completed == len(rows):
        status = "completed"
    elif failed:
        status = "failed"
    else:
        status = "partial"
    manifest[phase].update(
        {
            "status": status,
            "completed_cells": completed,
            "failed_cells": failed,
            "status_counts": counts,
        }
    )
    manifest["status"] = "scored_complete" if phase == "scored" and status == "completed" else status
    manifest["updated_at"] = utc_now()
    atomic_write_json(manifest_path, manifest)
    return manifest


def execute_phase(
    *,
    run_dir: Path,
    inputs: PilotInputs,
    rows: Sequence[dict[str, Any]],
    phase: str,
    cli_path: Path,
    codex_home: Path,
    cli_version: str,
    max_retries: int,
    timeout_seconds: float,
    retry_backoff_seconds: Sequence[float],
) -> dict[str, Any]:
    if not 0 <= max_retries <= MAX_ALLOWED_RETRIES:
        raise PilotError(f"max_retries must be between 0 and {MAX_ALLOWED_RETRIES}")
    for row in rows:
        result = execute_cell(
            run_dir=run_dir,
            inputs=inputs,
            row=row,
            cli_path=cli_path,
            codex_home=codex_home,
            max_retries=max_retries,
            timeout_seconds=timeout_seconds,
            retry_backoff_seconds=retry_backoff_seconds,
            cli_version=cli_version,
        )
        metadata = result.get("metadata", {})
        if (metadata.get("error") or {}).get("kind") == "fatal_runtime_drift":
            _update_manifest_phase(run_dir, phase, rows)
            raise PilotError(f"Fatal runtime drift in {row['cell_id']}")
    return _update_manifest_phase(run_dir, phase, rows)


def _runtime_or_raise(cli_path: Path, codex_home: Path) -> dict[str, Any]:
    runtime = inspect_runtime(cli_path, codex_home)
    if not runtime["ok"]:
        raise PilotError("; ".join(runtime["errors"]))
    return runtime


def _validate_everything(
    *, cli_path: Path, codex_home: Path, run_dir: Path | None = None
) -> dict[str, Any]:
    inputs = load_pilot_inputs()
    errors = validate_pilot_inputs(inputs)
    runtime = inspect_runtime(cli_path, codex_home)
    errors.extend(runtime["errors"])
    if run_dir is not None:
        errors.extend(validate_run_directory(run_dir, inputs))
    return {
        "ok": not errors,
        "errors": errors,
        "source_hashes": compute_source_hashes(inputs),
        "runtime": runtime,
        "run_dir": str(run_dir.resolve()) if run_dir else None,
    }


def _positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def _retry_count(value: str) -> int:
    parsed = int(value)
    if not 0 <= parsed <= MAX_ALLOWED_RETRIES:
        raise argparse.ArgumentTypeError(f"must be between 0 and {MAX_ALLOWED_RETRIES}")
    return parsed


def _retry_backoff_sequence(value: str) -> tuple[float, ...]:
    try:
        parsed = tuple(float(item.strip()) for item in value.split(","))
    except ValueError as error:
        raise argparse.ArgumentTypeError("must be comma-separated seconds") from error
    if len(parsed) < MAX_ALLOWED_RETRIES or any(item < 0 for item in parsed):
        raise argparse.ArgumentTypeError(
            f"must provide at least {MAX_ALLOWED_RETRIES} non-negative delays"
        )
    return parsed


def _add_runtime_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--cli-path", type=Path, default=DEFAULT_CLI_PATH)
    parser.add_argument("--codex-home", type=Path, required=True)


def _add_execution_arguments(parser: argparse.ArgumentParser) -> None:
    _add_runtime_arguments(parser)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--max-retries", type=_retry_count, default=MAX_ALLOWED_RETRIES)
    parser.add_argument("--timeout-seconds", type=_positive_float, default=600.0)
    parser.add_argument(
        "--retry-backoff-seconds",
        type=_retry_backoff_sequence,
        default=RETRY_BACKOFF_SECONDS,
        metavar="SECONDS[,SECONDS]",
    )
    parser.add_argument("--resume", action="store_true", default=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_parser = subparsers.add_parser("validate", help="Validate frozen inputs and runtime")
    _add_runtime_arguments(validate_parser)
    validate_parser.add_argument("--run-dir", type=Path)

    plan_parser = subparsers.add_parser("plan", help="Freeze plans, blind map, and run manifest")
    _add_runtime_arguments(plan_parser)
    plan_parser.add_argument("--run-dir", type=Path, required=True)
    plan_parser.add_argument("--run-id", required=True)
    plan_parser.add_argument("--plan-seed", type=int, default=DEFAULT_PLAN_SEED)
    plan_parser.add_argument("--blind-seed", type=int, default=DEFAULT_BLIND_SEED)

    preflight_parser = subparsers.add_parser(
        "preflight", help="Execute three discarded plumbing cells"
    )
    _add_execution_arguments(preflight_parser)
    run_parser = subparsers.add_parser("run", help="Execute or resume the 45 scored cells")
    _add_execution_arguments(run_parser)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        if args.command == "validate":
            result = _validate_everything(
                cli_path=args.cli_path, codex_home=args.codex_home, run_dir=args.run_dir
            )
            print(json.dumps(result, sort_keys=True))
            return 0 if result["ok"] else 1

        inputs = load_pilot_inputs()
        structural_errors = validate_pilot_inputs(inputs)
        if structural_errors:
            raise PilotError("; ".join(structural_errors))
        runtime = _runtime_or_raise(args.cli_path, args.codex_home)
        if args.command == "plan":
            manifest = create_run_plan(
                run_dir=args.run_dir,
                run_id=args.run_id,
                inputs=inputs,
                runtime=runtime,
                cli_path=args.cli_path,
                codex_home=args.codex_home,
                plan_seed=args.plan_seed,
                blind_seed=args.blind_seed,
            )
            print(json.dumps({"ok": True, "run_id": manifest["run_id"], "run_dir": str(args.run_dir)}))
            return 0

        run_errors = validate_run_directory(args.run_dir, inputs)
        if run_errors:
            raise PilotError("; ".join(run_errors))
        manifest = load_json(args.run_dir / "run-manifest.json")
        if Path(manifest["cli_path"]).resolve() != args.cli_path.resolve():
            raise PilotError("CLI path drift from frozen run manifest")
        if Path(manifest["codex_home"]).resolve() != args.codex_home.resolve():
            raise PilotError("CODEX_HOME drift from frozen run manifest")
        if manifest["cli_version"] != runtime["cli_version"]:
            raise PilotError("CLI version drift from frozen run manifest")
        if args.command == "preflight":
            rows = load_jsonl(args.run_dir / "preflight-plan.jsonl")
            result = execute_phase(
                run_dir=args.run_dir,
                inputs=inputs,
                rows=rows,
                phase="preflight",
                cli_path=args.cli_path,
                codex_home=args.codex_home,
                cli_version=runtime["cli_version"],
                max_retries=args.max_retries,
                timeout_seconds=args.timeout_seconds,
                retry_backoff_seconds=args.retry_backoff_seconds,
            )
            print(json.dumps({"ok": result["preflight"]["status"] == "completed", "preflight": result["preflight"]}))
            return 0 if result["preflight"]["status"] == "completed" else 1
        if manifest.get("preflight", {}).get("status") != "completed":
            raise PilotError("Scored run is blocked until all three discarded preflight cells complete")
        rows = load_jsonl(args.run_dir / "plan-private.jsonl")
        result = execute_phase(
            run_dir=args.run_dir,
            inputs=inputs,
            rows=rows,
            phase="scored",
            cli_path=args.cli_path,
            codex_home=args.codex_home,
            cli_version=runtime["cli_version"],
            max_retries=args.max_retries,
            timeout_seconds=args.timeout_seconds,
            retry_backoff_seconds=args.retry_backoff_seconds,
        )
        print(json.dumps({"ok": result["scored"]["status"] == "completed", "scored": result["scored"]}))
        return 0 if result["scored"]["status"] == "completed" else 1
    except (PilotError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
