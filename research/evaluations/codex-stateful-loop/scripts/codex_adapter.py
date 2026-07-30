#!/usr/bin/env python3
"""Guarded, preflight-only Codex CLI adapter for the stateful-loop study.

This module deliberately has no execution command. It proves that a frozen
episode plan, a frozen runtime profile, a scoped human approval, and the local
Codex runtime agree. A later, separately reviewed change must add execution.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import stat
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


LAB_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = LAB_ROOT / "config" / "loop-v1.json"
APPROVAL_SCHEMA_PATH = LAB_ROOT / "schemas" / "run-approval.schema.json"
DEFAULT_NO_TOOL_CWD = Path("/private/var/empty")
MAX_APPROVED_CELLS = 500
MAX_APPROVAL_WINDOW = timedelta(hours=72)
CLOCK_SKEW = timedelta(minutes=5)

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
NO_TOOL_FEATURE_DISABLES = ("shell_snapshot", "shell_tool", "unified_exec")
FORBIDDEN_CODEX_HOME_ENTRIES = (
    "AGENTS.md",
    "config.toml",
    "hooks.json",
    "skills",
    "plugins",
    "memories",
)


class AdapterError(RuntimeError):
    """A fail-closed preflight error."""


@dataclass(frozen=True)
class FrozenEpoch:
    epoch_id: str
    stage: str
    plan_sha256: str
    plan: dict[str, Any]
    selected_rows: tuple[dict[str, Any], ...]


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AdapterError(f"Cannot load {label}: {type(exc).__name__}") from exc
    if not isinstance(value, dict):
        raise AdapterError(f"{label} must be a JSON object")
    return value


def parse_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str):
        raise AdapterError(f"{field} must be an RFC 3339 timestamp")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise AdapterError(f"{field} must be an RFC 3339 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AdapterError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _is_named_human(value: Any) -> bool:
    if not isinstance(value, str) or len(value.strip()) < 3:
        return False
    folded = value.strip().casefold()
    machine_names = {"ai", "agent", "automation", "bot", "codex", "model", "system"}
    machine_prefixes = ("agent:", "automation:", "bot:", "codex:", "model:", "system:")
    return folded not in machine_names and not folded.startswith(machine_prefixes)


def validate_approval(
    approval: dict[str, Any],
    *,
    now: datetime,
    expected_epoch_id: str,
    expected_stage: str,
    expected_plan_sha256: str,
    expected_runtime_sha256: str,
) -> tuple[str, ...]:
    required = {
        "schema_version",
        "approval_id",
        "approver_type",
        "approved_by",
        "approved_at",
        "expires_at",
        "epoch_id",
        "plan_sha256",
        "runtime_profile_sha256",
        "maximum_cells",
        "cell_ids",
        "provider_processing_acknowledged",
        "allowed_stage",
    }
    allowed = required | {"notes"}
    missing = sorted(required - approval.keys())
    extra = sorted(approval.keys() - allowed)
    if missing:
        raise AdapterError(f"Approval is missing required fields: {missing}")
    if extra:
        raise AdapterError(f"Approval contains unsupported fields: {extra}")
    if approval["schema_version"] != "1.0":
        raise AdapterError("Approval schema_version must be 1.0")
    if not isinstance(approval["approval_id"], str) or not approval["approval_id"].strip():
        raise AdapterError("approval_id must be a nonempty string")
    if approval["approver_type"] != "human" or not _is_named_human(approval["approved_by"]):
        raise AdapterError("approved_by must identify a named human approver")
    approved_at = parse_timestamp(approval["approved_at"], "approved_at")
    expires_at = parse_timestamp(approval["expires_at"], "expires_at")
    current = now.astimezone(timezone.utc)
    if approved_at > current + CLOCK_SKEW:
        raise AdapterError("Approval time is in the future")
    if expires_at <= current:
        raise AdapterError("Approval has expired")
    if expires_at <= approved_at:
        raise AdapterError("expires_at must be later than approved_at")
    if expires_at - approved_at > MAX_APPROVAL_WINDOW:
        raise AdapterError("Approval validity window exceeds 72 hours")
    if approval["epoch_id"] != expected_epoch_id:
        raise AdapterError("Approval epoch_id does not match the requested epoch")
    if approval["allowed_stage"] != expected_stage:
        raise AdapterError("Approval stage does not match the frozen epoch")
    if approval["plan_sha256"] != expected_plan_sha256:
        raise AdapterError("Approval plan_sha256 does not match the frozen plan")
    if approval["runtime_profile_sha256"] != expected_runtime_sha256:
        raise AdapterError("Approval runtime_profile_sha256 does not match the frozen runtime")
    if approval["provider_processing_acknowledged"] is not True:
        raise AdapterError("Provider processing must be explicitly acknowledged")
    maximum = approval["maximum_cells"]
    cell_ids = approval["cell_ids"]
    if isinstance(maximum, bool) or not isinstance(maximum, int) or not 1 <= maximum <= MAX_APPROVED_CELLS:
        raise AdapterError(f"maximum_cells must be between 1 and {MAX_APPROVED_CELLS}")
    if not isinstance(cell_ids, list) or not cell_ids or any(
        not isinstance(value, str) or not value for value in cell_ids
    ):
        raise AdapterError("cell_ids must be a nonempty list of strings")
    if len(cell_ids) != len(set(cell_ids)):
        raise AdapterError("cell_ids must be unique")
    if len(cell_ids) != maximum:
        raise AdapterError("maximum_cells must exactly equal the approved cell_ids count")
    return tuple(cell_ids)


def _study_root(config_path: Path) -> Path:
    return config_path.resolve().parent.parent if config_path.parent.name == "config" else config_path.resolve().parent


def load_frozen_runtime(
    config_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], Path, str]:
    config = load_object(config_path, "study config")
    target = config.get("target_surface")
    if not isinstance(target, dict):
        raise AdapterError("Study config is missing target_surface")
    relative = target.get("runtime_profile_path")
    expected_digest = target.get("runtime_profile_sha256")
    if not isinstance(relative, str) or not re.fullmatch(r"[a-f0-9]{64}", str(expected_digest)):
        raise AdapterError("Study config has an invalid frozen runtime reference")
    runtime_path = Path(relative)
    if not runtime_path.is_absolute():
        runtime_path = (_study_root(config_path) / runtime_path).resolve()
    if not runtime_path.is_file():
        raise AdapterError(f"Frozen runtime profile is missing: {runtime_path}")
    actual_digest = sha256_file(runtime_path)
    if actual_digest != expected_digest:
        raise AdapterError("Frozen runtime profile hash mismatch")
    profile = load_object(runtime_path, "runtime profile")
    validate_runtime_profile(profile)
    return config, profile, runtime_path, actual_digest


def validate_runtime_profile(profile: dict[str, Any]) -> None:
    target = profile.get("target_surface")
    boundary = profile.get("execution_boundary")
    if not isinstance(target, dict) or not isinstance(boundary, dict):
        raise AdapterError("Runtime profile lacks target_surface or execution_boundary")
    required_text = ("cli_path", "cli_sha256", "cli_version", "model_alias", "reasoning_effort")
    if any(not isinstance(target.get(name), str) or not target[name] for name in required_text):
        raise AdapterError("Runtime profile has incomplete CLI or model controls")
    if not re.fullmatch(r"[a-f0-9]{64}", target["cli_sha256"]):
        raise AdapterError("Runtime profile cli_sha256 is invalid")
    common = set(target.get("common_disabled_features", []))
    no_tool = set(target.get("additional_no_tool_disabled_features", []))
    missing = sorted(set(COMMON_FEATURE_DISABLES) - common)
    missing_no_tool = sorted(set(NO_TOOL_FEATURE_DISABLES) - no_tool)
    if missing or missing_no_tool:
        raise AdapterError(f"Runtime profile omits frozen feature disables: {missing + missing_no_tool}")
    fixed_flags = set(target.get("fixed_cli_flags", []))
    required_flags = {
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--skip-git-repo-check",
        "--json",
        "--ask-for-approval=never",
    }
    if not required_flags.issubset(fixed_flags):
        raise AdapterError("Runtime profile omits required CLI isolation flags")
    if boundary.get("external_side_effects") != "Forbidden":
        raise AdapterError("Runtime profile must forbid external side effects")


def _read_registered_artifact(
    connection: sqlite3.Connection, instance: Path, digest: str
) -> bytes:
    row = connection.execute(
        "SELECT relative_path FROM artifacts WHERE sha256 = ?", (digest,)
    ).fetchone()
    if row is None:
        raise AdapterError(f"Artifact is not registered: {digest}")
    root = instance.resolve()
    path = (root / row["relative_path"]).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise AdapterError("Artifact path escapes the instance") from exc
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise AdapterError(f"Cannot read artifact {digest}: {type(exc).__name__}") from exc
    if sha256_bytes(content) != digest:
        raise AdapterError(f"Artifact hash mismatch: {digest}")
    return content


def load_frozen_epoch(
    instance: Path, epoch_id: str, approved_cell_ids: Sequence[str]
) -> FrozenEpoch:
    database = instance / "state.db"
    if not database.is_file():
        raise AdapterError(f"State database is missing: {database}")
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    try:
        epoch = connection.execute(
            "SELECT epoch_id, stage, plan_sha256, status FROM epochs WHERE epoch_id = ?",
            (epoch_id,),
        ).fetchone()
        if epoch is None:
            raise AdapterError(f"Unknown epoch: {epoch_id}")
        if epoch["status"] != "planned":
            raise AdapterError(f"Epoch must be planned, not {epoch['status']}")
        try:
            plan = json.loads(_read_registered_artifact(connection, instance, epoch["plan_sha256"]))
        except json.JSONDecodeError as exc:
            raise AdapterError("Frozen plan artifact is not valid JSON") from exc
        if not isinstance(plan, dict) or not isinstance(plan.get("rows"), list):
            raise AdapterError("Frozen plan must contain rows")
        if plan.get("epoch_id") != epoch_id or plan.get("stage") != epoch["stage"]:
            raise AdapterError("Frozen plan identity does not match the epoch")
        rows = plan["rows"]
        if plan.get("cell_count") != len(rows):
            raise AdapterError("Frozen plan cell_count does not match its rows")
        plan_by_id: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("cell_id"), str):
                raise AdapterError("Frozen plan contains an invalid cell row")
            cell_id = row["cell_id"]
            if cell_id in plan_by_id:
                raise AdapterError(f"Frozen plan contains duplicate cell_id: {cell_id}")
            packet_sha = row.get("packet_sha256")
            if not isinstance(packet_sha, str) or not re.fullmatch(r"[a-f0-9]{64}", packet_sha):
                raise AdapterError(f"Cell {cell_id} has an invalid packet hash")
            plan_by_id[cell_id] = row
        db_rows = connection.execute(
            "SELECT cell_id, packet_sha256, status FROM cells WHERE epoch_id = ?", (epoch_id,)
        ).fetchall()
        if len(db_rows) != len(rows):
            raise AdapterError("Database cell count does not match the frozen plan")
        for row in db_rows:
            planned = plan_by_id.get(row["cell_id"])
            if planned is None or planned["packet_sha256"] != row["packet_sha256"]:
                raise AdapterError("Database cells do not match the frozen plan")
            if row["status"] != "planned":
                raise AdapterError(f"Cell {row['cell_id']} is not planned")
        unknown = sorted(set(approved_cell_ids) - plan_by_id.keys())
        if unknown:
            raise AdapterError(f"Approval references unknown cells: {unknown}")
        selected = tuple(row for row in rows if row["cell_id"] in set(approved_cell_ids))
        if len(selected) != len(approved_cell_ids):
            raise AdapterError("Approved cell selection is inconsistent")
        for row in selected:
            _read_registered_artifact(connection, instance, row["packet_sha256"])
        return FrozenEpoch(
            epoch_id=epoch_id,
            stage=epoch["stage"],
            plan_sha256=epoch["plan_sha256"],
            plan=plan,
            selected_rows=selected,
        )
    except sqlite3.Error as exc:
        raise AdapterError(f"Cannot inspect state database: {type(exc).__name__}") from exc
    finally:
        connection.close()


def isolated_environment(codex_home: Path) -> dict[str, str]:
    return {
        "CODEX_HOME": str(codex_home),
        "HOME": str(codex_home),
        "PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TERM": "dumb",
        "NO_COLOR": "1",
        "TMPDIR": "/tmp",
    }


def _default_process_runner(args: Sequence[str], env: Mapping[str, str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            list(args),
            check=False,
            capture_output=True,
            text=True,
            env=dict(env),
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise AdapterError(f"Runtime readiness command failed: {type(exc).__name__}") from exc


def inspect_runtime(
    cli_path: Path,
    codex_home: Path,
    no_tool_cwd: Path,
    profile: dict[str, Any],
    *,
    process_runner: Callable[[Sequence[str], Mapping[str, str]], subprocess.CompletedProcess[str]] = _default_process_runner,
) -> dict[str, Any]:
    cli_path = cli_path.resolve()
    codex_home = codex_home.resolve()
    no_tool_cwd = no_tool_cwd.resolve()
    target = profile["target_surface"]
    if not cli_path.is_file() or not os.access(cli_path, os.X_OK):
        raise AdapterError(f"Codex CLI is not executable: {cli_path}")
    if str(cli_path) != str(Path(target["cli_path"]).resolve()):
        raise AdapterError("Codex CLI path does not match the frozen runtime profile")
    if sha256_file(cli_path) != target["cli_sha256"]:
        raise AdapterError("Codex CLI binary hash does not match the frozen runtime profile")
    if isinstance(target.get("cli_bytes"), int) and cli_path.stat().st_size != target["cli_bytes"]:
        raise AdapterError("Codex CLI byte size does not match the frozen runtime profile")
    if not codex_home.is_dir():
        raise AdapterError(f"CODEX_HOME is not a directory: {codex_home}")
    if codex_home == (Path.home() / ".codex").resolve():
        raise AdapterError("The user's normal ~/.codex is forbidden")
    if not (codex_home / "auth.json").is_file():
        raise AdapterError("Isolated CODEX_HOME must contain auth.json")
    forbidden = [name for name in FORBIDDEN_CODEX_HOME_ENTRIES if (codex_home / name).exists()]
    if forbidden:
        raise AdapterError(f"Isolated CODEX_HOME contains forbidden entries: {forbidden}")
    if not no_tool_cwd.is_dir() or any(no_tool_cwd.iterdir()):
        raise AdapterError("No-tool working directory must exist and be empty")
    writable_bits = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH
    if stat.S_IMODE(no_tool_cwd.stat().st_mode) & writable_bits:
        raise AdapterError("No-tool working directory must not have writable mode bits")

    environment = isolated_environment(codex_home)
    version = process_runner([str(cli_path), "--version"], environment)
    if version.returncode != 0 or not version.stdout.strip():
        raise AdapterError("Codex CLI version check failed")
    cli_version = version.stdout.strip().splitlines()[0][:200]
    if cli_version != target["cli_version"]:
        raise AdapterError("Codex CLI version does not match the frozen runtime profile")
    login = process_runner([str(cli_path), "login", "status"], environment)
    login_material = f"{login.stdout}\n{login.stderr}".casefold()
    if login.returncode != 0 or "chatgpt" not in login_material:
        raise AdapterError("Codex CLI is not authenticated with ChatGPT in isolated CODEX_HOME")
    features = process_runner([str(cli_path), "features", "list"], environment)
    if features.returncode != 0:
        raise AdapterError("Codex feature registry check failed")
    feature_names: set[str] = set()
    for line in features.stdout.splitlines():
        match = re.match(r"^(\S+)\s+.+\s+(?:true|false)$", line.strip())
        if match:
            feature_names.add(match.group(1))
    required = set(COMMON_FEATURE_DISABLES) | set(NO_TOOL_FEATURE_DISABLES)
    missing = sorted(required - feature_names)
    if missing:
        raise AdapterError(f"CLI feature registry is missing frozen controls: {missing}")
    return {
        "cli_path": str(cli_path),
        "cli_sha256": target["cli_sha256"],
        "cli_version": cli_version,
        "auth_mode": "chatgpt",
        "feature_registry_sha256": sha256_bytes("\n".join(sorted(feature_names)).encode("utf-8")),
        "no_tool_cwd": str(no_tool_cwd),
    }


def build_command_template(cli_path: Path, no_tool_cwd: Path, profile: dict[str, Any]) -> list[str]:
    target = profile["target_surface"]
    command = [
        str(cli_path.resolve()),
        "--ask-for-approval",
        "never",
        "exec",
        "--model",
        target["model_alias"],
        "--config",
        f'model_reasoning_effort="{target["reasoning_effort"]}"',
        "--config",
        "project_doc_max_bytes=0",
        "--strict-config",
        "--sandbox",
        "read-only",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--skip-git-repo-check",
        "--json",
        "--color",
        "never",
        "--cd",
        str(no_tool_cwd.resolve()),
    ]
    for feature in (*COMMON_FEATURE_DISABLES, *NO_TOOL_FEATURE_DISABLES):
        command.extend(("--disable", feature))
    command.append("-")
    return command


def preflight(
    *,
    instance: Path,
    epoch_id: str,
    cli_path: Path,
    codex_home: Path,
    approval_path: Path,
    config_path: Path = CONFIG_PATH,
    no_tool_cwd: Path = DEFAULT_NO_TOOL_CWD,
    now: datetime | None = None,
    process_runner: Callable[[Sequence[str], Mapping[str, str]], subprocess.CompletedProcess[str]] = _default_process_runner,
) -> dict[str, Any]:
    config_path = config_path.resolve()
    approval_path = approval_path.resolve()
    config, profile, runtime_path, runtime_sha = load_frozen_runtime(config_path)
    live = config.get("live_execution")
    if not isinstance(live, dict) or live.get("authorized") is not True:
        raise AdapterError("Study live execution is not authorized; the repository kill switch is closed")
    study_root = _study_root(config_path)
    try:
        approval_path.relative_to(study_root)
    except ValueError:
        pass
    else:
        raise AdapterError("Approval manifest must remain outside the research package")
    approval = load_object(approval_path, "run approval")

    database = instance / "state.db"
    if not database.is_file():
        raise AdapterError(f"State database is missing: {database}")
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        epoch = connection.execute(
            "SELECT stage, plan_sha256 FROM epochs WHERE epoch_id = ?", (epoch_id,)
        ).fetchone()
    except sqlite3.Error as exc:
        raise AdapterError(f"Cannot inspect state database: {type(exc).__name__}") from exc
    finally:
        connection.close()
    if epoch is None:
        raise AdapterError(f"Unknown epoch: {epoch_id}")
    approved_cells = validate_approval(
        approval,
        now=now or datetime.now(timezone.utc),
        expected_epoch_id=epoch_id,
        expected_stage=epoch["stage"],
        expected_plan_sha256=epoch["plan_sha256"],
        expected_runtime_sha256=runtime_sha,
    )
    frozen_epoch = load_frozen_epoch(instance.resolve(), epoch_id, approved_cells)
    runtime = inspect_runtime(
        cli_path,
        codex_home,
        no_tool_cwd,
        profile,
        process_runner=process_runner,
    )
    template = build_command_template(cli_path, no_tool_cwd, profile)
    selected_ids = [row["cell_id"] for row in frozen_epoch.selected_rows]
    report = {
        "schema_version": "1.0",
        "status": "ready-for-separately-reviewed-execution-adapter",
        "checked_at": (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "execution_performed": False,
        "model_invocations": 0,
        "approval": {
            "approval_id": approval["approval_id"],
            "approved_by": approval["approved_by"],
            "approval_sha256": sha256_file(approval_path),
            "expires_at": approval["expires_at"],
            "provider_processing_acknowledged": True,
        },
        "epoch": {
            "epoch_id": frozen_epoch.epoch_id,
            "stage": frozen_epoch.stage,
            "plan_sha256": frozen_epoch.plan_sha256,
            "approved_cell_count": len(selected_ids),
            "approved_cell_ids_sha256": sha256_bytes(canonical_json(selected_ids).encode("utf-8")),
        },
        "runtime_profile": {
            "path": str(runtime_path),
            "sha256": runtime_sha,
        },
        "runtime": runtime,
        "command_template_sha256": sha256_bytes(canonical_json(template).encode("utf-8")),
        "next_step": "No execution command exists in this adapter; add one only in a separately approved change.",
    }
    if APPROVAL_SCHEMA_PATH.is_file():
        report["approval_schema_sha256"] = sha256_file(APPROVAL_SCHEMA_PATH)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    command = subparsers.add_parser("preflight", help="Validate gates without invoking a model")
    command.add_argument("--instance", type=Path, required=True)
    command.add_argument("--epoch", required=True)
    command.add_argument("--cli-path", type=Path, required=True)
    command.add_argument("--codex-home", type=Path, required=True)
    command.add_argument("--approval", type=Path, required=True)
    command.add_argument("--config", type=Path, default=CONFIG_PATH)
    command.add_argument("--no-tool-cwd", type=Path, default=DEFAULT_NO_TOOL_CWD)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = preflight(
            instance=args.instance,
            epoch_id=args.epoch,
            cli_path=args.cli_path,
            codex_home=args.codex_home,
            approval_path=args.approval,
            config_path=args.config,
            no_tool_cwd=args.no_tool_cwd,
        )
    except AdapterError as exc:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "execution_performed": False,
                    "model_invocations": 0,
                    "error": str(exc),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
