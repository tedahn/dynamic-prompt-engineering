#!/usr/bin/env python3
"""Validate, plan, and summarize professionalize-prompt evaluations.

The harness uses only the Python standard library. It never calls a model and
prints plans/summaries to stdout so callers can preserve them immutably.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

LAB_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SCORE_HEADER = [
    "experiment_id",
    "run_id",
    "anonymous_id",
    "skill_snapshot_id",
    "workflow_id",
    "fixture_id",
    "split",
    "trial",
    "record_status",
    "grader_set",
    "prompt_score",
    "deterministic_score",
    "human_score",
    "efficiency_score",
    "outcome_score",
    "critical_gate",
    "gate_reason",
    "calls",
    "input_chars",
    "output_chars",
    "latency_ms",
    "evidence_ref",
    "scored_at",
    "notes",
]
FIXTURE_FIELDS = {
    "fixture_id",
    "family",
    "split",
    "domain",
    "request",
    "context",
    "expected",
    "forbidden",
    "mode",
    "ambiguity",
    "authority_risk",
    "tool_policy",
    "checks",
    "tags",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL {path}:{number}: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"Expected object at {path}:{number}")
            rows.append(value)
    return rows


def resolve_lab_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (LAB_ROOT / path).resolve()


def validate_snapshot(snapshot_dir: Path) -> list[str]:
    errors: list[str] = []
    manifest_path = snapshot_dir / "snapshot-manifest.json"
    if not manifest_path.is_file():
        return [f"Missing snapshot manifest: {manifest_path}"]
    manifest = load_json(manifest_path)
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        return [f"Snapshot files must be a nonempty list: {manifest_path}"]
    hash_rows: list[tuple[str, str]] = []
    for record in files:
        if not isinstance(record, dict):
            errors.append("Snapshot file record is not an object")
            continue
        relative = record.get("snapshot_path")
        if not isinstance(relative, str):
            errors.append("Snapshot path is missing")
            continue
        pure = PurePosixPath(relative)
        if pure.is_absolute() or ".." in pure.parts or pure.as_posix() != relative:
            errors.append(f"Unsafe snapshot path: {relative!r}")
            continue
        path = snapshot_dir / relative
        if not path.is_file():
            errors.append(f"Snapshot file missing: {relative}")
            continue
        data = path.read_bytes()
        actual_hash = sha256_bytes(data)
        if actual_hash != record.get("sha256"):
            errors.append(f"Snapshot hash mismatch: {relative}")
        if len(data) != record.get("bytes"):
            errors.append(f"Snapshot byte count mismatch: {relative}")
        try:
            line_count = len(data.decode("utf-8").replace("\r\n", "\n").split("\n"))
        except UnicodeDecodeError:
            errors.append(f"Snapshot is not UTF-8: {relative}")
            line_count = None
        if line_count is not None and line_count != record.get("lines"):
            errors.append(f"Snapshot line count mismatch: {relative}")
        hash_rows.append((relative, actual_hash))
    material = "\n".join(f"{name}:{digest}" for name, digest in sorted(hash_rows))
    bundle_hash = sha256_bytes(material.encode("utf-8"))
    if bundle_hash != manifest.get("bundle_sha256"):
        errors.append("Snapshot bundle hash mismatch")
    directory_files = {
        path.relative_to(snapshot_dir).as_posix()
        for path in snapshot_dir.rglob("*")
        if path.is_file() and path.name != "snapshot-manifest.json"
    }
    listed_files = {record.get("snapshot_path") for record in files if isinstance(record, dict)}
    if directory_files != listed_files:
        errors.append(
            f"Snapshot dependency closure mismatch; unlisted={sorted(directory_files - listed_files)}, "
            f"missing={sorted(listed_files - directory_files)}"
        )
    return errors


def validate_workflows(path: Path) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    data = load_json(path)
    workflows = data.get("workflows")
    ablations = data.get("ablations")
    if not isinstance(workflows, list) or not isinstance(ablations, list):
        return ["Workflow registry requires workflow and ablation lists"], data
    ids: list[str] = []
    for record in workflows + ablations:
        if not isinstance(record, dict) or not isinstance(record.get("workflow_id"), str):
            errors.append("Every workflow and ablation requires workflow_id")
            continue
        ids.append(record["workflow_id"])
    if len(ids) != len(set(ids)):
        errors.append("Workflow IDs are not unique")
    if data.get("adoption_baseline") not in ids:
        errors.append("Adoption baseline is not in the workflow registry")
    for required in {
        "B00_RAW_1CALL",
        "B01_STATIC_MIN_1CALL",
        "B02_SHAM_2CALL",
        "B03_PRO_PROMPT_2CALL",
        "B04_PRO_INLINE_1CALL",
        "B05_HUMAN_SPEC_UPPER",
    }:
        if required not in ids:
            errors.append(f"Missing required baseline: {required}")
    return errors, data


def validate_rubric(path: Path) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    data = load_json(path)
    for section in ("prompt_diagnostic", "human_outcome"):
        rows = data.get(section)
        if not isinstance(rows, list):
            errors.append(f"Rubric section missing: {section}")
            continue
        total = sum(float(row.get("weight", 0)) for row in rows if isinstance(row, dict))
        if not math.isclose(total, 100.0):
            errors.append(f"Rubric weights for {section} sum to {total}, not 100")
    gates = data.get("hard_gates")
    if not isinstance(gates, list) or len(gates) < 5:
        errors.append("Behavior rubric requires the five critical hard gates")
    return errors, data


def validate_fixtures(path: Path) -> tuple[list[str], list[dict[str, Any]]]:
    errors: list[str] = []
    rows = load_jsonl(path)
    ids: list[str] = []
    families: list[str] = []
    for index, row in enumerate(rows, start=1):
        missing = FIXTURE_FIELDS - row.keys()
        if missing:
            errors.append(f"Fixture line {index} missing {sorted(missing)}")
        ids.append(str(row.get("fixture_id")))
        families.append(str(row.get("family")))
        if not isinstance(row.get("checks"), list) or not row.get("checks"):
            errors.append(f"Fixture {row.get('fixture_id')} has no checks")
        if not isinstance(row.get("tags"), list):
            errors.append(f"Fixture {row.get('fixture_id')} tags must be a list")
    if len(rows) != 45:
        errors.append(f"Expected 45 fixtures, found {len(rows)}")
    if len(ids) != len(set(ids)):
        errors.append("Fixture IDs are not unique")
    if len(families) != len(set(families)):
        errors.append("Scenario families cross fixture boundaries")
    expected_counts = {
        "split": {"dev": 30, "holdout": 15},
        "domain": {"editing": 9, "coding": 9, "research": 9, "decision-analysis": 9, "creative": 9},
        "mode": {"prompt-only": 15, "default": 15, "execute-only": 15},
        "ambiguity": {"clear": 15, "vague": 15, "consequentially-incomplete": 15},
        "authority_risk": {"high": 25, "low": 20},
        "tool_policy": {"workspace": 25, "none": 20},
    }
    for field, expected in expected_counts.items():
        actual = Counter(str(row.get(field)) for row in rows)
        if actual != Counter(expected):
            errors.append(f"Unexpected {field} strata: {dict(actual)}; expected {expected}")
    return errors, rows


def validate_check_registry(path: Path, fixtures: list[dict[str, Any]]) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    data = load_json(path)
    rules = data.get("rules")
    if not isinstance(rules, list) or not rules:
        return ["Check registry requires at least one rule"], data

    allowed_graders = {
        "automated-output-envelope",
        "fixture-or-trace-adapter",
        "blinded-human-semantic",
    }
    allowed_channels = {"D", "H"}
    registered_checks: list[str] = []
    for index, rule in enumerate(rules, start=1):
        if not isinstance(rule, dict):
            errors.append(f"Check registry rule {index} must be an object")
            continue
        grader_type = rule.get("grader_type")
        if grader_type not in allowed_graders:
            errors.append(f"Check registry rule {index} has invalid grader_type: {grader_type}")
        score_channel = rule.get("score_channel")
        if score_channel not in allowed_channels:
            errors.append(f"Check registry rule {index} has invalid score_channel: {score_channel}")
        weight = rule.get("default_weight")
        if not isinstance(weight, (int, float)) or isinstance(weight, bool) or weight <= 0:
            errors.append(f"Check registry rule {index} requires a positive default_weight")
        if not isinstance(rule.get("status"), str) or not rule.get("status"):
            errors.append(f"Check registry rule {index} requires a status")
        checks = rule.get("checks")
        if not isinstance(checks, list) or not checks:
            errors.append(f"Check registry rule {index} requires checks")
            continue
        if any(not isinstance(check, str) or not check for check in checks):
            errors.append(f"Check registry rule {index} contains an invalid check ID")
        registered_checks.extend(str(check) for check in checks)

    duplicate_registrations = sorted(
        check for check, count in Counter(registered_checks).items() if count != 1
    )
    if duplicate_registrations:
        errors.append(f"Checks must resolve to exactly one rule: {duplicate_registrations}")

    fixture_checks = {
        str(check)
        for fixture in fixtures
        for check in fixture.get("checks", [])
        if isinstance(check, str) and check
    }
    registered_set = set(registered_checks)
    missing = sorted(fixture_checks - registered_set)
    extra = sorted(registered_set - fixture_checks)
    if missing:
        errors.append(f"Fixture checks missing from registry: {missing}")
    if extra:
        errors.append(f"Registry checks unused by fixtures: {extra}")
    return errors, data


def as_float(value: str, field: str, row_number: int) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {field} at score row {row_number}: {value!r}") from exc
    return number


def is_true(value: str | bool | None) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def compute_outcome(deterministic: float, human: float, efficiency: float, gated: bool) -> float:
    for name, value in {"D": deterministic, "H": human, "E": efficiency}.items():
        if not 0 <= value <= 100:
            raise ValueError(f"{name} must be between 0 and 100")
    return 0.0 if gated else 0.50 * deterministic + 0.40 * human + 0.10 * efficiency


def validate_scores(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    errors: list[str] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != EXPECTED_SCORE_HEADER:
            errors.append("Score ledger header does not match v1 contract")
        rows = list(reader)
    keys: set[tuple[str, ...]] = set()
    for number, row in enumerate(rows, start=2):
        key = (
            row.get("experiment_id", ""),
            row.get("workflow_id", ""),
            row.get("fixture_id", ""),
            row.get("trial", ""),
            row.get("grader_set", ""),
        )
        if key in keys:
            errors.append(f"Duplicate score key at row {number}: {key}")
        keys.add(key)
        if row.get("record_status") != "adjudicated":
            continue
        try:
            p = as_float(row["prompt_score"], "prompt_score", number)
            d = as_float(row["deterministic_score"], "deterministic_score", number)
            h = as_float(row["human_score"], "human_score", number)
            e = as_float(row["efficiency_score"], "efficiency_score", number)
            s = as_float(row["outcome_score"], "outcome_score", number)
            if not 0 <= p <= 100:
                errors.append(f"Prompt score out of range at row {number}")
            expected = compute_outcome(d, h, e, is_true(row.get("critical_gate")))
            if not math.isclose(s, expected, abs_tol=0.05):
                errors.append(f"Outcome formula mismatch at row {number}: {s} vs {expected}")
        except ValueError as exc:
            errors.append(str(exc))
    return errors, rows


def validate_static_audit(path: Path) -> list[str]:
    errors: list[str] = []
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != 8:
        errors.append(f"Static audit requires 8 dimensions, found {len(rows)}")
        return errors
    weight_total = 0.0
    points_total = 0.0
    for number, row in enumerate(rows, start=2):
        try:
            weight = float(row["weight"])
            score = float(row["score_0_4"])
            points = float(row["weighted_points"])
        except (KeyError, ValueError) as exc:
            errors.append(f"Invalid static audit row {number}: {exc}")
            continue
        expected = weight * score / 4.0
        if not math.isclose(points, expected, abs_tol=0.01):
            errors.append(f"Static audit formula mismatch at row {number}")
        weight_total += weight
        points_total += points
    if not math.isclose(weight_total, 100.0):
        errors.append(f"Static audit weights sum to {weight_total}")
    if not math.isclose(points_total, 63.5, abs_tol=0.01):
        errors.append(f"Static audit total is {points_total}, expected 63.5")
    return errors


def validate_experiment(path: Path, workflows: dict[str, Any], fixtures: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    data = load_json(path)
    workflow_ids = {
        row["workflow_id"]
        for row in workflows.get("workflows", []) + workflows.get("ablations", [])
        if isinstance(row, dict) and "workflow_id" in row
    }
    fixture_ids = {row["fixture_id"] for row in fixtures}
    for workflow_id in data.get("full_workflows", []):
        if workflow_id not in workflow_ids:
            errors.append(f"Experiment references unknown workflow: {workflow_id}")
    pilot = data.get("pilot", {})
    for workflow_id in pilot.get("workflow_ids", []):
        if workflow_id not in workflow_ids:
            errors.append(f"Pilot references unknown workflow: {workflow_id}")
    for fixture_id in pilot.get("fixture_ids", []):
        if fixture_id not in fixture_ids:
            errors.append(f"Pilot references unknown fixture: {fixture_id}")
    calculated = len(pilot.get("workflow_ids", [])) * len(pilot.get("fixture_ids", [])) * int(pilot.get("trials", 0))
    if calculated != pilot.get("execution_cells"):
        errors.append("Pilot execution-cell count is inconsistent")
    full = data.get("full_study", {})
    calculated_full = int(full.get("fixture_count", 0)) * int(full.get("workflow_count", 0)) * int(full.get("trials", 0))
    if calculated_full != full.get("execution_cells"):
        errors.append("Full-study execution-cell count is inconsistent")
    snapshot_id = data.get("skill_snapshot_id")
    snapshot_matches = [
        manifest
        for manifest in LAB_ROOT.glob("snapshots/*/snapshot-manifest.json")
        if load_json(manifest).get("snapshot_id") == snapshot_id
    ]
    if len(snapshot_matches) != 1:
        errors.append(f"Experiment snapshot ID resolves to {len(snapshot_matches)} manifests")
    artifacts = data.get("frozen_artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        errors.append("Experiment requires frozen artifact hashes")
    else:
        for artifact_id, record in artifacts.items():
            if not isinstance(record, dict):
                errors.append(f"Frozen artifact record is invalid: {artifact_id}")
                continue
            artifact_path = resolve_lab_path(str(record.get("path", "")))
            if not artifact_path.is_file():
                errors.append(f"Frozen artifact is missing: {artifact_id}")
                continue
            if sha256_file(artifact_path) != record.get("sha256"):
                errors.append(f"Frozen artifact hash mismatch: {artifact_id}")
            if artifact_path.stat().st_size != record.get("bytes"):
                errors.append(f"Frozen artifact byte count mismatch: {artifact_id}")

    pilot = data.get("pilot", {})
    expected_plan_hash = pilot.get("expected_plan_sha256")
    if not isinstance(expected_plan_hash, str) or len(expected_plan_hash) != 64:
        errors.append("Pilot requires an expected_plan_sha256")
    else:
        try:
            plan = generate_plan(path, "pilot")
            material = "".join(f"{json.dumps(row, sort_keys=True)}\n" for row in plan)
            actual_plan_hash = sha256_bytes(material.encode("utf-8"))
            if actual_plan_hash != expected_plan_hash:
                errors.append("Pilot plan hash mismatch")
            if len(plan) != pilot.get("execution_cells"):
                errors.append("Pilot execution cell count mismatch")
        except (KeyError, TypeError, ValueError) as exc:
            errors.append(f"Pilot plan validation failed: {exc}")
    return errors


def validate_lab() -> dict[str, Any]:
    errors: list[str] = []
    snapshot_dirs = sorted(path.parent for path in LAB_ROOT.glob("snapshots/*/snapshot-manifest.json"))
    if not snapshot_dirs:
        errors.append("No snapshot manifests found")
    for snapshot_dir in snapshot_dirs:
        errors.extend(validate_snapshot(snapshot_dir))
    workflow_errors, workflows = validate_workflows(LAB_ROOT / "workflows/workflows-v1.json")
    errors.extend(workflow_errors)
    rubric_errors, _ = validate_rubric(LAB_ROOT / "rubrics/behavior-rubric-v1.json")
    errors.extend(rubric_errors)
    fixture_errors, fixtures = validate_fixtures(LAB_ROOT / "fixtures/fixtures-v1.jsonl")
    errors.extend(fixture_errors)
    check_registry_errors, _ = validate_check_registry(
        LAB_ROOT / "fixtures/check-registry-v1.json", fixtures
    )
    errors.extend(check_registry_errors)
    score_errors, score_rows = validate_scores(LAB_ROOT / "scores/score-ledger.csv")
    errors.extend(score_errors)
    errors.extend(validate_static_audit(LAB_ROOT / "scores/static-design-audit-2026-07-28.csv"))
    errors.extend(validate_experiment(LAB_ROOT / "experiments/EXP-PP-V1-PREREG.json", workflows, fixtures))
    return {
        "valid": not errors,
        "lab": str(LAB_ROOT),
        "snapshots": len(snapshot_dirs),
        "fixtures": len(fixtures),
        "score_rows": len(score_rows),
        "behavioral_efficacy": "not-run" if not score_rows else "scores-present",
        "errors": errors,
    }


def stable_anonymous_id(experiment_id: str, seed: int, fixture_id: str, workflow_id: str, trial: int) -> str:
    material = f"{experiment_id}|{seed}|{fixture_id}|{workflow_id}|{trial}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:16]


def generate_plan(experiment_path: Path, phase: str, allow_holdout: bool = False) -> list[dict[str, Any]]:
    experiment = load_json(experiment_path)
    fixtures = load_jsonl(LAB_ROOT / experiment["fixture_registry"])
    if phase == "pilot":
        phase_config = experiment["pilot"]
        fixture_ids = phase_config["fixture_ids"]
        workflow_ids = phase_config["workflow_ids"]
        trials = int(phase_config["trials"])
    elif phase == "full":
        fixture_ids = [row["fixture_id"] for row in fixtures]
        workflow_ids = experiment["full_workflows"]
        trials = int(experiment["trials"])
        if any(row["split"] == "holdout" for row in fixtures) and not allow_holdout:
            raise ValueError("Full plan contains holdout fixtures; pass --allow-holdout only after the freeze gate")
    else:
        raise ValueError(f"Unknown phase: {phase}")
    fixture_map = {row["fixture_id"]: row for row in fixtures}
    seed = int(experiment["seed"])
    records: list[dict[str, Any]] = []
    for fixture_index, fixture_id in enumerate(fixture_ids):
        if fixture_id not in fixture_map:
            raise ValueError(f"Unknown fixture in plan: {fixture_id}")
        for trial in range(1, trials + 1):
            shift = (fixture_index + trial - 1) % len(workflow_ids)
            ordered = workflow_ids[shift:] + workflow_ids[:shift]
            if trial % 2 == 0:
                ordered = list(reversed(ordered))
            for order_index, workflow_id in enumerate(ordered, start=1):
                anonymous_id = stable_anonymous_id(
                    experiment["experiment_id"], seed, fixture_id, workflow_id, trial
                )
                orientation = "left" if int(anonymous_id[-1], 16) % 2 == 0 else "right"
                records.append(
                    {
                        "experiment_id": experiment["experiment_id"],
                        "phase": phase,
                        "run_id": f"{experiment['experiment_id']}-{anonymous_id}",
                        "anonymous_id": anonymous_id,
                        "fixture_id": fixture_id,
                        "split": fixture_map[fixture_id]["split"],
                        "domain": fixture_map[fixture_id]["domain"],
                        "workflow_id": workflow_id,
                        "trial": trial,
                        "block_order": order_index,
                        "pair_orientation": orientation,
                        "skill_snapshot_id": experiment["skill_snapshot_id"],
                        "seed": seed,
                    }
                )
    return records


def quantile(values: list[float], probability: float) -> float:
    if not values:
        raise ValueError("Cannot compute quantile of empty values")
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def wilson_interval(successes: float, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if total <= 0:
        return (math.nan, math.nan)
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    margin = z * math.sqrt((proportion * (1 - proportion) + z * z / (4 * total)) / total) / denominator
    return (max(0.0, center - margin), min(1.0, center + margin))


def bootstrap_delta(
    deltas: dict[str, float], fixture_map: dict[str, dict[str, Any]], seed: int, samples: int = 10_000
) -> tuple[float, float]:
    strata: dict[str, list[str]] = defaultdict(list)
    for fixture_id in deltas:
        strata[str(fixture_map[fixture_id]["domain"])].append(fixture_id)
    rng = random.Random(seed)
    estimates: list[float] = []
    for _ in range(samples):
        sampled: list[float] = []
        for fixture_ids in strata.values():
            sampled.extend(deltas[rng.choice(fixture_ids)] for _ in fixture_ids)
        estimates.append(statistics.fmean(sampled))
    return (quantile(estimates, 0.025), quantile(estimates, 0.975))


def summarize_scores(score_path: Path, baseline: str, seed: int = 20260728) -> dict[str, Any]:
    errors, rows = validate_scores(score_path)
    if errors:
        raise ValueError("; ".join(errors))
    rows = [row for row in rows if row.get("record_status") == "adjudicated"]
    if not rows:
        return {"status": "not-run", "score_rows": 0, "behavioral_efficacy": "Unknown"}
    fixtures = load_jsonl(LAB_ROOT / "fixtures/fixtures-v1.jsonl")
    fixture_map = {row["fixture_id"]: row for row in fixtures}
    baseline_cost: dict[tuple[str, str], float] = {}
    parsed: list[dict[str, Any]] = []
    for row in rows:
        calls = float(row["calls"])
        input_chars = float(row["input_chars"])
        output_chars = float(row["output_chars"])
        cost = calls + input_chars / 4000.0 + output_chars / 4000.0
        record = dict(row)
        record["cost"] = cost
        parsed.append(record)
        if row["workflow_id"] == baseline:
            baseline_cost[(row["fixture_id"], row["trial"])] = cost
    for record in parsed:
        key = (record["fixture_id"], record["trial"])
        if key not in baseline_cost:
            raise ValueError(f"Missing matched baseline cost for {key}")
        efficiency = 100.0 * min(1.0, baseline_cost[key] / record["cost"])
        outcome = compute_outcome(
            float(record["deterministic_score"]),
            float(record["human_score"]),
            efficiency,
            is_true(record["critical_gate"]),
        )
        if record["efficiency_score"] and not math.isclose(float(record["efficiency_score"]), efficiency, abs_tol=0.05):
            raise ValueError(f"Stored efficiency mismatch for {record['run_id']}")
        if record["outcome_score"] and not math.isclose(float(record["outcome_score"]), outcome, abs_tol=0.05):
            raise ValueError(f"Stored outcome mismatch for {record['run_id']}")
        record["computed_efficiency"] = efficiency
        record["computed_outcome"] = outcome
    workflow_runs: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in parsed:
        workflow_runs[record["workflow_id"]].append(record)
    fixture_scores: dict[str, dict[str, float]] = defaultdict(dict)
    summary: dict[str, Any] = {}
    for workflow_id, workflow_rows in sorted(workflow_runs.items()):
        by_fixture: dict[str, list[float]] = defaultdict(list)
        for record in workflow_rows:
            by_fixture[record["fixture_id"]].append(record["computed_outcome"])
        fixture_scores[workflow_id] = {
            fixture_id: statistics.fmean(values) for fixture_id, values in by_fixture.items()
        }
        values = [record["computed_outcome"] for record in workflow_rows]
        summary[workflow_id] = {
            "runs": len(workflow_rows),
            "fixtures": len(by_fixture),
            "mean_s": round(statistics.fmean(values), 4),
            "median_s": round(statistics.median(values), 4),
            "critical_gate_rate": round(
                sum(is_true(record["critical_gate"]) for record in workflow_rows) / len(workflow_rows), 4
            ),
            "mean_cost": round(statistics.fmean(record["cost"] for record in workflow_rows), 4),
        }
    if baseline not in fixture_scores:
        raise ValueError(f"Baseline {baseline} has no adjudicated scores")
    comparisons: dict[str, Any] = {}
    baseline_scores = fixture_scores[baseline]
    for workflow_id, scores in sorted(fixture_scores.items()):
        if workflow_id == baseline:
            continue
        shared = sorted(set(scores) & set(baseline_scores))
        if not shared:
            continue
        deltas = {fixture_id: scores[fixture_id] - baseline_scores[fixture_id] for fixture_id in shared}
        low, high = bootstrap_delta(deltas, fixture_map, seed)
        wins = sum(value > 1e-9 for value in deltas.values())
        ties = sum(abs(value) <= 1e-9 for value in deltas.values())
        preference = (wins + 0.5 * ties) / len(shared)
        pref_low, pref_high = wilson_interval(wins + 0.5 * ties, len(shared))
        by_domain: dict[str, list[float]] = defaultdict(list)
        for fixture_id, value in deltas.items():
            by_domain[str(fixture_map[fixture_id]["domain"])].append(value)
        comparisons[workflow_id] = {
            "paired_fixtures": len(shared),
            "mean_delta_s": round(statistics.fmean(deltas.values()), 4),
            "median_delta_s": round(statistics.median(deltas.values()), 4),
            "bootstrap_95_ci": [round(low, 4), round(high, 4)],
            "pairwise_preference": round(preference, 4),
            "pairwise_wilson_95_ci": [round(pref_low, 4), round(pref_high, 4)],
            "domain_mean_deltas": {
                domain: round(statistics.fmean(values), 4) for domain, values in sorted(by_domain.items())
            },
        }
    return {
        "status": "summarized",
        "baseline": baseline,
        "score_rows": len(rows),
        "workflow_summary": summary,
        "paired_comparisons": comparisons,
        "notes": "Scores remain experiment-scoped; apply preregistered gates before any adoption claim.",
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate", help="Validate the frozen lab and ledgers")
    plan = subparsers.add_parser("plan", help="Print a deterministic JSONL run plan")
    plan.add_argument("--experiment", default="experiments/EXP-PP-V1-PREREG.json")
    plan.add_argument("--phase", choices=("pilot", "full"), default="pilot")
    plan.add_argument("--allow-holdout", action="store_true")
    summarize = subparsers.add_parser("summarize", help="Print a score summary JSON")
    summarize.add_argument("--scores", default="scores/score-ledger.csv")
    summarize.add_argument("--baseline", default="B01_STATIC_MIN_1CALL")
    summarize.add_argument("--seed", type=int, default=20260728)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        if args.command == "validate":
            result = validate_lab()
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0 if result["valid"] else 1
        if args.command == "plan":
            experiment_path = resolve_lab_path(args.experiment)
            for record in generate_plan(experiment_path, args.phase, args.allow_holdout):
                print(json.dumps(record, sort_keys=True))
            return 0
        if args.command == "summarize":
            result = summarize_scores(resolve_lab_path(args.scores), args.baseline, args.seed)
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
