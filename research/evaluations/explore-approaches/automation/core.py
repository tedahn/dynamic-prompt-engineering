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
import signal
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterable, Sequence


class PipelineError(RuntimeError):
    """Raised when a lifecycle invariant is not satisfied."""


PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600


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


def _create_private_directories(path: Path) -> None:
    """Create only missing directories, then remove any umask-dependent access."""

    missing: list[Path] = []
    current = path
    while not current.exists() and not current.is_symlink():
        missing.append(current)
        if current.parent == current:
            break
        current = current.parent
    path.mkdir(parents=True, exist_ok=True, mode=PRIVATE_DIRECTORY_MODE)
    for directory in reversed(missing):
        os.chmod(directory, PRIVATE_DIRECTORY_MODE, follow_symlinks=False)


def ensure_private_directory(path: Path, *, create: bool = False, normalize: bool = False) -> None:
    """Require an owner-only, caller-owned regular directory."""

    if create and not path.exists() and not path.is_symlink():
        _create_private_directories(path)
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise PipelineError(f"Private directory is missing: {path}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise PipelineError(f"Private directory is unsafe: {path}")
    if metadata.st_uid != os.getuid():
        raise PipelineError(f"Private directory is not owned by the current user: {path}")
    if normalize and stat.S_IMODE(metadata.st_mode) != PRIVATE_DIRECTORY_MODE:
        os.chmod(path, PRIVATE_DIRECTORY_MODE, follow_symlinks=False)
        metadata = path.lstat()
    if stat.S_IMODE(metadata.st_mode) != PRIVATE_DIRECTORY_MODE:
        raise PipelineError(f"Private directory mode must be 0700: {path}")


def ensure_private_file(path: Path, *, normalize: bool = False) -> None:
    """Require an owner-only, caller-owned regular non-symlink file."""

    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise PipelineError(f"Private file is missing: {path}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise PipelineError(f"Private file is unsafe: {path}")
    if metadata.st_uid != os.getuid():
        raise PipelineError(f"Private file is not owned by the current user: {path}")
    if normalize and stat.S_IMODE(metadata.st_mode) != PRIVATE_FILE_MODE:
        os.chmod(path, PRIVATE_FILE_MODE, follow_symlinks=False)
        metadata = path.lstat()
    if stat.S_IMODE(metadata.st_mode) != PRIVATE_FILE_MODE:
        raise PipelineError(f"Private file mode must be 0600: {path}")


def verify_private_tree(root: Path) -> None:
    """Fail closed when private persisted state drifts in type, owner, or mode."""

    ensure_private_directory(root)
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        ensure_private_directory(current_path)
        for name in directories:
            ensure_private_directory(current_path / name)
        for name in files:
            ensure_private_file(current_path / name)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PipelineError(f"Expected a JSON object: {path}")
    return value


def atomic_write_json(path: Path, value: Any) -> None:
    if path.exists() or path.is_symlink():
        ensure_private_file(path, normalize=True)
    _create_private_directories(path.parent)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        os.chmod(temporary_path, PRIVATE_FILE_MODE, follow_symlinks=False)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        ensure_private_file(path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def load_config(path: Path) -> dict[str, Any]:
    config = load_json(path)
    required = {
        "schema_version",
        "pipeline_id",
        "candidate",
        "evaluation",
        "privacy",
        "roles",
        "holdout_verification",
        "human_review_verification",
        "execution_verification",
        "approval_verification",
        "provider_execution_limits",
        "promotion",
        "installation",
    }
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

    minimum_tasks_value = config["evaluation"].get("minimum_holdout_tasks")
    minimum_tasks_valid = (
        isinstance(minimum_tasks_value, int)
        and not isinstance(minimum_tasks_value, bool)
        and minimum_tasks_value >= 29
    )
    minimum_tasks = minimum_tasks_value if minimum_tasks_valid else 29
    required_trials = int(config["evaluation"]["trials_per_task"])
    task_count_value = coverage.get("tasks")
    task_count = (
        int(task_count_value)
        if minimum_tasks_valid
        and isinstance(task_count_value, int)
        and not isinstance(task_count_value, bool)
        and task_count_value >= minimum_tasks
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

    critical_gate_ids = config["evaluation"].get("critical_gate_ids")
    critical_gate_coverage = quality.get("critical_gate_coverage")
    minimum_critical_opportunities = thresholds.get("critical_gate_independent_opportunities_min")
    maximum_critical_upper = thresholds.get("critical_gate_failure_rate_upper95_max")
    critical_opportunity_unit = config["evaluation"].get("analysis_plan", {}).get(
        "critical_opportunity_unit"
    )
    critical_family_handling = config["evaluation"].get("analysis_plan", {}).get(
        "critical_family_handling"
    )
    critical_coverage_valid = (
        isinstance(critical_gate_ids, list)
        and bool(critical_gate_ids)
        and len(set(critical_gate_ids)) == len(critical_gate_ids)
        and all(isinstance(gate, str) and gate for gate in critical_gate_ids)
        and isinstance(critical_gate_coverage, dict)
        and set(critical_gate_coverage) == set(critical_gate_ids)
        and isinstance(minimum_critical_opportunities, int)
        and not isinstance(minimum_critical_opportunities, bool)
        and minimum_critical_opportunities >= 29
        and isinstance(maximum_critical_upper, (int, float))
        and not isinstance(maximum_critical_upper, bool)
        and math.isfinite(float(maximum_critical_upper))
        and 0 < float(maximum_critical_upper) <= 0.10
        and task_count is not None
        and critical_opportunity_unit == "holdout_owner_attested_family"
        and critical_family_handling == "duplicate_family_counts_once_any_failure_fails_family"
    )
    critical_rate_within_bound = True
    critical_gate_failure_observed = False
    if critical_coverage_valid:
        for gate in critical_gate_ids:
            gate_record = critical_gate_coverage[gate]
            if not isinstance(gate_record, dict):
                critical_coverage_valid = False
                break
            opportunities = gate_record.get("independent_opportunities")
            failures = gate_record.get("failed_independent_opportunities")
            upper = gate_record.get("failure_rate_upper95")
            if (
                gate_record.get("opportunity_unit") != "holdout_owner_attested_family"
                or not isinstance(opportunities, int)
                or isinstance(opportunities, bool)
                or opportunities < minimum_critical_opportunities
                or opportunities > task_count
                or not isinstance(failures, int)
                or isinstance(failures, bool)
                or failures < 0
                or failures > opportunities
                or not isinstance(upper, (int, float))
                or isinstance(upper, bool)
                or not math.isfinite(float(upper))
                or not 0 <= float(upper) <= 1
            ):
                critical_coverage_valid = False
                break
            expected_upper = 1.0 if failures else 1.0 - math.pow(0.05, 1.0 / opportunities)
            if not math.isclose(float(upper), expected_upper, rel_tol=1e-12, abs_tol=1e-12):
                critical_coverage_valid = False
                break
            critical_gate_failure_observed = critical_gate_failure_observed or failures > 0
            critical_rate_within_bound = (
                critical_rate_within_bound and float(upper) <= float(maximum_critical_upper)
            )
    checks["critical_gate_opportunity_coverage"] = True if critical_coverage_valid else None
    if not critical_coverage_valid:
        checks["critical_gate_rate_bound"] = None
        reasons.append("missing_or_invalid:critical_gate_opportunity_coverage")
    elif critical_rate_within_bound:
        checks["critical_gate_rate_bound"] = True
    elif critical_gate_failure_observed:
        checks["critical_gate_rate_bound"] = False
    else:
        checks["critical_gate_rate_bound"] = None
        reasons.append("missing_or_invalid:critical_gate_failure_rate_bound")

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


_PROCESS_CONTAINMENT_ENV = "CODEX_LIFECYCLE_PROCESS_TOKEN"
_PROCESS_SNAPSHOT_TIMEOUT_SECONDS = 1.0


def _posix_ps_path() -> Path | None:
    for candidate in (Path("/bin/ps"), Path("/usr/bin/ps")):
        if candidate.is_file():
            return candidate
    return None


def _snapshot_posix_processes(*, include_environment: bool) -> dict[int, dict[str, Any]]:
    ps_path = _posix_ps_path()
    if ps_path is None:
        raise PipelineError("POSIX process containment requires an absolute ps executable")
    argv = [str(ps_path)]
    if include_environment and sys.platform == "darwin":
        argv.append("eww")
    argv.extend(["-axo", "pid=,ppid=,pgid=,sess=,lstart=,command="])
    try:
        result = subprocess.run(
            argv,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=_PROCESS_SNAPSHOT_TIMEOUT_SECONDS,
            shell=False,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PipelineError("POSIX process containment snapshot failed") from exc
    if result.returncode != 0:
        raise PipelineError("POSIX process containment snapshot failed")
    processes: dict[int, dict[str, Any]] = {}
    for line in result.stdout.splitlines():
        parts = line.strip().split(None, 9)
        if len(parts) < 9:
            continue
        try:
            pid, parent_pid, process_group_id, session_id = (int(value) for value in parts[:4])
        except ValueError:
            continue
        command = parts[9] if len(parts) == 10 else ""
        if include_environment and sys.platform.startswith("linux"):
            try:
                environment = Path(f"/proc/{pid}/environ").read_bytes().replace(b"\x00", b" ")
                command = f"{command} {environment.decode('utf-8', errors='replace')}"
            except (OSError, PermissionError):
                pass
        processes[pid] = {
            "pid": pid,
            "parent_pid": parent_pid,
            "process_group_id": process_group_id,
            "session_id": session_id,
            "started_at": " ".join(parts[4:9]),
            "command": command,
        }
    if os.getpid() not in processes:
        raise PipelineError("POSIX process containment snapshot omitted the current process")
    return processes


def _process_group_exists(process_group_id: int) -> bool:
    try:
        os.killpg(process_group_id, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _posix_process_isolation_available() -> bool:
    return os.name == "posix" and _posix_ps_path() is not None and all(
        (
            hasattr(os, "killpg"),
            hasattr(signal, "SIGTERM"),
            hasattr(signal, "SIGKILL"),
        )
    )


def require_posix_process_isolation(context: str) -> None:
    """Fail before authority-bearing child launch when POSIX containment is unavailable."""

    if not _posix_process_isolation_available():
        raise PipelineError(f"{context} requires POSIX process-group isolation")
    _snapshot_posix_processes(include_environment=False)


def _containment_members(
    snapshot: dict[int, dict[str, Any]],
    *,
    process_group_id: int,
    token: str,
) -> tuple[dict[int, dict[str, Any]], bool]:
    token_assignment = f"{_PROCESS_CONTAINMENT_ENV}={token}"
    members = {
        pid: process
        for pid, process in snapshot.items()
        if pid == process_group_id or token_assignment in str(process.get("command", ""))
    }
    changed = True
    while changed:
        changed = False
        for pid, process in snapshot.items():
            if pid not in members and process.get("parent_pid") in members:
                members[pid] = process
                changed = True
    escaped = any(
        pid != process_group_id
        and process.get("process_group_id") != process_group_id
        for pid, process in members.items()
    )
    return members, escaped


def _signal_containment(
    process_group_id: int,
    token: str,
    signal_number: int,
    errors: list[str],
) -> bool:
    escaped = False
    try:
        os.killpg(process_group_id, signal_number)
    except ProcessLookupError:
        pass
    except PermissionError:
        errors.append(f"permission_denied:process_group:{signal_number}")
    except OSError:
        errors.append(f"signal_failed:process_group:{signal_number}")
    try:
        snapshot = _snapshot_posix_processes(include_environment=True)
        members, escaped = _containment_members(
            snapshot,
            process_group_id=process_group_id,
            token=token,
        )
    except PipelineError:
        errors.append("process_snapshot_failed")
        members = {}
    for pid in sorted((pid for pid in members if pid != process_group_id), reverse=True):
        try:
            os.kill(pid, signal_number)
        except ProcessLookupError:
            pass
        except PermissionError:
            errors.append(f"permission_denied:process:{pid}:{signal_number}")
        except OSError:
            errors.append(f"signal_failed:process:{pid}:{signal_number}")
    return escaped


def _containment_remaining(
    process_group_id: int,
    token: str,
    errors: list[str],
) -> tuple[bool, bool]:
    group_exists = _process_group_exists(process_group_id)
    try:
        snapshot = _snapshot_posix_processes(include_environment=True)
        members, escaped = _containment_members(
            snapshot,
            process_group_id=process_group_id,
            token=token,
        )
    except PipelineError:
        errors.append("process_snapshot_failed")
        return True, False
    return group_exists or bool(members), escaped


def _close_process_pipes(process: subprocess.Popen[str]) -> None:
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass


def _stop_process_group(
    process: subprocess.Popen[str],
    *,
    token: str,
    termination_grace_seconds: float,
    stdout: str = "",
    stderr: str = "",
) -> tuple[str, str, bool]:
    """Boundedly terminate the group and token-bound escaped descendants, or fail closed."""

    process_group_id = process.pid
    errors: list[str] = []
    escaped = _signal_containment(
        process_group_id,
        token,
        signal.SIGTERM,
        errors,
    )
    deadline = time.monotonic() + termination_grace_seconds
    remaining = True
    while remaining and time.monotonic() < deadline:
        remaining, newly_escaped = _containment_remaining(process_group_id, token, errors)
        escaped = escaped or newly_escaped
        if remaining:
            time.sleep(0.01)

    if remaining:
        escaped = _signal_containment(
            process_group_id,
            token,
            signal.SIGKILL,
            errors,
        ) or escaped
    reap_deadline = time.monotonic() + max(termination_grace_seconds, 0.1)
    while remaining and time.monotonic() < reap_deadline:
        remaining, newly_escaped = _containment_remaining(process_group_id, token, errors)
        escaped = escaped or newly_escaped
        if remaining:
            time.sleep(0.01)

    if process.poll() is None:
        try:
            process.wait(timeout=max(termination_grace_seconds, 0.1))
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            except (PermissionError, OSError):
                errors.append("leader_kill_failed")
            try:
                process.wait(timeout=max(termination_grace_seconds, 0.1))
            except subprocess.TimeoutExpired:
                errors.append("leader_reap_timed_out")
    _close_process_pipes(process)
    final_remaining, newly_escaped = _containment_remaining(process_group_id, token, errors)
    escaped = escaped or newly_escaped
    if final_remaining:
        errors.append("containment_members_survived")
    if errors:
        raise PipelineError(
            "Isolated command containment cleanup failed closed: " + ",".join(sorted(set(errors)))
        )
    return stdout, stderr, escaped


def run_command(
    argv: Sequence[str],
    *,
    cwd: Path | None = None,
    timeout: float = 300.0,
    input_text: str | None = None,
    env: dict[str, str] | None = None,
    inherit_env: bool = True,
    check: bool = True,
    isolate_process_group: bool = False,
    termination_grace_seconds: float = 0.25,
) -> subprocess.CompletedProcess[str]:
    if not argv or any(not isinstance(part, str) or "\x00" in part for part in argv):
        raise PipelineError("Command argv must contain safe strings")
    if timeout <= 0 or termination_grace_seconds <= 0:
        raise PipelineError("Command timeouts must be positive")
    merged_env = os.environ.copy() if inherit_env else {}
    if env:
        merged_env.update(env)
    if isolate_process_group:
        require_posix_process_isolation("Isolated command execution")
        if env and _PROCESS_CONTAINMENT_ENV in env:
            raise PipelineError("Command environment may not override the process-containment token")
        containment_token = hashlib.sha256(os.urandom(32)).hexdigest()
        merged_env[_PROCESS_CONTAINMENT_ENV] = containment_token
        process = subprocess.Popen(
            list(argv),
            cwd=cwd,
            stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=merged_env,
            shell=False,
            start_new_session=True,
        )
        try:
            stdout, stderr = process.communicate(input=input_text, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            partial_stdout = exc.output if isinstance(exc.output, str) else ""
            partial_stderr = exc.stderr if isinstance(exc.stderr, str) else ""
            stdout, stderr, escaped = _stop_process_group(
                process,
                token=containment_token,
                termination_grace_seconds=termination_grace_seconds,
                stdout=partial_stdout,
                stderr=partial_stderr,
            )
            if escaped:
                raise PipelineError(
                    "Isolated command descendant escaped its process group; cleanup completed but retry is forbidden"
                ) from exc
            raise subprocess.TimeoutExpired(list(argv), timeout, output=stdout, stderr=stderr) from exc
        except BaseException:
            _stop_process_group(
                process,
                token=containment_token,
                termination_grace_seconds=termination_grace_seconds,
            )
            raise
        try:
            snapshot = _snapshot_posix_processes(include_environment=True)
            members, escaped = _containment_members(
                snapshot,
                process_group_id=process.pid,
                token=containment_token,
            )
        except PipelineError as exc:
            _stop_process_group(
                process,
                token=containment_token,
                termination_grace_seconds=termination_grace_seconds,
                stdout=stdout,
                stderr=stderr,
            )
            raise PipelineError("Isolated command containment could not be verified after leader exit") from exc
        if _process_group_exists(process.pid) or members:
            _stop_process_group(
                process,
                token=containment_token,
                termination_grace_seconds=termination_grace_seconds,
                stdout=stdout,
                stderr=stderr,
            )
            suffix = " after a descendant escaped its process group" if escaped else ""
            raise PipelineError(
                "An isolated command descendant outlived its leader"
                f"{suffix}; descendants were terminated before continuation"
            )
        result = subprocess.CompletedProcess(list(argv), process.returncode, stdout, stderr)
    else:
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
