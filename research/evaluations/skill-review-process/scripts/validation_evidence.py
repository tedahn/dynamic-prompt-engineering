#!/usr/bin/env python3
"""Create and verify self-reference-safe validation evidence for a repository tree."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


SCHEMA_VERSION = "1.0"
MANIFEST_NAME = "content-projection-manifest.json"
RESULT_NAME = "validation-result.json"
NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
ENV_NAME_PATTERN = re.compile(r"^[A-Z_][A-Z0-9_]*$")
FORBIDDEN_ENVIRONMENT_NAMES = {
    "BASH_ENV",
    "CDPATH",
    "ENV",
    "GIT_EXEC_PATH",
    "NODE_PATH",
    "PATH",
    "PYTHONHOME",
    "PYTHONPATH",
}
SECRET_ENVIRONMENT_FRAGMENTS = ("KEY", "PASSWORD", "SECRET", "TOKEN")
BASE_ENVIRONMENT = {
    "LANG": "C",
    "LC_ALL": "C",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONHASHSEED": "0",
    "TZ": "UTC",
}
if sys.platform == "darwin":
    BASE_ENVIRONMENT["__CF_USER_TEXT_ENCODING"] = f"0x{os.getuid():X}:0x0:0x0"
PROCESS_GROUP_GRACE_SECONDS = 0.25
PROCESS_GROUP_KILL_SECONDS = 1.0


class EvidenceError(RuntimeError):
    """Raised when an evidence request or artifact is invalid."""


def canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def parse_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise EvidenceError(f"{field} must be an RFC 3339 UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise EvidenceError(f"{field} is not a valid timestamp") from exc
    if parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise EvidenceError(f"{field} must be UTC")
    return parsed


def normalize_relative_path(value: str, field: str = "path") -> str:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        raise EvidenceError(f"{field} must be a non-empty repository-relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise EvidenceError(f"{field} must stay within the repository: {value!r}")
    if path.as_posix() != value:
        raise EvidenceError(f"{field} must be normalized POSIX syntax: {value!r}")
    return path.as_posix()


def path_within(root: Path, path: Path, field: str) -> Path:
    root = root.resolve()
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise EvidenceError(f"{field} must be inside the repository") from exc
    return resolved


def repository_input_path(root: Path, value: Path) -> Path:
    return value if value.is_absolute() else root / value


def repo_relative(root: Path, path: Path, field: str) -> str:
    relative = path_within(root, path, field).relative_to(root.resolve()).as_posix()
    return normalize_relative_path(relative, field)


def git_bytes(repo_root: Path, *args: str) -> bytes:
    process = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    if process.returncode != 0:
        message = process.stderr.decode("utf-8", errors="replace").strip()
        raise EvidenceError(f"git {' '.join(args)} failed: {message}")
    return process.stdout


def git_text(repo_root: Path, *args: str) -> str:
    return git_bytes(repo_root, *args).decode("utf-8", errors="strict").strip()


def ensure_repository(repo_root: Path) -> Path:
    root = repo_root.resolve()
    if not root.is_dir():
        raise EvidenceError(f"repository root is not a directory: {root}")
    top = Path(git_text(root, "rev-parse", "--show-toplevel")).resolve()
    if top != root:
        raise EvidenceError(f"--repo-root must be the Git top level: {top}")
    return root


def decode_git_path(value: bytes) -> str:
    try:
        decoded = value.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise EvidenceError("repository paths must be valid UTF-8") from exc
    return normalize_relative_path(decoded, "Git path")


def tracked_index(repo_root: Path) -> dict[str, tuple[str, str]]:
    records: dict[str, tuple[str, str]] = {}
    raw = git_bytes(repo_root, "ls-files", "--stage", "-z")
    for record in filter(None, raw.split(b"\0")):
        try:
            metadata, path_bytes = record.split(b"\t", 1)
            mode_bytes, oid_bytes, stage_bytes = metadata.split(b" ", 2)
        except ValueError as exc:
            raise EvidenceError("unexpected git ls-files --stage output") from exc
        if stage_bytes != b"0":
            raise EvidenceError("content projection cannot be created with unmerged index entries")
        path = decode_git_path(path_bytes)
        records[path] = (
            mode_bytes.decode("ascii", errors="strict"),
            oid_bytes.decode("ascii", errors="strict"),
        )
    return records


def untracked_paths(repo_root: Path) -> set[str]:
    raw = git_bytes(repo_root, "ls-files", "--others", "--exclude-standard", "-z")
    return {decode_git_path(record) for record in filter(None, raw.split(b"\0"))}


def worktree_entry(
    repo_root: Path,
    relative: str,
    index: tuple[str, str] | None,
) -> dict[str, Any]:
    path = repo_root / relative
    index_mode, index_oid = index if index else (None, None)
    if not os.path.lexists(path):
        if index is None:
            raise EvidenceError(f"untracked path disappeared during projection: {relative}")
        return {
            "path": relative,
            "kind": "absent_tracked",
            "mode": index_mode,
            "size_bytes": 0,
            "sha256": None,
            "index_oid": index_oid,
        }
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode):
        target = os.fsencode(os.readlink(path))
        return {
            "path": relative,
            "kind": "symlink",
            "mode": "120000",
            "size_bytes": len(target),
            "sha256": sha256_bytes(target),
        }
    if stat.S_ISREG(info.st_mode):
        mode = "100755" if info.st_mode & 0o111 else "100644"
        return {
            "path": relative,
            "kind": "file",
            "mode": mode,
            "size_bytes": info.st_size,
            "sha256": sha256_file(path),
        }
    if stat.S_ISDIR(info.st_mode) and index_mode == "160000":
        try:
            worktree_oid = git_text(path, "rev-parse", "HEAD")
        except EvidenceError:
            worktree_oid = None
        return {
            "path": relative,
            "kind": "gitlink",
            "mode": "160000",
            "size_bytes": 0,
            "sha256": worktree_oid,
            "index_oid": index_oid,
        }
    raise EvidenceError(f"unsupported projected file type: {relative}")


def build_projection(repo_root: Path, excluded_paths: list[str]) -> dict[str, Any]:
    excluded = sorted({normalize_relative_path(path, "excluded path") for path in excluded_paths})
    index = tracked_index(repo_root)
    candidates = set(index) | untracked_paths(repo_root)
    entries = [
        worktree_entry(repo_root, relative, index.get(relative))
        for relative in sorted(candidates)
        if relative not in excluded
    ]
    identity = {
        "algorithm": "sha256-canonical-json-v1",
        "excluded_paths": excluded,
        "entries": entries,
    }
    return {
        "algorithm": identity["algorithm"],
        "entry_count": len(entries),
        "sha256": sha256_bytes(canonical_bytes(identity)),
        "entries": entries,
    }


def validate_name(value: object, field: str) -> str:
    if not isinstance(value, str) or not NAME_PATTERN.fullmatch(value):
        raise EvidenceError(f"{field} must match {NAME_PATTERN.pattern}")
    return value


def validate_argv(value: object, field: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item or "\x00" in item for item in value)
    ):
        raise EvidenceError(f"{field} must be a non-empty array of non-empty strings")
    return list(value)


def resolve_cwd(repo_root: Path, value: object, field: str) -> tuple[str, Path]:
    if value in (None, "."):
        return ".", repo_root
    relative = normalize_relative_path(value, field) if isinstance(value, str) else None
    if relative is None:
        raise EvidenceError(f"{field} must be a repository-relative path")
    resolved = path_within(repo_root, repo_root / relative, field)
    if not resolved.is_dir():
        raise EvidenceError(f"{field} is not a directory: {relative}")
    return relative, resolved


def normalized_environment(extra: dict[str, str] | None) -> dict[str, str]:
    if extra is not None and not isinstance(extra, dict):
        raise EvidenceError("environment must be a JSON object")
    environment = dict(BASE_ENVIRONMENT)
    for name, value in (extra or {}).items():
        if not isinstance(name, str) or not ENV_NAME_PATTERN.fullmatch(name):
            raise EvidenceError(f"environment name is invalid: {name!r}")
        if name in FORBIDDEN_ENVIRONMENT_NAMES:
            raise EvidenceError(f"environment variable is forbidden for deterministic execution: {name}")
        if any(fragment in name for fragment in SECRET_ENVIRONMENT_FRAGMENTS):
            raise EvidenceError(f"secret-like environment variable must not be persisted: {name}")
        if not isinstance(value, str) or "\x00" in value:
            raise EvidenceError(f"environment value for {name} must be a NUL-free string")
        environment[name] = value
    return dict(sorted(environment.items()))


def absolute_file_identity(
    value: str,
    field: str,
    *,
    executable: bool = False,
) -> dict[str, Any]:
    requested = Path(value)
    if not requested.is_absolute():
        raise EvidenceError(f"{field} must be an absolute path; PATH resolution is forbidden")
    if not requested.exists() or not requested.is_file():
        raise EvidenceError(f"{field} is not a regular file: {requested}")
    resolved = requested.resolve()
    if not resolved.is_file():
        raise EvidenceError(f"{field} does not resolve to a regular file: {requested}")
    info = resolved.stat()
    if executable and not os.access(resolved, os.X_OK):
        raise EvidenceError(f"{field} is not executable: {requested}")
    if executable:
        with resolved.open("rb") as handle:
            if handle.read(2) == b"#!":
                raise EvidenceError(
                    f"{field} is a script wrapper; invoke its absolute interpreter and declare the script as a dependency"
                )
    return {
        "requested_path": requested.as_posix(),
        "resolved_path": resolved.as_posix(),
        "size_bytes": info.st_size,
        "mode": f"{stat.S_IMODE(info.st_mode):04o}",
        "sha256": sha256_file(resolved),
    }


def external_tree_identity(value: str, field: str) -> dict[str, Any]:
    requested = Path(value)
    if not requested.is_absolute():
        raise EvidenceError(f"{field} must be an absolute path")
    resolved = requested.resolve()
    if not resolved.is_dir():
        raise EvidenceError(f"{field} is not a directory: {requested}")
    entries: list[dict[str, Any]] = []
    for directory, directory_names, file_names in os.walk(resolved, followlinks=False):
        directory_names.sort()
        file_names.sort()
        base = Path(directory)
        for name in file_names:
            path = base / name
            relative = path.relative_to(resolved).as_posix()
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                target = os.fsencode(os.readlink(path))
                entries.append(
                    {
                        "path": relative,
                        "kind": "symlink",
                        "mode": "120000",
                        "size_bytes": len(target),
                        "sha256": sha256_bytes(target),
                    }
                )
            elif stat.S_ISREG(info.st_mode):
                entries.append(
                    {
                        "path": relative,
                        "kind": "file",
                        "mode": "100755" if info.st_mode & 0o111 else "100644",
                        "size_bytes": info.st_size,
                        "sha256": sha256_file(path),
                    }
                )
            else:
                raise EvidenceError(f"{field} contains an unsupported file type: {path}")
    if not entries:
        raise EvidenceError(f"{field} must contain at least one file")
    return {
        "requested_path": requested.as_posix(),
        "resolved_path": resolved.as_posix(),
        "entry_count": len(entries),
        "sha256": sha256_bytes(canonical_bytes({"entries": entries})),
        "entries": entries,
    }


def normalize_dependency(value: object, command_name: str, index: int) -> dict[str, str]:
    if not isinstance(value, dict):
        raise EvidenceError(f"command {command_name} dependency {index} must be an object")
    name = validate_name(value.get("name"), f"command {command_name} dependency {index} name")
    kind = value.get("kind")
    if kind not in ("projected_file", "projected_tree", "external_file", "external_tree"):
        raise EvidenceError(f"command {command_name} dependency {name} kind is invalid")
    path = value.get("path")
    if not isinstance(path, str) or not path:
        raise EvidenceError(f"command {command_name} dependency {name} path is invalid")
    if kind.startswith("projected_"):
        path = normalize_relative_path(path, f"command {command_name} dependency {name} path")
    elif not Path(path).is_absolute():
        raise EvidenceError(f"command {command_name} dependency {name} must use an absolute path")
    return {"name": name, "kind": kind, "path": path}


def bind_dependency(
    repo_root: Path,
    projection: dict[str, Any],
    dependency: dict[str, str],
) -> dict[str, Any]:
    kind = dependency["kind"]
    path = dependency["path"]
    bound: dict[str, Any] = dict(dependency)
    if kind.startswith("projected_"):
        resolved = (repo_root / path).resolve()
        try:
            resolved.relative_to(repo_root)
        except ValueError as exc:
            raise EvidenceError(f"projected dependency escapes the repository: {path}") from exc
        entries = projection["entries"]
        if kind == "projected_file":
            matches = [entry for entry in entries if entry["path"] == path]
            if len(matches) != 1 or matches[0]["kind"] not in ("file", "symlink"):
                raise EvidenceError(f"projected file dependency is absent from the projection: {path}")
            identity: dict[str, Any] = {"projection_entry": matches[0]}
        else:
            prefix = "" if path == "." else path.rstrip("/") + "/"
            matches = [entry for entry in entries if entry["path"].startswith(prefix)]
            if not matches:
                raise EvidenceError(f"projected tree dependency is absent from the projection: {path}")
            identity = {
                "entry_count": len(matches),
                "sha256": sha256_bytes(canonical_bytes({"entries": matches})),
            }
        bound["identity"] = identity
        return bound
    resolved = Path(path).resolve()
    try:
        resolved.relative_to(repo_root)
    except ValueError:
        pass
    else:
        raise EvidenceError(f"external dependency must be outside the repository: {path}")
    bound["identity"] = (
        absolute_file_identity(path, f"external dependency {dependency['name']}")
        if kind == "external_file"
        else external_tree_identity(path, f"external dependency {dependency['name']}")
    )
    return bound


def bind_dependencies(
    repo_root: Path,
    projection: dict[str, Any],
    dependencies: list[dict[str, str]],
) -> list[dict[str, Any]]:
    return [bind_dependency(repo_root, projection, dependency) for dependency in dependencies]


def declared_dependency_paths(repo_root: Path, dependencies: list[dict[str, str]]) -> set[Path]:
    paths: set[Path] = set()
    for dependency in dependencies:
        raw = dependency["path"]
        paths.add((repo_root / raw).resolve() if dependency["kind"].startswith("projected_") else Path(raw).resolve())
    return paths


def reject_undeclared_path_arguments(
    repo_root: Path,
    spec: dict[str, Any],
) -> None:
    _, cwd = resolve_cwd(repo_root, spec["cwd"], f"command {spec['name']} cwd")
    declared = declared_dependency_paths(repo_root, spec["dependencies"])
    for argument in spec["argv"][1:]:
        candidate = Path(argument)
        candidate = candidate if candidate.is_absolute() else cwd / candidate
        if os.path.lexists(candidate) and candidate.resolve() not in declared:
            raise EvidenceError(
                f"command {spec['name']} path argument is an undeclared mutable dependency: {argument}"
            )


def validate_specs(
    repo_root: Path,
    commands: list[dict[str, Any]],
    tool_versions: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(commands, list) or not commands:
        raise EvidenceError("at least one validation command is required")
    if not isinstance(tool_versions, list) or not tool_versions:
        raise EvidenceError("at least one tool-version command is required")
    normalized_tools: list[dict[str, Any]] = []
    tool_names: set[str] = set()
    for index, raw in enumerate(tool_versions, 1):
        if not isinstance(raw, dict):
            raise EvidenceError(f"tool version {index} must be an object")
        name = validate_name(raw.get("name"), f"tool version {index} name")
        if name in tool_names:
            raise EvidenceError(f"duplicate tool name: {name}")
        tool_names.add(name)
        cwd_text, _ = resolve_cwd(repo_root, raw.get("cwd", "."), f"tool {name} cwd")
        argv = validate_argv(raw.get("argv"), f"tool {name} argv")
        normalized_tools.append(
            {
                "name": name,
                "argv": argv,
                "cwd": cwd_text,
                "executable_identity": absolute_file_identity(
                    argv[0], f"tool {name} executable", executable=True
                ),
            }
        )
    tools_by_name = {tool["name"]: tool for tool in normalized_tools}
    normalized_commands: list[dict[str, Any]] = []
    command_names: set[str] = set()
    for index, raw in enumerate(commands, 1):
        if not isinstance(raw, dict):
            raise EvidenceError(f"command {index} must be an object")
        name = validate_name(raw.get("name"), f"command {index} name")
        if name in command_names:
            raise EvidenceError(f"duplicate command name: {name}")
        command_names.add(name)
        cwd_text, _ = resolve_cwd(repo_root, raw.get("cwd", "."), f"command {name} cwd")
        dependencies = raw.get("tools")
        if (
            not isinstance(dependencies, list)
            or not dependencies
            or any(not isinstance(item, str) for item in dependencies)
        ):
            raise EvidenceError(f"command {name} tools must name at least one recorded tool")
        unknown = sorted(set(dependencies) - tool_names)
        if unknown:
            raise EvidenceError(f"command {name} references unknown tool: {', '.join(unknown)}")
        executable_tool = raw.get("executable_tool")
        if not isinstance(executable_tool, str) or executable_tool not in tool_names:
            raise EvidenceError(f"command {name} executable_tool must name a recorded tool")
        if executable_tool not in dependencies:
            raise EvidenceError(f"command {name} tools must include executable_tool {executable_tool}")
        raw_dependencies = raw.get("dependencies")
        if not isinstance(raw_dependencies, list):
            raise EvidenceError(f"command {name} dependencies must be an explicit array")
        normalized_dependencies = [
            normalize_dependency(value, name, dependency_index)
            for dependency_index, value in enumerate(raw_dependencies, 1)
        ]
        dependency_names = [dependency["name"] for dependency in normalized_dependencies]
        if len(dependency_names) != len(set(dependency_names)):
            raise EvidenceError(f"command {name} dependency names must be unique")
        timeout = raw.get("timeout_seconds", 600)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 86400:
            raise EvidenceError(f"command {name} timeout_seconds must be in (0, 86400]")
        argv = validate_argv(raw.get("argv"), f"command {name} argv")
        executable_identity = absolute_file_identity(
            argv[0], f"command {name} executable", executable=True
        )
        tool_identity = tools_by_name[executable_tool]["executable_identity"]
        if executable_identity != tool_identity:
            raise EvidenceError(
                f"command {name} executable does not match executable_tool {executable_tool}"
            )
        normalized = {
            "name": name,
            "argv": argv,
            "cwd": cwd_text,
            "tools": list(dict.fromkeys(dependencies)),
            "executable_tool": executable_tool,
            "executable_identity": executable_identity,
            "dependencies": normalized_dependencies,
            "timeout_seconds": timeout,
        }
        reject_undeclared_path_arguments(repo_root, normalized)
        normalized_commands.append(normalized)
    return normalized_commands, normalized_tools


def artifact_descriptor(repo_root: Path, path: Path, kind: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "path": repo_relative(repo_root, path, "artifact path"),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def process_group_alive(process_group_id: int) -> bool:
    try:
        os.killpg(process_group_id, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def wait_for_empty_process_group(process_group_id: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while process_group_alive(process_group_id) and time.monotonic() < deadline:
        time.sleep(0.01)
    return not process_group_alive(process_group_id)


def cleanup_process_group(process: subprocess.Popen[bytes]) -> bool:
    process_group_id = process.pid
    if process_group_alive(process_group_id):
        try:
            os.killpg(process_group_id, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=PROCESS_GROUP_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        pass
    if wait_for_empty_process_group(process_group_id, PROCESS_GROUP_GRACE_SECONDS):
        return True
    try:
        os.killpg(process_group_id, signal.SIGKILL)
    except ProcessLookupError:
        pass
    if process.poll() is None:
        try:
            process.wait(timeout=PROCESS_GROUP_KILL_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=PROCESS_GROUP_KILL_SECONDS)
    return wait_for_empty_process_group(process_group_id, PROCESS_GROUP_KILL_SECONDS)


def execute_spec(
    repo_root: Path,
    spec: dict[str, Any],
    timeout: float,
    stdout_path: Path,
    stderr_path: Path,
    environment: dict[str, str],
) -> dict[str, Any]:
    if os.name != "posix":
        raise EvidenceError("validation evidence execution requires POSIX process-group isolation")
    cwd_text, cwd = resolve_cwd(repo_root, spec["cwd"], f"{spec['name']} cwd")
    started_at = utc_now()
    monotonic_start = time.monotonic_ns()
    timed_out = False
    launch_error: str | None = None
    exit_code: int | None = None
    surviving_descendants = False
    cleanup_attempted = False
    process_group_empty = True
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stderr_path.parent.mkdir(parents=True, exist_ok=True)
    with stdout_path.open("wb") as stdout_handle, stderr_path.open("wb") as stderr_handle:
        try:
            process = subprocess.Popen(
                spec["argv"],
                cwd=cwd,
                env=environment,
                stdout=stdout_handle,
                stderr=stderr_handle,
                start_new_session=True,
            )
            try:
                exit_code = process.wait(timeout=timeout)
                surviving_descendants = process_group_alive(process.pid)
                if surviving_descendants:
                    cleanup_attempted = True
                    process_group_empty = cleanup_process_group(process)
            except subprocess.TimeoutExpired:
                timed_out = True
                cleanup_attempted = True
                process_group_empty = cleanup_process_group(process)
                exit_code = process.returncode
        except OSError as exc:
            launch_error = f"{type(exc).__name__}: {exc}"
            stderr_handle.write((launch_error + "\n").encode("utf-8", errors="replace"))
    completed_at = utc_now()
    duration_ms = max(0, (time.monotonic_ns() - monotonic_start) // 1_000_000)
    if launch_error:
        status = "launch_error"
    elif not process_group_empty:
        status = "cleanup_failed"
    elif timed_out:
        status = "timed_out"
    elif surviving_descendants:
        status = "descendants_terminated"
    else:
        status = "completed"
    record: dict[str, Any] = {
        "name": spec["name"],
        "argv": spec["argv"],
        "cwd": cwd_text,
        "started_at": started_at,
        "completed_at": completed_at,
        "duration_ms": duration_ms,
        "execution_status": status,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "process_group_id": process.pid if not launch_error else None,
        "surviving_descendants_after_leader_exit": surviving_descendants,
        "cleanup_attempted": cleanup_attempted,
        "process_group_empty_after_cleanup": process_group_empty,
    }
    if launch_error:
        record["launch_error"] = launch_error
    return record


def planned_artifact_paths(
    repo_root: Path,
    output_dir: Path,
    commands: list[dict[str, Any]],
    tools: list[dict[str, Any]],
) -> dict[str, Any]:
    def paths(group: str, items: list[dict[str, Any]]) -> list[tuple[Path, Path]]:
        return [
            (
                output_dir / "artifacts" / group / f"{index:03d}-{item['name']}.stdout.txt",
                output_dir / "artifacts" / group / f"{index:03d}-{item['name']}.stderr.txt",
            )
            for index, item in enumerate(items, 1)
        ]

    manifest = output_dir / MANIFEST_NAME
    result = output_dir / RESULT_NAME
    command_paths = paths("commands", commands)
    tool_paths = paths("tools", tools)
    generated = [manifest, result]
    generated.extend(path for pair in command_paths + tool_paths for path in pair)
    excluded = [repo_relative(repo_root, path, "generated evidence path") for path in generated]
    return {
        "manifest": manifest,
        "result": result,
        "commands": command_paths,
        "tools": tool_paths,
        "excluded": sorted(excluded),
    }


def run_validation(
    repo_root: Path,
    output_dir: Path,
    commands: list[dict[str, Any]],
    tool_versions: list[dict[str, Any]],
    environment: dict[str, str] | None = None,
) -> dict[str, Any]:
    root = ensure_repository(Path(repo_root))
    requested_output = repository_input_path(root, Path(output_dir))
    if requested_output.is_symlink():
        raise EvidenceError("output directory must not be a symlink")
    output = path_within(root, requested_output, "output directory")
    if output.exists() and any(output.iterdir()):
        raise EvidenceError(f"output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    execution_environment = normalized_environment(environment)
    normalized_commands, normalized_tools = validate_specs(root, commands, tool_versions)
    paths = planned_artifact_paths(root, output, normalized_commands, normalized_tools)
    run_started_at = utc_now()
    projection = build_projection(root, paths["excluded"])
    if build_projection(root, paths["excluded"]) != projection:
        raise EvidenceError("repository content projection was not stable before validation")
    try:
        head_sha = git_text(root, "rev-parse", "HEAD")
    except EvidenceError:
        head_sha = None
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "kind": "content_projection_manifest",
        "created_at": run_started_at,
        "repository": {
            "root": ".",
            "discovery": "git_tracked_plus_untracked_nonignored_worktree",
        },
        "git": {"head_sha_at_validation_start": head_sha},
        "exclusions": [
            {"path": path, "reason": "generated_validation_evidence"}
            for path in paths["excluded"]
        ],
        "projection": projection,
    }
    write_json(paths["manifest"], manifest)
    artifacts = [artifact_descriptor(root, paths["manifest"], "content_projection_manifest")]
    for spec in normalized_commands:
        spec["dependencies"] = bind_dependencies(root, projection, spec["dependencies"])

    tool_records: list[dict[str, Any]] = []
    for spec, (stdout_path, stderr_path) in zip(normalized_tools, paths["tools"], strict=True):
        before_projection = build_projection(root, paths["excluded"])
        executable_before = absolute_file_identity(
            spec["argv"][0], f"tool {spec['name']} executable", executable=True
        )
        record = execute_spec(
            root, spec, 60, stdout_path, stderr_path, execution_environment
        )
        executable_after = absolute_file_identity(
            spec["argv"][0], f"tool {spec['name']} executable", executable=True
        )
        stdout_artifact = artifact_descriptor(root, stdout_path, "tool_version_stdout")
        stderr_artifact = artifact_descriptor(root, stderr_path, "tool_version_stderr")
        record["stdout_artifact"] = stdout_artifact
        record["stderr_artifact"] = stderr_artifact
        record["timeout_seconds"] = 60
        text = (stdout_path.read_bytes() + b"\n" + stderr_path.read_bytes()).decode(
            "utf-8", errors="replace"
        )
        record["reported_version"] = next((line.strip() for line in text.splitlines() if line.strip()), "")
        record["executable_identity"] = spec["executable_identity"]
        record["executable_identity_matches_bound"] = (
            executable_before == spec["executable_identity"] == executable_after
        )
        record["dependencies"] = []
        record["dependency_identities_match_bound"] = True
        record["environment_sha256"] = sha256_bytes(canonical_bytes(execution_environment))
        after_projection = build_projection(root, paths["excluded"])
        record["projection_sha256_before"] = before_projection["sha256"]
        record["projection_sha256_after"] = after_projection["sha256"]
        record["projection_matches_tested"] = before_projection == projection == after_projection
        tool_records.append(record)
        artifacts.extend((stdout_artifact, stderr_artifact))

    command_records: list[dict[str, Any]] = []
    for spec, (stdout_path, stderr_path) in zip(normalized_commands, paths["commands"], strict=True):
        before_projection = build_projection(root, paths["excluded"])
        declarations = [
            {key: dependency[key] for key in ("name", "kind", "path")}
            for dependency in spec["dependencies"]
        ]
        dependencies_before = bind_dependencies(root, before_projection, declarations)
        executable_before = absolute_file_identity(
            spec["argv"][0], f"command {spec['name']} executable", executable=True
        )
        record = execute_spec(
            root,
            spec,
            float(spec["timeout_seconds"]),
            stdout_path,
            stderr_path,
            execution_environment,
        )
        record["tools"] = spec["tools"]
        record["executable_tool"] = spec["executable_tool"]
        record["timeout_seconds"] = spec["timeout_seconds"]
        stdout_artifact = artifact_descriptor(root, stdout_path, "command_stdout")
        stderr_artifact = artifact_descriptor(root, stderr_path, "command_stderr")
        record["stdout_artifact"] = stdout_artifact
        record["stderr_artifact"] = stderr_artifact
        after_projection = build_projection(root, paths["excluded"])
        dependencies_after = bind_dependencies(root, after_projection, declarations)
        executable_after = absolute_file_identity(
            spec["argv"][0], f"command {spec['name']} executable", executable=True
        )
        record["executable_identity"] = spec["executable_identity"]
        record["executable_identity_matches_bound"] = (
            executable_before == spec["executable_identity"] == executable_after
        )
        record["dependencies"] = spec["dependencies"]
        record["dependency_identities_match_bound"] = (
            dependencies_before == spec["dependencies"] == dependencies_after
        )
        record["environment_sha256"] = sha256_bytes(canonical_bytes(execution_environment))
        record["projection_sha256_before"] = before_projection["sha256"]
        record["projection_sha256_after"] = after_projection["sha256"]
        record["projection_matches_tested"] = before_projection == projection == after_projection
        command_records.append(record)
        artifacts.extend((stdout_artifact, stderr_artifact))

    final_projection = build_projection(root, paths["excluded"])
    projection_unchanged = final_projection == projection
    executions_passed = all(
        record["execution_status"] == "completed"
        and record["exit_code"] == 0
        and record["projection_matches_tested"]
        and record["executable_identity_matches_bound"]
        and record.get("dependency_identities_match_bound", True)
        and record["process_group_empty_after_cleanup"]
        for record in tool_records + command_records
    )
    run_completed_at = utc_now()
    result = {
        "schema_version": SCHEMA_VERSION,
        "kind": "validation_result",
        "status": "passed" if executions_passed and projection_unchanged else "failed",
        "started_at": run_started_at,
        "completed_at": run_completed_at,
        "tested_projection_sha256": projection["sha256"],
        "projection_unchanged_after_validation": projection_unchanged,
        "content_projection_manifest": artifact_descriptor(
            root, paths["manifest"], "content_projection_manifest"
        ),
        "tool_versions": tool_records,
        "commands": command_records,
        "artifact_manifest": sorted(artifacts, key=lambda item: item["path"]),
        "recorder": {
            "git_version": git_text(root, "--version"),
            "python_version": sys.version,
            "platform": sys.platform,
            "script_sha256": sha256_file(Path(__file__)),
        },
        "environment": {
            "policy": "explicit_no_inheritance",
            "values": execution_environment,
            "sha256": sha256_bytes(canonical_bytes(execution_environment)),
        },
        "self_reference_policy": {
            "result_path": repo_relative(root, paths["result"], "validation result path"),
            "excluded_generated_paths": paths["excluded"],
            "binding": (
                "The content projection excludes only the listed generated evidence files. "
                "This result hashes the projection manifest and stream artifacts but not itself. "
                "A frozen review packet must hash both this result and the projection manifest."
            ),
        },
        "limitations": [],
    }
    write_json(paths["result"], result)
    return result


def read_json(path: Path, field: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"cannot read {field}: {exc}") from exc
    if not isinstance(value, dict):
        raise EvidenceError(f"{field} must contain a JSON object")
    return value


def descriptor_errors(repo_root: Path, descriptor: object, label: str) -> list[str]:
    errors: list[str] = []
    if not isinstance(descriptor, dict):
        return [f"{label} artifact descriptor must be an object"]
    if not isinstance(descriptor.get("kind"), str) or not descriptor["kind"]:
        errors.append(f"{label} artifact kind is invalid")
    try:
        relative = normalize_relative_path(descriptor.get("path"), f"{label} artifact path")
        path = path_within(repo_root, repo_root / relative, f"{label} artifact path")
    except EvidenceError as exc:
        return [str(exc)]
    if not path.is_file() or path.is_symlink():
        return [f"{label} artifact is missing or not a regular file: {relative}"]
    expected_hash = descriptor.get("sha256")
    expected_size = descriptor.get("size_bytes")
    if not isinstance(expected_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        errors.append(f"{label} artifact SHA-256 is invalid: {relative}")
    elif sha256_file(path) != expected_hash:
        errors.append(f"{label} artifact SHA-256 mismatch: {relative}")
    if not isinstance(expected_size, int) or expected_size < 0:
        errors.append(f"{label} artifact size is invalid: {relative}")
    elif path.stat().st_size != expected_size:
        errors.append(f"{label} artifact size mismatch: {relative}")
    return errors


def execution_errors(rows: object, label: str) -> tuple[list[str], set[str], list[dict[str, Any]]]:
    errors: list[str] = []
    artifacts: set[str] = set()
    valid_rows: list[dict[str, Any]] = []
    if not isinstance(rows, list) or not rows:
        return [f"{label} must be a non-empty array"], artifacts, valid_rows
    names: set[str] = set()
    for index, row in enumerate(rows, 1):
        prefix = f"{label}[{index}]"
        if not isinstance(row, dict):
            errors.append(f"{prefix} must be an object")
            continue
        valid_rows.append(row)
        try:
            name = validate_name(row.get("name"), f"{prefix}.name")
            if name in names:
                errors.append(f"{prefix}.name is duplicated: {name}")
            names.add(name)
            validate_argv(row.get("argv"), f"{prefix}.argv")
            normalize_relative_path(row["cwd"], f"{prefix}.cwd") if row.get("cwd") != "." else None
            started = parse_timestamp(row.get("started_at"), f"{prefix}.started_at")
            completed = parse_timestamp(row.get("completed_at"), f"{prefix}.completed_at")
            if completed < started:
                errors.append(f"{prefix} completed before it started")
        except (EvidenceError, KeyError) as exc:
            errors.append(str(exc))
        if row.get("execution_status") not in (
            "completed",
            "timed_out",
            "launch_error",
            "descendants_terminated",
            "cleanup_failed",
        ):
            errors.append(f"{prefix}.execution_status is invalid")
        if not isinstance(row.get("duration_ms"), int) or row["duration_ms"] < 0:
            errors.append(f"{prefix}.duration_ms is invalid")
        timeout = row.get("timeout_seconds")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 86400:
            errors.append(f"{prefix}.timeout_seconds is invalid")
        exit_code = row.get("exit_code")
        if exit_code is not None and (isinstance(exit_code, bool) or not isinstance(exit_code, int)):
            errors.append(f"{prefix}.exit_code is invalid")
        if row.get("timed_out") is not (row.get("execution_status") == "timed_out"):
            errors.append(f"{prefix}.timed_out is inconsistent with execution_status")
        if row.get("execution_status") == "completed" and exit_code is None:
            errors.append(f"{prefix}.exit_code is required for a completed execution")
        for boolean_field in (
            "surviving_descendants_after_leader_exit",
            "cleanup_attempted",
            "process_group_empty_after_cleanup",
            "executable_identity_matches_bound",
            "dependency_identities_match_bound",
        ):
            if not isinstance(row.get(boolean_field), bool):
                errors.append(f"{prefix}.{boolean_field} must be boolean")
        if row.get("execution_status") != "launch_error":
            if isinstance(row.get("process_group_id"), bool) or not isinstance(
                row.get("process_group_id"), int
            ):
                errors.append(f"{prefix}.process_group_id is invalid")
        if row.get("execution_status") == "completed" and (
            row.get("surviving_descendants_after_leader_exit") is not False
            or row.get("process_group_empty_after_cleanup") is not True
        ):
            errors.append(f"{prefix} completed despite a non-empty process group")
        if row.get("execution_status") == "descendants_terminated" and (
            row.get("surviving_descendants_after_leader_exit") is not True
            or row.get("cleanup_attempted") is not True
            or row.get("process_group_empty_after_cleanup") is not True
        ):
            errors.append(f"{prefix} descendant-cleanup status is inconsistent")
        if row.get("execution_status") == "cleanup_failed" and row.get(
            "process_group_empty_after_cleanup"
        ) is not False:
            errors.append(f"{prefix} cleanup_failed status is inconsistent")
        for projection_field in ("projection_sha256_before", "projection_sha256_after"):
            if not isinstance(row.get(projection_field), str) or not re.fullmatch(
                r"[0-9a-f]{64}", row[projection_field]
            ):
                errors.append(f"{prefix}.{projection_field} is invalid")
        if not isinstance(row.get("projection_matches_tested"), bool):
            errors.append(f"{prefix}.projection_matches_tested must be boolean")
        for stream in ("stdout_artifact", "stderr_artifact"):
            descriptor = row.get(stream)
            if isinstance(descriptor, dict) and isinstance(descriptor.get("path"), str):
                artifacts.add(descriptor["path"])
    return errors, artifacts, valid_rows


def verify_evidence(repo_root: Path, manifest_path: Path, result_path: Path) -> dict[str, Any]:
    errors: list[str] = []
    try:
        root = ensure_repository(Path(repo_root))
        manifest_file = path_within(
            root, repository_input_path(root, Path(manifest_path)), "manifest path"
        )
        result_file = path_within(
            root, repository_input_path(root, Path(result_path)), "result path"
        )
        manifest = read_json(manifest_file, "content projection manifest")
        result = read_json(result_file, "validation result")
    except EvidenceError as exc:
        return {"ok": False, "recorded_status": None, "errors": [str(exc)]}

    expected_manifest_file = result_file.parent / MANIFEST_NAME
    expected_result_file = result_file.parent / RESULT_NAME
    if manifest_file != expected_manifest_file:
        errors.append(f"manifest must be named {MANIFEST_NAME} beside the validation result")
    if result_file != expected_result_file:
        errors.append(f"validation result must be named {RESULT_NAME}")

    if manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("kind") != "content_projection_manifest":
        errors.append("content projection manifest schema_version or kind is invalid")
    if result.get("schema_version") != SCHEMA_VERSION or result.get("kind") != "validation_result":
        errors.append("validation result schema_version or kind is invalid")
    try:
        parse_timestamp(manifest.get("created_at"), "manifest.created_at")
    except EvidenceError as exc:
        errors.append(str(exc))
    try:
        start = parse_timestamp(result.get("started_at"), "result.started_at")
        end = parse_timestamp(result.get("completed_at"), "result.completed_at")
        if end < start:
            errors.append("validation result completed before it started")
    except EvidenceError as exc:
        errors.append(str(exc))

    manifest_descriptor = result.get("content_projection_manifest")
    errors.extend(descriptor_errors(root, manifest_descriptor, "content projection manifest"))
    if isinstance(manifest_descriptor, dict):
        try:
            expected_manifest_path = normalize_relative_path(
                manifest_descriptor.get("path"), "content projection manifest path"
            )
            actual_manifest_path = repo_relative(root, manifest_file, "manifest path")
            if expected_manifest_path != actual_manifest_path:
                errors.append("content projection manifest path does not match the verified file")
            if manifest_descriptor.get("kind") != "content_projection_manifest":
                errors.append("content projection manifest artifact kind is invalid")
        except EvidenceError as exc:
            errors.append(str(exc))

    exclusions = manifest.get("exclusions")
    excluded_paths: list[str] = []
    if not isinstance(exclusions, list) or not exclusions:
        errors.append("manifest exclusions must be a non-empty array")
    else:
        for index, exclusion in enumerate(exclusions, 1):
            if not isinstance(exclusion, dict) or exclusion.get("reason") != "generated_validation_evidence":
                errors.append(f"manifest exclusion {index} is invalid")
                continue
            try:
                excluded_paths.append(normalize_relative_path(exclusion.get("path"), "excluded path"))
            except EvidenceError as exc:
                errors.append(str(exc))
    if len(excluded_paths) != len(set(excluded_paths)):
        errors.append("manifest exclusions contain duplicate paths")

    projection = manifest.get("projection")
    if not isinstance(projection, dict):
        errors.append("manifest projection must be an object")
    else:
        try:
            current_projection = build_projection(root, excluded_paths)
            if current_projection != projection:
                errors.append("current repository content projection does not match the tested projection")
            if result.get("tested_projection_sha256") != projection.get("sha256"):
                errors.append("validation result tested projection SHA-256 does not match the manifest")
        except EvidenceError as exc:
            errors.append(str(exc))

    tool_errors, tool_artifacts, tool_rows = execution_errors(result.get("tool_versions"), "tool_versions")
    command_errors, command_artifacts, command_rows = execution_errors(result.get("commands"), "commands")
    errors.extend(tool_errors)
    errors.extend(command_errors)
    tested_projection_sha256 = result.get("tested_projection_sha256")
    for label, rows in (("tool_versions", tool_rows), ("commands", command_rows)):
        for index, row in enumerate(rows, 1):
            derived_match = (
                isinstance(tested_projection_sha256, str)
                and row.get("projection_sha256_before") == tested_projection_sha256
                and row.get("projection_sha256_after") == tested_projection_sha256
            )
            if row.get("projection_matches_tested") is not derived_match:
                errors.append(
                    f"{label}[{index}].projection_matches_tested is inconsistent with recorded hashes"
                )
    tool_names = {row.get("name") for row in tool_rows if isinstance(row.get("name"), str)}
    for label, rows in (("tool_versions", tool_rows), ("commands", command_rows)):
        for index, row in enumerate(rows, 1):
            identity = row.get("executable_identity")
            if not isinstance(identity, dict):
                errors.append(f"{label}[{index}].executable_identity must be an object")
            else:
                try:
                    current = absolute_file_identity(
                        identity.get("requested_path"),
                        f"{label}[{index}] executable",
                        executable=True,
                    )
                    if current != identity:
                        errors.append(f"{label}[{index}] executable identity no longer matches")
                except EvidenceError as exc:
                    errors.append(str(exc))
            dependencies = row.get("dependencies", [])
            if not isinstance(dependencies, list):
                errors.append(f"{label}[{index}].dependencies must be an array")
                continue
            for dependency_index, dependency in enumerate(dependencies, 1):
                if not isinstance(dependency, dict) or not isinstance(dependency.get("identity"), dict):
                    errors.append(
                        f"{label}[{index}].dependencies[{dependency_index}] identity is invalid"
                    )
                    continue
                try:
                    normalized = normalize_dependency(
                        dependency,
                        str(row.get("name", label)),
                        dependency_index,
                    )
                    current = bind_dependency(root, projection, normalized)
                    if current != dependency:
                        errors.append(
                            f"{label}[{index}].dependencies[{dependency_index}] dependency identity no longer matches"
                        )
                except EvidenceError as exc:
                    errors.append(str(exc))
    for index, row in enumerate(tool_rows, 1):
        if isinstance(row.get("name"), str):
            for stream in ("stdout", "stderr"):
                descriptor = row.get(f"{stream}_artifact")
                expected_path = repo_relative(
                    root,
                    result_file.parent
                    / "artifacts"
                    / "tools"
                    / f"{index:03d}-{row['name']}.{stream}.txt",
                    f"tool_versions[{index}] {stream} path",
                )
                if not isinstance(descriptor, dict) or descriptor.get("path") != expected_path:
                    errors.append(
                        f"tool_versions[{index}].{stream}_artifact path is not canonical"
                    )
                elif descriptor.get("kind") != f"tool_version_{stream}":
                    errors.append(
                        f"tool_versions[{index}].{stream}_artifact kind is invalid"
                    )
        if row.get("execution_status") == "completed" and row.get("exit_code") == 0:
            if not isinstance(row.get("reported_version"), str) or not row["reported_version"].strip():
                errors.append(f"tool_versions[{index}].reported_version is empty")
            else:
                try:
                    streams = []
                    for field in ("stdout_artifact", "stderr_artifact"):
                        relative = normalize_relative_path(
                            row[field]["path"], f"tool_versions[{index}].{field}.path"
                        )
                        streams.append((root / relative).read_bytes())
                    text = (streams[0] + b"\n" + streams[1]).decode("utf-8", errors="replace")
                    reported = next(
                        (line.strip() for line in text.splitlines() if line.strip()), ""
                    )
                    if row["reported_version"] != reported:
                        errors.append(
                            f"tool_versions[{index}].reported_version does not match captured output"
                        )
                except (EvidenceError, KeyError, OSError) as exc:
                    errors.append(f"cannot derive tool_versions[{index}].reported_version: {exc}")
    for index, row in enumerate(command_rows, 1):
        if isinstance(row.get("name"), str):
            for stream in ("stdout", "stderr"):
                descriptor = row.get(f"{stream}_artifact")
                expected_path = repo_relative(
                    root,
                    result_file.parent
                    / "artifacts"
                    / "commands"
                    / f"{index:03d}-{row['name']}.{stream}.txt",
                    f"commands[{index}] {stream} path",
                )
                if not isinstance(descriptor, dict) or descriptor.get("path") != expected_path:
                    errors.append(f"commands[{index}].{stream}_artifact path is not canonical")
                elif descriptor.get("kind") != f"command_{stream}":
                    errors.append(f"commands[{index}].{stream}_artifact kind is invalid")
        dependencies = row.get("tools")
        if not isinstance(dependencies, list) or not dependencies:
            errors.append(f"commands[{index}].tools must be a non-empty array")
        else:
            unknown = sorted(set(dependencies) - tool_names)
            if unknown:
                errors.append(f"commands[{index}] references unrecorded tools: {', '.join(unknown)}")

    artifact_manifest = result.get("artifact_manifest")
    manifest_artifact_paths: set[str] = set()
    if not isinstance(artifact_manifest, list) or not artifact_manifest:
        errors.append("artifact_manifest must be a non-empty array")
    else:
        for index, descriptor in enumerate(artifact_manifest, 1):
            errors.extend(descriptor_errors(root, descriptor, f"artifact_manifest[{index}]"))
            if isinstance(descriptor, dict) and isinstance(descriptor.get("path"), str):
                if descriptor["path"] in manifest_artifact_paths:
                    errors.append(f"artifact_manifest contains duplicate path: {descriptor['path']}")
                manifest_artifact_paths.add(descriptor["path"])

    expected_artifacts = tool_artifacts | command_artifacts
    if isinstance(manifest_descriptor, dict) and isinstance(manifest_descriptor.get("path"), str):
        expected_artifacts.add(manifest_descriptor["path"])
    if manifest_artifact_paths != expected_artifacts:
        errors.append("artifact_manifest paths do not exactly match referenced generated artifacts")
    elif isinstance(artifact_manifest, list):
        indexed_descriptors = {
            descriptor["path"]: descriptor
            for descriptor in artifact_manifest
            if isinstance(descriptor, dict) and isinstance(descriptor.get("path"), str)
        }
        referenced_descriptors = [manifest_descriptor]
        referenced_descriptors.extend(
            row.get(stream)
            for row in tool_rows + command_rows
            for stream in ("stdout_artifact", "stderr_artifact")
        )
        for descriptor in referenced_descriptors:
            if not isinstance(descriptor, dict) or not isinstance(descriptor.get("path"), str):
                continue
            if indexed_descriptors.get(descriptor["path"]) != descriptor:
                errors.append(
                    f"artifact_manifest descriptor does not match its reference: {descriptor['path']}"
                )

    self_reference = result.get("self_reference_policy")
    expected_exclusions: set[str] = set(manifest_artifact_paths)
    if not isinstance(self_reference, dict):
        errors.append("self_reference_policy must be an object")
    else:
        try:
            recorded_result_path = normalize_relative_path(
                self_reference.get("result_path"), "self_reference_policy.result_path"
            )
            actual_result_path = repo_relative(root, result_file, "result path")
            if recorded_result_path != actual_result_path:
                errors.append("self-reference result path does not match the verified file")
            expected_exclusions.add(recorded_result_path)
        except EvidenceError as exc:
            errors.append(str(exc))
        if self_reference.get("excluded_generated_paths") != sorted(excluded_paths):
            errors.append("self-reference excluded paths do not match manifest exclusions")
    if set(excluded_paths) != expected_exclusions:
        errors.append("manifest exclusions are not exactly the generated evidence artifact set")

    executions_passed = all(
        row.get("execution_status") == "completed"
        and row.get("exit_code") == 0
        and row.get("projection_matches_tested") is True
        and row.get("executable_identity_matches_bound") is True
        and row.get("dependency_identities_match_bound") is True
        and row.get("process_group_empty_after_cleanup") is True
        for row in tool_rows + command_rows
    )
    expected_status = (
        "passed"
        if executions_passed and result.get("projection_unchanged_after_validation") is True
        else "failed"
    )
    if result.get("status") != expected_status:
        errors.append("validation status is inconsistent with command statuses or projection stability")
    recorder = result.get("recorder")
    if not isinstance(recorder, dict):
        errors.append("recorder must be an object")
    elif recorder.get("script_sha256") != sha256_file(Path(__file__)):
        errors.append("recorder script SHA-256 does not match the verifier implementation")
    return {
        "ok": not errors,
        "recorded_status": result.get("status"),
        "tested_projection_sha256": result.get("tested_projection_sha256"),
        "errors": errors,
    }


def parse_json_argument(value: str, label: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"{label} must be valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError(f"{label} must be a JSON object")
    return parsed


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="operation", required=True)
    run = sub.add_parser("run", help="freeze a content projection and execute validation commands")
    run.add_argument("--repo-root", required=True)
    run.add_argument("--output-dir", required=True)
    run.add_argument(
        "--tool-version",
        action="append",
        required=True,
        type=lambda value: parse_json_argument(value, "--tool-version"),
    )
    run.add_argument(
        "--command",
        action="append",
        required=True,
        type=lambda value: parse_json_argument(value, "--command"),
    )
    verify = sub.add_parser("verify", help="verify projection and artifact integrity without rerunning commands")
    verify.add_argument("--repo-root", required=True)
    verify.add_argument("--manifest", required=True)
    verify.add_argument("--result", required=True)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.operation == "run":
            value = run_validation(
                Path(args.repo_root),
                Path(args.output_dir),
                args.command,
                args.tool_version,
            )
            code = 0 if value["status"] == "passed" else 1
        else:
            value = verify_evidence(
                Path(args.repo_root),
                Path(args.manifest),
                Path(args.result),
            )
            code = 0 if value["ok"] else 1
    except EvidenceError as exc:
        value = {"ok": False, "error": str(exc)}
        code = 1
    print(canonical_bytes(value).decode("utf-8"), end="")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
