"""Shared fail-closed primitives for the explore-approaches lifecycle."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import fnmatch
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import subprocess
import tempfile
from typing import Any, Iterable, Sequence


class PipelineError(RuntimeError):
    """Raised when a lifecycle invariant is not satisfied."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat().replace("+00:00", "Z")


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise PipelineError("Timestamp must include a timezone")
    return parsed.astimezone(timezone.utc)


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PipelineError(f"Expected a JSON object: {path}")
    return value


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def load_config(path: Path) -> dict[str, Any]:
    config = load_json(path)
    required = {"schema_version", "pipeline_id", "candidate", "evaluation", "privacy", "promotion", "installation"}
    missing = sorted(required - config.keys())
    if missing:
        raise PipelineError(f"Pipeline config missing fields: {missing}")
    if config["schema_version"] != "1.0":
        raise PipelineError("Unsupported pipeline config schema")
    thresholds = config.get("evaluation", {}).get("thresholds", {})
    if not thresholds:
        raise PipelineError("Evaluation thresholds are required")
    return config


def is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def require_outside(path: Path, root: Path, label: str) -> None:
    if is_within(path, root):
        raise PipelineError(f"{label} must stay outside the repository: {path}")


def validate_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or not value or any(part in {"", ".", ".."} for part in path.parts):
        raise PipelineError(f"Unsafe relative path: {value!r}")
    return path


def excluded(relative_path: str, patterns: Iterable[str]) -> bool:
    path = PurePosixPath(relative_path)
    return any(path.match(pattern) or fnmatch.fnmatch(relative_path, pattern) for pattern in patterns)


def regular_files(root: Path, relative_root: str, patterns: Iterable[str]) -> list[Path]:
    validate_relative_path(relative_root)
    start = root / relative_root
    if not start.is_dir() or start.is_symlink():
        raise PipelineError(f"Candidate tree is missing or unsafe: {relative_root}")
    output: list[Path] = []
    for current, directories, files in os.walk(start, followlinks=False):
        current_path = Path(current)
        for directory in list(directories):
            candidate = current_path / directory
            relative = candidate.relative_to(root).as_posix()
            if candidate.is_symlink():
                raise PipelineError(f"Symlink is forbidden in candidate tree: {relative}")
            if excluded(relative, patterns):
                directories.remove(directory)
        for filename in files:
            candidate = current_path / filename
            relative = candidate.relative_to(root).as_posix()
            if excluded(relative, patterns):
                continue
            if candidate.is_symlink() or not candidate.is_file():
                raise PipelineError(f"Only regular files may be promoted: {relative}")
            output.append(candidate)
    return sorted(output)


def _csv_records(path: Path, record_ids: Sequence[str]) -> list[dict[str, Any]]:
    raw_lines = path.read_text(encoding="utf-8").splitlines()
    rows = list(csv.reader(raw_lines))
    if not rows:
        raise PipelineError(f"CSV ledger is empty: {path}")
    header = rows[0]
    selected: list[dict[str, Any]] = []
    by_id = {row[0]: (row, raw_line) for row, raw_line in zip(rows[1:], raw_lines[1:]) if row}
    for record_id in record_ids:
        match = by_id.get(record_id)
        if match is None:
            raise PipelineError(f"Missing approved ledger record {record_id} in {path}")
        row, raw_line = match
        if len(row) != len(header):
            raise PipelineError(f"Malformed ledger record {record_id} in {path}")
        selected.append({"record_id": record_id, "values": row, "line": raw_line})
    return selected


def _markdown_records(path: Path, record_ids: Sequence[str]) -> list[dict[str, str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    selected: list[dict[str, str]] = []
    for record_id in record_ids:
        matches = [line for line in lines if line.startswith(f"| {record_id} |")]
        if len(matches) != 1:
            raise PipelineError(f"Expected one markdown record {record_id} in {path}, found {len(matches)}")
        selected.append({"record_id": record_id, "line": matches[0]})
    return selected


def build_candidate_manifest(repo_root: Path, config: dict[str, Any]) -> dict[str, Any]:
    promotion = config["promotion"]
    patterns = list(promotion.get("excluded_globs", []))
    file_paths: set[Path] = set()
    for tree in promotion.get("copy_trees", []):
        file_paths.update(regular_files(repo_root, tree, patterns))
    for relative in promotion.get("copy_files", []):
        validate_relative_path(relative)
        path = repo_root / relative
        if not path.is_file() or path.is_symlink():
            raise PipelineError(f"Approved file is missing or unsafe: {relative}")
        file_paths.add(path)
    files = [
        {
            "path": path.relative_to(repo_root).as_posix(),
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in sorted(file_paths)
    ]
    csv_records: list[dict[str, Any]] = []
    for relative, ids in promotion.get("csv_record_allowlist", {}).items():
        validate_relative_path(relative)
        for record in _csv_records(repo_root / relative, ids):
            csv_records.append({"path": relative, **record})
    markdown_records: list[dict[str, str]] = []
    for relative, ids in promotion.get("markdown_record_allowlist", {}).items():
        validate_relative_path(relative)
        for record in _markdown_records(repo_root / relative, ids):
            markdown_records.append({"path": relative, **record})
    body = {
        "schema_version": "1.0",
        "pipeline_id": config["pipeline_id"],
        "candidate_name": config["candidate"]["name"],
        "candidate_version": config["candidate"]["version"],
        "files": files,
        "csv_records": csv_records,
        "markdown_records": markdown_records,
    }
    return {**body, "manifest_sha256": sha256_json(body)}


def _number(value: Any, label: str, reasons: list[str]) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        reasons.append(f"missing_or_invalid:{label}")
        return None
    return float(value)


def assess_summary(summary: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    """Classify a completed evaluation without inventing unavailable evidence."""
    reasons: list[str] = []
    checks: dict[str, bool | None] = {}
    integrity = summary.get("integrity", {})
    coverage = summary.get("coverage", {})
    quality = summary.get("quality", {})
    resources = summary.get("resources", {})
    analysis_coverage = summary.get("analysis_coverage", {})
    thresholds = config["evaluation"]["thresholds"]

    if integrity.get("valid") is not True or integrity.get("contamination_detected") is True:
        return {"classification": "invalid", "promotable": False, "reasons": ["integrity_invalid_or_contaminated"], "checks": {}}

    minimum_tasks = int(config["evaluation"]["minimum_holdout_tasks"])
    required_trials = int(config["evaluation"]["trials_per_task"])
    task_count_value = coverage.get("tasks")
    task_count = (
        int(task_count_value)
        if isinstance(task_count_value, int) and not isinstance(task_count_value, bool) and task_count_value >= minimum_tasks
        else None
    )
    required_cells = task_count * required_trials * len(config["evaluation"]["arms"]) if task_count is not None else None
    required_comparisons = task_count * required_trials if task_count is not None else None
    checks["coverage"] = (
        task_count is not None
        and coverage.get("trials_per_task") == required_trials
        and coverage.get("expected_cells") == required_cells
        and coverage.get("complete_cells") == required_cells
        and coverage.get("final_graded_cells") == required_cells
        and coverage.get("expected_comparisons") == required_comparisons
        and coverage.get("final_comparisons") == required_comparisons
        and coverage.get("failed_cells", 0) == 0
    )
    if not checks["coverage"]:
        reasons.append("incomplete_coverage")
    checks["human_final"] = coverage.get("human_final") is True and coverage.get("adjudication_complete") is True
    if thresholds.get("require_human_final") and not checks["human_final"]:
        reasons.append("human_final_review_missing")

    cluster_specs = {
        "c01_minus_b01_task_clusters": "quality_task_cluster_coverage_min",
        "c01_minus_b02_task_clusters": "quality_task_cluster_coverage_min",
        "preference_task_clusters": "preference_task_cluster_coverage_min",
        "latency_ratio_task_clusters": "resource_task_cluster_coverage_min",
        "token_ratio_task_clusters": "resource_task_cluster_coverage_min",
    }
    cluster_coverage_valid = task_count is not None and isinstance(analysis_coverage, dict)
    if cluster_coverage_valid and analysis_coverage.get("expected_task_clusters") != task_count:
        cluster_coverage_valid = False
    for field, threshold_name in cluster_specs.items():
        count = analysis_coverage.get(field) if isinstance(analysis_coverage, dict) else None
        fraction = thresholds.get(threshold_name)
        if (
            task_count is None
            or not isinstance(count, int)
            or isinstance(count, bool)
            or count < 0
            or count > task_count
            or not isinstance(fraction, (int, float))
            or isinstance(fraction, bool)
            or not math.isfinite(float(fraction))
            or not 0 <= float(fraction) <= 1
            or count < math.ceil(task_count * float(fraction) - 1e-12)
        ):
            cluster_coverage_valid = False
    checks["analysis_cluster_coverage"] = True if cluster_coverage_valid else None
    if not cluster_coverage_valid:
        reasons.append("missing_or_invalid:analysis_cluster_coverage")

    critical = _number(quality.get("critical_candidate_failures"), "critical_candidate_failures", reasons)
    pass_rate = _number(quality.get("other_hard_gate_pass_rate"), "other_hard_gate_pass_rate", reasons)
    c01_b01 = quality.get("c01_minus_b01", {})
    c01_b02 = quality.get("c01_minus_b02", {})
    preference = quality.get("c01_vs_b01_preference", {})
    require_bounds = thresholds.get("require_confidence_bounds") is True
    c01_b01_value = _number(c01_b01.get("lower95" if require_bounds else "estimate"), "c01_minus_b01", reasons)
    c01_b02_value = _number(c01_b02.get("lower95" if require_bounds else "estimate"), "c01_minus_b02", reasons)
    preference_value = _number(preference.get("lower95" if require_bounds else "rate"), "c01_vs_b01_preference", reasons)
    checks["critical_failures"] = critical is not None and critical <= thresholds["critical_candidate_failures_max"]
    checks["other_hard_gates"] = pass_rate is not None and pass_rate >= thresholds["other_hard_gate_pass_rate_min"]
    checks["c01_minus_b01"] = c01_b01_value is not None and c01_b01_value >= thresholds["c01_minus_b01_mean_min"]
    checks["c01_minus_b02"] = c01_b02_value is not None and c01_b02_value >= thresholds["c01_minus_b02_mean_min"]
    checks["preference"] = preference_value is not None and preference_value >= thresholds["c01_vs_b01_preference_min"]

    latency = resources.get("latency_ratio", {})
    tokens = resources.get("token_ratio", {})
    latency_value = _number(latency.get("upper95" if require_bounds else "median"), "latency_ratio", reasons)
    token_value = _number(tokens.get("upper95" if require_bounds else "median"), "token_ratio", reasons)
    checks["usage_complete"] = resources.get("usage_complete") is True
    checks["latency"] = latency_value is not None and latency_value <= thresholds["latency_ratio_max"]
    checks["tokens"] = token_value is not None and token_value <= thresholds["token_ratio_max"]
    if thresholds.get("require_complete_usage") and not checks["usage_complete"]:
        reasons.append("usage_incomplete")

    domain_deltas = quality.get("domain_deltas")
    expected_domains = coverage.get("expected_domains")
    if not isinstance(domain_deltas, dict) or not domain_deltas:
        checks["domains"] = None
        reasons.append("missing_or_invalid:domain_deltas")
    elif not isinstance(expected_domains, list) or set(domain_deltas) != set(expected_domains):
        checks["domains"] = None
        reasons.append("missing_or_invalid:domain_coverage")
    else:
        checks["domains"] = all(isinstance(value, (int, float)) and value >= thresholds["domain_delta_min"] for value in domain_deltas.values())

    unavailable = any(value is None for value in checks.values()) or any(reason.startswith("missing_or_invalid:") for reason in reasons)
    if unavailable or not checks["coverage"] or (thresholds.get("require_human_final") and not checks["human_final"]) or (thresholds.get("require_complete_usage") and not checks["usage_complete"]):
        classification = "inconclusive"
    elif critical is not None and critical > thresholds["critical_candidate_failures_max"]:
        classification = "rejected"
        reasons.append("critical_candidate_failure")
    elif all(value is True for value in checks.values()):
        classification = "promotable"
    else:
        classification = "rejected"
        reasons.extend(sorted(name for name, passed in checks.items() if passed is False and name not in {"coverage", "human_final", "usage_complete"}))
    return {"classification": classification, "promotable": classification == "promotable", "reasons": sorted(set(reasons)), "checks": checks}


def run_command(
    argv: Sequence[str],
    *,
    cwd: Path | None = None,
    timeout: float = 300.0,
    input_text: str | None = None,
    env: dict[str, str] | None = None,
    inherit_env: bool = True,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    if not argv or any(not isinstance(part, str) or "\x00" in part for part in argv):
        raise PipelineError("Command argv must contain safe strings")
    merged_env = os.environ.copy() if inherit_env else {}
    if env:
        merged_env.update(env)
    result = subprocess.run(
        list(argv),
        cwd=cwd,
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        env=merged_env,
        shell=False,
    )
    if check and result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or f"Command failed with {result.returncode}"
        raise PipelineError(message)
    return result
