"""Signed promotion, reviewed GitHub merge, atomic install, and rollback."""

from __future__ import annotations

import base64
import csv
import fcntl
import io
import json
import os
import shutil
import stat
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence

from .core import (
    PipelineError,
    atomic_write_json,
    canonical_json_bytes,
    ensure_private_directory,
    ensure_private_file,
    is_within,
    iso_now,
    load_json,
    parse_time,
    regular_files,
    run_command,
    sha256_file,
    sha256_json,
    utc_now,
    validate_relative_path,
)
from .evaluation import (
    BLIND_MAP_RELATIVE_PATH,
    invoke_adapter,
    verify_evidence_manifest,
    verify_lifecycle_executable_binding,
)
from .execution_authorization import role_bindings


REQUIRED_PERMISSIONS = {
    "push_branch",
    "create_pr",
    "merge_reviewed_pr",
    "install_root_skill",
    "run_canary",
    "rollback",
}

SUCCESSFUL_CHECK_CONCLUSIONS = {"SUCCESS"}
SUCCESSFUL_STATUS_STATES = {"SUCCESS"}


def _record_hash(record: dict[str, Any]) -> str:
    return sha256_json({key: value for key, value in record.items() if key != "record_sha256"})


def seal_record(record: dict[str, Any]) -> dict[str, Any]:
    sealed = {key: value for key, value in record.items() if key != "record_sha256"}
    sealed["record_sha256"] = sha256_json(sealed)
    return sealed


def validate_sealed_record(record: dict[str, Any], *, status: str | None = None) -> None:
    if record.get("record_sha256") != _record_hash(record):
        raise PipelineError("Record hash mismatch")
    if status is not None and record.get("status") != status:
        raise PipelineError(f"Record status is not {status}")


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(directory, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _durable_write_json(path: Path, value: dict[str, Any]) -> None:
    atomic_write_json(path, value)
    _fsync_directory(path.parent)


def write_immutable_record(path: Path, record: dict[str, Any]) -> dict[str, Any]:
    sealed = seal_record(record)
    if path.exists():
        if path.is_symlink() or not path.is_file():
            raise PipelineError(f"Unsafe immutable record path: {path}")
        ensure_private_file(path)
        existing = load_json(path)
        validate_sealed_record(existing)
        if canonical_json_bytes(existing) != canonical_json_bytes(sealed):
            raise PipelineError(f"Immutable record already exists with different content: {path}")
        return existing
    _durable_write_json(path, sealed)
    return sealed


def load_immutable_record(path: Path, *, status: str | None = None) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise PipelineError(f"Immutable record is missing or unsafe: {path}")
    ensure_private_file(path)
    record = load_json(path)
    validate_sealed_record(record, status=status)
    return record


def _assert_safe_descendant(root: Path, path: Path, *, allow_missing_leaf: bool = True) -> None:
    if root.is_symlink() or not root.is_dir():
        raise PipelineError(f"Unsafe destination root: {root}")
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise PipelineError(f"Destination escapes configured root: {path}") from exc
    current = root
    for index, part in enumerate(relative.parts):
        current = current / part
        if current.is_symlink():
            raise PipelineError(f"Symlink destination ancestor is forbidden: {current}")
        if current.exists() and index < len(relative.parts) - 1 and not current.is_dir():
            raise PipelineError(f"Non-directory destination ancestor: {current}")
    if not allow_missing_leaf and not path.exists():
        raise PipelineError(f"Expected destination does not exist: {path}")
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=True))
    except (FileNotFoundError, ValueError) as exc:
        raise PipelineError(f"Resolved destination escapes configured root: {path}") from exc


def _tree_hashes(root: Path) -> dict[str, str]:
    if not root.is_dir() or root.is_symlink():
        raise PipelineError(f"Unsafe tree: {root}")
    hashes: dict[str, str] = {}
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        for directory in list(directories):
            candidate = current_path / directory
            if candidate.is_symlink():
                raise PipelineError(f"Symlink is forbidden in tree: {candidate}")
        for filename in files:
            candidate = current_path / filename
            if candidate.is_symlink() or not candidate.is_file():
                raise PipelineError(f"Only regular files are allowed in tree: {candidate}")
            hashes[candidate.relative_to(root).as_posix()] = sha256_file(candidate)
    return dict(sorted(hashes.items()))


@contextmanager
def installation_lock(skills_root: Path, skill_name: str) -> Iterator[None]:
    _assert_safe_descendant(skills_root, skills_root / f".{skill_name}.install.lock")
    lock_path = skills_root / f".{skill_name}.install.lock"
    try:
        descriptor = os.open(
            lock_path,
            os.O_CREAT
            | os.O_RDWR
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
    except OSError as exc:
        raise PipelineError(f"Unsafe or inaccessible installation lock: {lock_path}") from exc
    try:
        lock_stat = os.fstat(descriptor)
        if (
            not stat.S_ISREG(lock_stat.st_mode)
            or lock_stat.st_uid != os.geteuid()
            or lock_stat.st_nlink != 1
        ):
            raise PipelineError(f"Installation lock is not a private regular file: {lock_path}")
        os.fchmod(descriptor, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise PipelineError(f"Another installation owns the lock: {lock_path}") from exc
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def approval_payload(approval: dict[str, Any]) -> bytes:
    return canonical_json_bytes({key: value for key, value in approval.items() if key != "signature"})


def verify_ssh_signature(approval: dict[str, Any], config: dict[str, Any]) -> None:
    settings = config.get("approval_verification", {})
    allowed_signers = Path(str(settings.get("allowed_signers_path", "")))
    expected_identity = str(settings.get("expected_identity", ""))
    namespace = str(settings.get("namespace", ""))
    signature = approval.get("signature", {})
    if not expected_identity or not namespace or not allowed_signers.is_file() or allowed_signers.is_symlink():
        raise PipelineError("SSH approval verification is not fully configured")
    if signature.get("algorithm") != "ssh-keygen-y":
        raise PipelineError("Approval signature algorithm is unsupported")
    if signature.get("identity") != expected_identity or signature.get("namespace") != namespace:
        raise PipelineError("Approval signer identity or namespace does not match configuration")
    try:
        decoded = base64.b64decode(signature.get("value", ""), validate=True)
    except (ValueError, TypeError) as exc:
        raise PipelineError("Approval signature is not valid base64") from exc
    with tempfile.TemporaryDirectory(prefix="explore-approval-") as temporary:
        signature_path = Path(temporary) / "approval.sig"
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
            input_text=approval_payload(approval).decode("utf-8"),
            check=False,
        )
    if result.returncode != 0:
        raise PipelineError(f"SSH approval signature verification failed: {result.stderr.strip()}")


def validate_approval(
    approval: dict[str, Any],
    config: dict[str, Any],
    candidate_manifest: dict[str, Any],
    evaluation_summary_path: Path,
    holdout_manifest_path: Path,
    rollback_evidence_path: Path,
    *,
    signature_verifier: Callable[[dict[str, Any], dict[str, Any]], None] = verify_ssh_signature,
) -> None:
    summary = load_json(evaluation_summary_path)
    required = {
        "schema_version",
        "approval_id",
        "decision",
        "approved_by",
        "approved_at",
        "expires_at",
        "evaluation_completed_at",
        "candidate",
        "evidence",
        "target",
        "permissions",
        "thresholds_met",
        "accepted_exceptions",
        "signature",
    }
    if set(approval) - (required | {"notes"}) or not required.issubset(approval):
        raise PipelineError("Approval fields do not match the v2 contract")
    if approval["schema_version"] != "2.0" or approval["decision"] != "promote" or approval["thresholds_met"] is not True:
        raise PipelineError("Approval does not authorize promotion")
    if approval.get("accepted_exceptions") != []:
        raise PipelineError("Automated promotion does not permit signed threshold exceptions")
    if not isinstance(approval.get("approved_by"), str) or not approval["approved_by"].strip() or "REPLACE_WITH" in approval["approved_by"]:
        raise PipelineError("Approval lacks a named human approver")
    verified_identity = str(config.get("approval_verification", {}).get("expected_identity", ""))
    if not verified_identity or approval["approved_by"] != verified_identity:
        raise PipelineError("Approval attribution does not match the verified approval identity")
    if set(approval["permissions"]) != REQUIRED_PERMISSIONS:
        raise PipelineError("Approval permissions are incomplete or over-broad")
    completed_at = parse_time(str(summary.get("completed_at")))
    if parse_time(str(approval["evaluation_completed_at"])) != completed_at:
        raise PipelineError("Approval evaluation timestamp does not match the summary")
    approved_at = parse_time(str(approval["approved_at"]))
    expires_at = parse_time(str(approval["expires_at"]))
    if approved_at <= completed_at or expires_at <= approved_at or utc_now() >= expires_at:
        raise PipelineError("Approval is pre-result, expired, or has an invalid time window")

    candidate = approval["candidate"]
    expected_candidate = config["candidate"]
    if candidate.get("name") != expected_candidate["name"] or candidate.get("version") != expected_candidate["version"]:
        raise PipelineError("Approval targets another candidate")
    if candidate.get("manifest_sha256") != candidate_manifest.get("manifest_sha256"):
        raise PipelineError("Approval candidate manifest hash mismatch")

    evidence = approval["evidence"]
    evidence_manifest_path = evaluation_summary_path.parent / "evidence-manifest.json"
    if not evidence_manifest_path.is_file() or evidence_manifest_path.is_symlink():
        raise PipelineError("Promotion requires the canonical evaluation evidence manifest")
    verified_evidence_manifest = verify_evidence_manifest(evaluation_summary_path.parent, config)
    blind_map_artifact = verified_evidence_manifest.get("artifacts", {}).get("blind_map", {})
    if (
        blind_map_artifact.get("path") != BLIND_MAP_RELATIVE_PATH
        or blind_map_artifact.get("sha256") != verified_evidence_manifest.get("blind_map_sha256")
    ):
        raise PipelineError("Verified evidence manifest does not bind the canonical private blind map")
    evidence_manifest_sha256 = sha256_file(evidence_manifest_path)
    if summary.get("evidence", {}).get("evidence_manifest_sha256") != evidence_manifest_sha256:
        raise PipelineError("Evaluation summary does not bind the canonical evidence manifest")
    expected_evidence = {
        "evaluation_summary_sha256": sha256_file(evaluation_summary_path),
        "evidence_manifest_sha256": evidence_manifest_sha256,
        "blind_key_commitment": verified_evidence_manifest["blind_key_commitment"],
        "blind_map_path": BLIND_MAP_RELATIVE_PATH,
        "blind_map_sha256": verified_evidence_manifest["blind_map_sha256"],
        "holdout_manifest_sha256": sha256_file(holdout_manifest_path),
        "protocol_sha256": summary.get("protocol_sha256") or load_json(evaluation_summary_path).get("protocol_sha256"),
        "rubric_sha256": summary.get("rubric_sha256") or load_json(evaluation_summary_path).get("rubric_sha256"),
        "rollback_evidence_sha256": sha256_file(rollback_evidence_path),
        "config_sha256": sha256_json(config),
        "lifecycle_executables_sha256": None,
    }
    # Protocol and rubric bindings may live in the frozen plan instead of the summary.
    plan_path = evaluation_summary_path.parent / "plan.json"
    if not plan_path.is_file():
        raise PipelineError("Promotion requires a frozen evaluation plan")
    plan = load_json(plan_path)
    if plan.get("plan_sha256") != sha256_json({key: value for key, value in plan.items() if key != "plan_sha256"}):
        raise PipelineError("Frozen plan hash mismatch")
    if plan.get("config_sha256") != sha256_json(config):
        raise PipelineError("Promotion configuration changed after evaluation freeze")
    if plan.get("candidate_manifest_sha256") != candidate_manifest.get("manifest_sha256"):
        raise PipelineError("Frozen plan targets another candidate manifest")
    if candidate.get("base_commit") != plan.get("base_commit"):
        raise PipelineError("Approval base commit does not match the frozen plan")
    expected_evidence["protocol_sha256"] = plan.get("protocol_sha256")
    expected_evidence["rubric_sha256"] = plan.get("rubric_sha256")
    expected_evidence["config_sha256"] = plan.get("config_sha256")
    expected_evidence["lifecycle_executables_sha256"] = plan.get(
        "lifecycle_executables_sha256"
    )
    if evidence != expected_evidence:
        raise PipelineError("Approval evidence hashes do not match immutable run artifacts")

    promotion = config["promotion"]
    installation = config["installation"]
    target = approval["target"]
    expected_target = {
        "repository_url": promotion["repository_url"],
        "repository_slug": promotion["repository_slug"],
        "base_branch": promotion["base_branch"],
        "feature_branch": promotion["feature_branch"],
        "root_skills_path": str(Path(installation["skills_root"]) / installation["skill_name"]),
    }
    if target != expected_target:
        raise PipelineError("Approval targets do not match pipeline configuration")
    signature_verifier(approval, config)


def _verify_manifest(manifest: dict[str, Any]) -> None:
    body = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    if manifest.get("manifest_sha256") != sha256_json(body):
        raise PipelineError("Candidate manifest hash mismatch")
    paths = [entry.get("path") for entry in manifest.get("files", [])]
    if len(paths) != len(set(paths)):
        raise PipelineError("Candidate manifest contains path collisions")
    for value in paths:
        validate_relative_path(str(value))


def _copy_manifest_files(source_root: Path, destination_root: Path, manifest: dict[str, Any]) -> None:
    for entry in manifest["files"]:
        relative = validate_relative_path(entry["path"])
        source = source_root / relative
        destination = destination_root / relative
        if not source.is_file() or source.is_symlink() or not is_within(source, source_root):
            raise PipelineError(f"Unsafe manifest source: {relative}")
        if source.stat().st_size != entry["size"] or sha256_file(source) != entry["sha256"]:
            raise PipelineError(f"Manifest source changed: {relative}")
        _assert_safe_descendant(destination_root, destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        _assert_safe_descendant(destination_root, destination)
        if destination.exists() and (destination.is_symlink() or not destination.is_file()):
            raise PipelineError(f"Unsafe destination collision: {relative}")
        shutil.copyfile(source, destination)


def _merge_csv_records(destination_root: Path, records: list[dict[str, Any]]) -> None:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(record["path"], []).append(record)
    for relative_value, selected in grouped.items():
        relative = validate_relative_path(relative_value)
        destination = destination_root / relative
        _assert_safe_descendant(destination_root, destination, allow_missing_leaf=False)
        if not destination.is_file() or destination.is_symlink():
            raise PipelineError(f"Clean clone lacks ledger: {relative}")
        lines = destination.read_text(encoding="utf-8").splitlines()
        rows = list(csv.reader(lines))
        if not lines or not rows:
            raise PipelineError(f"Clean clone ledger is empty: {relative}")
        header = rows[0]
        replacements = {record["record_id"]: record for record in selected}
        merged: list[str] = [lines[0]]
        seen: set[str] = set()
        for row, raw_line in zip(rows[1:], lines[1:]):
            if row and row[0] in replacements:
                replacement = replacements[row[0]]
                merged.append(replacement.get("line") or _csv_line(replacement["values"]))
                seen.add(row[0])
            else:
                merged.append(raw_line)
        for record_id in sorted(set(replacements) - seen):
            replacement = replacements[record_id]
            merged.append(replacement.get("line") or _csv_line(replacement["values"]))
        parsed = list(csv.reader(merged))
        if any(len(row) != len(header) for row in parsed):
            raise PipelineError(f"Ledger width mismatch after merge: {relative}")
        destination.write_text("\n".join(merged) + "\n", encoding="utf-8")


def _csv_line(values: Sequence[str]) -> str:
    buffer = io.StringIO(newline="")
    csv.writer(buffer, lineterminator="\n").writerow(values)
    return buffer.getvalue().rstrip("\n")


def _merge_markdown_records(destination_root: Path, records: list[dict[str, Any]]) -> None:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(record["path"], []).append(record)
    for relative_value, selected in grouped.items():
        relative = validate_relative_path(relative_value)
        destination = destination_root / relative
        _assert_safe_descendant(destination_root, destination, allow_missing_leaf=False)
        if not destination.is_file() or destination.is_symlink():
            raise PipelineError(f"Clean clone lacks markdown ledger: {relative}")
        lines = destination.read_text(encoding="utf-8").splitlines()
        for record in selected:
            indexes = [index for index, line in enumerate(lines) if line.startswith(f"| {record['record_id']} |")]
            if len(indexes) > 1:
                raise PipelineError(f"Duplicate markdown record in clean clone: {record['record_id']}")
            if indexes:
                lines[indexes[0]] = record["line"]
            else:
                table_rows = [index for index, line in enumerate(lines) if line.startswith("|")]
                if not table_rows:
                    raise PipelineError(f"No markdown table in clean clone: {relative}")
                lines.insert(table_rows[-1] + 1, record["line"])
        destination.write_text("\n".join(lines) + "\n", encoding="utf-8")


def materialize_change(source_root: Path, clean_root: Path, manifest: dict[str, Any]) -> list[str]:
    _verify_manifest(manifest)
    _copy_manifest_files(source_root, clean_root, manifest)
    _merge_csv_records(clean_root, manifest.get("csv_records", []))
    _merge_markdown_records(clean_root, manifest.get("markdown_records", []))
    expected = {entry["path"] for entry in manifest["files"]}
    expected.update(record["path"] for record in manifest.get("csv_records", []))
    expected.update(record["path"] for record in manifest.get("markdown_records", []))
    return sorted(expected)


def _approved_manifest_paths(manifest: dict[str, Any]) -> set[str]:
    _verify_manifest(manifest)
    paths = {str(entry["path"]) for entry in manifest.get("files", [])}
    paths.update(str(record["path"]) for record in manifest.get("csv_records", []))
    paths.update(str(record["path"]) for record in manifest.get("markdown_records", []))
    return paths


def verify_promoted_manifest(checkout: Path, manifest: dict[str, Any]) -> dict[str, str]:
    """Verify every direct file and governed ledger record in the approved manifest."""
    _verify_manifest(manifest)
    verified: dict[str, str] = {}
    for entry in manifest.get("files", []):
        relative = validate_relative_path(str(entry["path"]))
        candidate = checkout / relative
        if not is_within(candidate, checkout) or candidate.is_symlink() or not candidate.is_file():
            raise PipelineError(f"Promoted manifest file is missing or unsafe: {relative}")
        if candidate.stat().st_size != entry["size"] or sha256_file(candidate) != entry["sha256"]:
            raise PipelineError(f"Promoted file differs from candidate manifest: {relative}")
        verified[relative.as_posix()] = sha256_file(candidate)

    for record in manifest.get("csv_records", []):
        relative = validate_relative_path(str(record["path"]))
        candidate = checkout / relative
        if not is_within(candidate, checkout) or candidate.is_symlink() or not candidate.is_file():
            raise PipelineError(f"Promoted CSV ledger is missing or unsafe: {relative}")
        lines = candidate.read_text(encoding="utf-8").splitlines()
        parsed = list(csv.reader(lines))
        matches = [
            raw
            for raw, row in zip(lines, parsed)
            if row and row[0] == str(record["record_id"])
        ]
        expected_line = str(record.get("line") or _csv_line(record["values"]))
        if matches != [expected_line]:
            raise PipelineError(f"Promoted CSV record differs from candidate manifest: {record['record_id']}")
        verified[relative.as_posix()] = sha256_file(candidate)

    for record in manifest.get("markdown_records", []):
        relative = validate_relative_path(str(record["path"]))
        candidate = checkout / relative
        if not is_within(candidate, checkout) or candidate.is_symlink() or not candidate.is_file():
            raise PipelineError(f"Promoted markdown ledger is missing or unsafe: {relative}")
        matches = [
            line
            for line in candidate.read_text(encoding="utf-8").splitlines()
            if line.startswith(f"| {record['record_id']} |")
        ]
        if matches != [str(record["line"])]:
            raise PipelineError(f"Promoted markdown record differs from candidate manifest: {record['record_id']}")
        verified[relative.as_posix()] = sha256_file(candidate)
    return dict(sorted(verified.items()))


def prepare_clean_promotion(
    source_root: Path,
    work_root: Path,
    config: dict[str, Any],
    manifest: dict[str, Any],
    *,
    expected_base_commit: str,
    approval_sha256: str,
    config_sha256: str,
) -> dict[str, Any]:
    promotion = config["promotion"]
    clone = work_root / "clean-repository"
    if clone.exists():
        raise PipelineError(f"Clean promotion directory already exists: {clone}")
    if len(expected_base_commit) not in {40, 64} or any(character not in "0123456789abcdef" for character in expected_base_commit):
        raise PipelineError("Expected base commit is not an immutable Git object ID")
    work_root.mkdir(parents=True, exist_ok=True)
    run_command(["git", "clone", "--no-checkout", promotion["repository_url"], str(clone)])
    run_command(["git", "config", "core.hooksPath", "/dev/null"], cwd=clone)
    run_command(["git", "fetch", "origin", promotion["base_branch"]], cwd=clone)
    belongs = run_command(
        ["git", "merge-base", "--is-ancestor", expected_base_commit, f"origin/{promotion['base_branch']}"],
        cwd=clone,
        check=False,
    )
    if belongs.returncode != 0:
        raise PipelineError("Signed base commit is not an ancestor of the configured base branch")
    run_command(["git", "checkout", "--detach", expected_base_commit], cwd=clone)
    base_commit = run_command(["git", "rev-parse", "HEAD"], cwd=clone).stdout.strip()
    if base_commit != expected_base_commit:
        raise PipelineError("Clean clone did not resolve the signed frozen base commit")
    run_command(["git", "switch", "-c", promotion["feature_branch"]], cwd=clone)
    allowed = materialize_change(source_root, clone, manifest)
    run_command(["git", "add", "--", *allowed], cwd=clone)
    staged = [line for line in run_command(["git", "diff", "--cached", "--name-only", "-z"], cwd=clone).stdout.split("\0") if line]
    if not staged or set(staged) - set(allowed):
        raise PipelineError(f"Staged paths are empty or outside the allowlist: {sorted(set(staged) - set(allowed))}")
    run_command(["git", "diff", "--cached", "--check"], cwd=clone)
    run_command(["git", "commit", "-m", promotion["commit_message"], "--no-verify"], cwd=clone)
    head_commit = run_command(["git", "rev-parse", "HEAD"], cwd=clone).stdout.strip()
    head_tree = run_command(["git", "rev-parse", "HEAD^{tree}"], cwd=clone).stdout.strip()
    return {
        "clone": str(clone),
        "base_commit": base_commit,
        "head_commit": head_commit,
        "head_tree": head_tree,
        "staged_paths": sorted(staged),
        "approval_sha256": approval_sha256,
        "candidate_manifest_sha256": manifest["manifest_sha256"],
        "config_sha256": config_sha256,
    }


def _canonical_materialized_tree(
    source_checkout: Path,
    base_commit: str,
    work_root: Path,
    manifest: dict[str, Any],
) -> str:
    """Rebuild the only authorized full tree from the signed base and manifest."""

    with tempfile.TemporaryDirectory(prefix=".promotion-rederive-", dir=work_root) as temporary:
        canonical = Path(temporary) / "canonical-repository"
        run_command(["git", "clone", "--no-checkout", "--", str(source_checkout), str(canonical)])
        run_command(["git", "config", "core.hooksPath", "/dev/null"], cwd=canonical)
        run_command(["git", "checkout", "--detach", base_commit], cwd=canonical)
        allowed = materialize_change(source_checkout, canonical, manifest)
        run_command(["git", "add", "--", *allowed], cwd=canonical)
        staged = {
            path
            for path in run_command(
                ["git", "diff", "--cached", "--name-only", "-z"], cwd=canonical
            ).stdout.split("\0")
            if path
        }
        if staged - set(allowed):
            raise PipelineError("Canonical promotion materialization escaped the approved manifest")
        untracked = run_command(
            ["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=canonical
        ).stdout
        if untracked:
            raise PipelineError("Canonical promotion materialization produced untracked files")
        run_command(["git", "diff", "--cached", "--check"], cwd=canonical)
        return run_command(["git", "write-tree"], cwd=canonical).stdout.strip()


def validate_prepared_promotion(
    prepared: dict[str, Any],
    run_dir: Path,
    config: dict[str, Any],
    manifest: dict[str, Any],
    *,
    approval_sha256: str,
) -> dict[str, Any]:
    """Re-derive every trusted property of a crash-recovered promotion receipt."""
    validate_sealed_record(prepared)
    expected_bindings = {
        "approval_sha256": approval_sha256,
        "candidate_manifest_sha256": manifest.get("manifest_sha256"),
        "config_sha256": sha256_json(config),
    }
    if any(prepared.get(key) != value for key, value in expected_bindings.items()):
        raise PipelineError("Prepared promotion receipt is not bound to the approved inputs")

    clone_value = prepared.get("clone")
    if not isinstance(clone_value, str) or not clone_value:
        raise PipelineError("Prepared promotion receipt lacks a clean clone")
    clone_path = Path(clone_value).expanduser()
    try:
        clone = clone_path.resolve(strict=True)
        governed_root = run_dir.resolve(strict=True)
    except OSError as exc:
        raise PipelineError("Prepared promotion clone cannot be resolved") from exc
    if clone_path.is_symlink() or not clone.is_dir() or not is_within(clone, governed_root):
        raise PipelineError("Prepared promotion clone is outside governed run data")

    promotion = config["promotion"]
    remote = str(promotion["remote"])
    origin = run_command(["git", "remote", "get-url", remote], cwd=clone).stdout.strip()
    if origin != promotion["repository_url"]:
        raise PipelineError("Prepared promotion clone targets another repository")
    run_command(["git", "fetch", "--no-tags", remote, promotion["base_branch"]], cwd=clone)

    actual_head = run_command(["git", "rev-parse", "HEAD"], cwd=clone).stdout.strip()
    actual_tree = run_command(["git", "rev-parse", "HEAD^{tree}"], cwd=clone).stdout.strip()
    if actual_head != prepared.get("head_commit") or actual_tree != prepared.get("head_tree"):
        raise PipelineError("Prepared promotion HEAD or tree differs from its receipt")
    branch = run_command(["git", "branch", "--show-current"], cwd=clone).stdout.strip()
    if branch != promotion["feature_branch"]:
        raise PipelineError("Prepared promotion is not on the configured feature branch")
    if run_command(["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"], cwd=clone).stdout:
        raise PipelineError("Prepared promotion clone contains uncommitted or untracked changes")

    base_commit = str(prepared.get("base_commit", ""))
    if len(base_commit) not in {40, 64} or any(character not in "0123456789abcdef" for character in base_commit):
        raise PipelineError("Prepared promotion base is not an immutable Git object ID")
    belongs = run_command(
        ["git", "merge-base", "--is-ancestor", base_commit, f"{remote}/{promotion['base_branch']}"],
        cwd=clone,
        check=False,
    )
    if belongs.returncode != 0:
        raise PipelineError("Prepared promotion base is not reachable from the configured base branch")
    parents = run_command(["git", "rev-list", "--parents", "-n", "1", actual_head], cwd=clone).stdout.split()
    if parents != [actual_head, base_commit]:
        raise PipelineError("Prepared promotion must be exactly one commit on the signed base")

    actual_paths = sorted(
        path
        for path in run_command(
            ["git", "diff", "--name-only", "-z", f"{base_commit}..{actual_head}"], cwd=clone
        ).stdout.split("\0")
        if path
    )
    recorded_paths = prepared.get("staged_paths")
    if not isinstance(recorded_paths, list) or recorded_paths != sorted(set(str(path) for path in recorded_paths)):
        raise PipelineError("Prepared promotion staged paths are not canonical")
    if not actual_paths or actual_paths != recorded_paths:
        raise PipelineError("Prepared promotion diff differs from its recorded staged paths")
    unauthorized = sorted(set(actual_paths) - _approved_manifest_paths(manifest))
    if unauthorized:
        raise PipelineError(f"Prepared promotion diff contains paths outside the approved manifest: {unauthorized}")
    run_command(["git", "diff", "--check", f"{base_commit}..{actual_head}"], cwd=clone)
    verify_promoted_manifest(clone, manifest)
    canonical_tree = _canonical_materialized_tree(clone, base_commit, governed_root, manifest)
    if actual_tree != canonical_tree:
        raise PipelineError("Prepared promotion tree differs from canonical approved materialization")
    return prepared


def push_and_open_pr(clean_root: Path, config: dict[str, Any]) -> dict[str, Any]:
    promotion = config["promotion"]
    github_actor = verify_github_actor(config, cwd=clean_root)
    head_commit = run_command(["git", "rev-parse", "HEAD"], cwd=clean_root).stdout.strip()
    run_command(
        ["git", "push", "--set-upstream", promotion["remote"], promotion["feature_branch"]],
        cwd=clean_root,
    )
    listed = json.loads(
        run_command(
            [
                "gh",
                "pr",
                "list",
                "--repo",
                promotion["repository_slug"],
                "--head",
                promotion["feature_branch"],
                "--state",
                "all",
                "--json",
                "url,headRefOid",
            ],
            cwd=clean_root,
        ).stdout
    )
    matching = [item for item in listed if item.get("headRefOid") == head_commit]
    if matching:
        pr_url = matching[0]["url"]
    else:
        created = run_command(
            [
                "gh",
                "pr",
                "create",
                "--repo",
                promotion["repository_slug"],
                "--base",
                promotion["base_branch"],
                "--head",
                promotion["feature_branch"],
                "--title",
                promotion["pr_title"],
                "--body",
                "Governed promotion. Evidence and signed authorization are recorded in the run receipt; private holdout data is excluded.",
            ],
            cwd=clean_root,
        )
        pr_url = created.stdout.strip().splitlines()[-1]
    return {
        "pr_url": pr_url,
        "head_commit": head_commit,
        "opened_at": iso_now(),
        "github_actor": github_actor,
    }


def build_pr_record(
    prepared: dict[str, Any],
    opened: dict[str, Any],
    *,
    approval_sha256: str,
    candidate_manifest_sha256: str,
    config_sha256: str,
) -> dict[str, Any]:
    if prepared.get("head_commit") != opened.get("head_commit"):
        raise PipelineError("Prepared commit and pull-request head differ")
    if not isinstance(opened.get("github_actor"), str) or not opened["github_actor"].strip():
        raise PipelineError("Pull-request result lacks the verified GitHub actor")
    return seal_record(
        {
            "schema_version": "2.0",
            "approval_sha256": approval_sha256,
            "candidate_manifest_sha256": candidate_manifest_sha256,
            "config_sha256": config_sha256,
            "base_commit": prepared["base_commit"],
            "head_commit": prepared["head_commit"],
            "staged_paths": sorted(prepared["staged_paths"]),
            "pr_url": opened["pr_url"],
            "opened_at": opened["opened_at"],
            "github_actor": opened["github_actor"],
            "status": "pr-open",
        }
    )


def build_release_record(pr_record: dict[str, Any], merged: dict[str, Any]) -> dict[str, Any]:
    validate_sealed_record(pr_record, status="pr-open")
    if pr_record.get("head_commit") != merged.get("head_commit") or pr_record.get("pr_url") != merged.get("pr_url"):
        raise PipelineError("Merge result does not match immutable pull-request record")
    if str(pr_record.get("github_actor", "")).casefold() != str(merged.get("github_actor", "")).casefold():
        raise PipelineError("Merge credential differs from the pull-request automation actor")
    return seal_record(
        {
            "schema_version": "2.0",
            "approval_sha256": pr_record["approval_sha256"],
            "candidate_manifest_sha256": pr_record["candidate_manifest_sha256"],
            "config_sha256": pr_record["config_sha256"],
            "pr_record_sha256": pr_record["record_sha256"],
            "base_commit": pr_record["base_commit"],
            "head_commit": pr_record["head_commit"],
            "pr_url": pr_record["pr_url"],
            "merge_commit": merged["merge_commit"],
            "merged_at": merged["merged_at"],
            "github_evidence": merged["github_evidence"],
            "github_actor": merged["github_actor"],
            "status": "merged",
        }
    )


def validate_release_record(
    release: dict[str, Any], pr_record: dict[str, Any], merged: dict[str, Any]
) -> dict[str, Any]:
    """Require a recovered receipt to equal freshly queried GitHub evidence."""
    validate_sealed_record(release, status="merged")
    expected = build_release_record(pr_record, merged)
    def stable(value: dict[str, Any]) -> dict[str, Any]:
        normalized = {key: item for key, item in value.items() if key != "record_sha256"}
        evidence = dict(normalized.get("github_evidence") or {})
        evidence.pop("verified_at", None)
        normalized["github_evidence"] = evidence
        return normalized

    if canonical_json_bytes(stable(release)) != canonical_json_bytes(stable(expected)):
        raise PipelineError("Recovered release receipt differs from current verified GitHub merge evidence")
    return release


def _reviewer_policy(
    automation_actor: Any, required_reviewer_logins: Any
) -> tuple[str, dict[str, str]]:
    if (
        not isinstance(automation_actor, str)
        or not automation_actor.strip()
        or "replace_with" in automation_actor.casefold()
    ):
        raise PipelineError("A non-placeholder GitHub automation actor is required")
    if (
        not isinstance(required_reviewer_logins, (list, tuple))
        or not required_reviewer_logins
    ):
        raise PipelineError("At least one allowed GitHub reviewer login is required")

    allowed: dict[str, str] = {}
    for value in required_reviewer_logins:
        if (
            not isinstance(value, str)
            or not value.strip()
            or "replace_with" in value.casefold()
        ):
            raise PipelineError("Allowed GitHub reviewer logins must be non-placeholder strings")
        login = value.strip()
        normalized = login.casefold()
        if normalized in allowed:
            raise PipelineError("Allowed GitHub reviewer logins must be unique")
        allowed[normalized] = login
    actor = automation_actor.strip().casefold()
    if actor in allowed:
        raise PipelineError("The automation actor cannot be an allowed independent reviewer")
    return actor, allowed


def verify_github_actor(config: dict[str, Any], *, cwd: Path | None = None) -> str:
    """Resolve the active gh principal in the exact ambient credential context."""

    configured, _ = _reviewer_policy(
        config.get("promotion", {}).get("automation_actor"),
        config.get("promotion", {}).get("required_reviewer_logins"),
    )
    result = run_command(["gh", "api", "user", "--jq", ".login"], cwd=cwd)
    active = result.stdout.strip()
    if not active or active.casefold() != configured:
        raise PipelineError("Active GitHub credential does not match the frozen automation actor")
    return active


def _validated_pr_snapshot(
    snapshot: dict[str, Any],
    *,
    expected_head: str,
    expected_base: str,
    expected_state: str,
    automation_actor: Any,
    required_reviewer_logins: Any,
    required_reviewer_identity: Any,
    required_checks: Sequence[str],
) -> dict[str, Any]:
    if snapshot.get("state") != expected_state:
        raise PipelineError(f"Pull request state is not {expected_state}")
    if snapshot.get("headRefOid") != expected_head or snapshot.get("baseRefName") != expected_base:
        raise PipelineError("Pull request head or base changed")
    if snapshot.get("reviewDecision") != "APPROVED":
        raise PipelineError("Pull request lacks approval")
    if expected_state == "OPEN" and snapshot.get("mergeStateStatus") != "CLEAN":
        raise PipelineError("Open pull request does not have GitHub CLEAN merge status")

    automation_login, allowed_reviewers = _reviewer_policy(
        automation_actor, required_reviewer_logins
    )
    designated_reviewer = str(required_reviewer_identity or "").strip().casefold()
    if not designated_reviewer or designated_reviewer not in allowed_reviewers:
        raise PipelineError("Frozen PR reviewer is not present in the reviewer policy")
    author = ((snapshot.get("author") or {}).get("login") or "").casefold()
    excluded_reviewers = {author, automation_login}
    reviews = snapshot.get("reviews")
    if not isinstance(reviews, list):
        raise PipelineError("Pull request review evidence is malformed")
    latest_reviews: dict[str, tuple[tuple[str, int], str, str, str]] = {}
    for index, review in enumerate(reviews):
        if not isinstance(review, dict):
            raise PipelineError("Pull request review evidence is malformed")
        login = str((review.get("author") or {}).get("login") or "").strip()
        if not login:
            continue
        normalized = login.casefold()
        order = (str(review.get("submittedAt") or ""), index)
        commit = review.get("commit")
        review_commit = str(commit.get("oid") or "") if isinstance(commit, dict) else ""
        previous = latest_reviews.get(normalized)
        if previous is None or order >= previous[0]:
            latest_reviews[normalized] = (
                order,
                login,
                str(review.get("state") or ""),
                review_commit,
            )
    approved_reviewers = sorted(
        login
        for normalized, (_, login, state, review_commit) in latest_reviews.items()
        if normalized == designated_reviewer
        and normalized not in excluded_reviewers
        and state == "APPROVED"
        and review_commit == expected_head
    )
    if not approved_reviewers:
        raise PipelineError("Pull request lacks a current approval from the frozen independent reviewer")

    checks = snapshot.get("statusCheckRollup")
    if not isinstance(checks, list) or not checks:
        raise PipelineError("Pull request has no successful required checks")
    successful_checks: list[str] = []
    for check in checks:
        name = str(check.get("name") or check.get("context") or check.get("workflowName") or "unnamed")
        if "conclusion" in check or check.get("__typename") == "CheckRun":
            if check.get("status") != "COMPLETED" or check.get("conclusion") not in SUCCESSFUL_CHECK_CONCLUSIONS:
                raise PipelineError(f"Pull request check did not succeed: {name}")
        elif check.get("state") not in SUCCESSFUL_STATUS_STATES:
            raise PipelineError(f"Pull request status did not succeed: {name}")
        successful_checks.append(name)
    expected_checks = {str(name) for name in required_checks if str(name).strip()}
    if not expected_checks:
        raise PipelineError("No required GitHub status-check identities are configured")
    missing_checks = sorted(expected_checks - set(successful_checks))
    if missing_checks:
        raise PipelineError(f"Pull request lacks required successful checks: {missing_checks}")
    return {
        "base_branch": expected_base,
        "head_commit": expected_head,
        "merge_state_status": snapshot.get("mergeStateStatus"),
        "review_decision": "APPROVED",
        "approved_reviewers": approved_reviewers,
        "successful_checks": sorted(successful_checks),
        "verified_at": iso_now(),
    }


def merge_reviewed_pr(pr_url: str, expected_head: str, config: dict[str, Any]) -> dict[str, Any]:
    promotion = config["promotion"]
    roles = role_bindings(config, require_resolved=True)
    slug = promotion["repository_slug"]
    github_actor = verify_github_actor(config)
    fields = "state,headRefOid,baseRefName,reviewDecision,mergeStateStatus,url,mergeCommit,mergedAt,statusCheckRollup,reviews,author"
    before = json.loads(run_command(["gh", "pr", "view", pr_url, "--repo", slug, "--json", fields]).stdout)
    expected_state = "MERGED" if before.get("state") == "MERGED" else "OPEN"
    evidence = _validated_pr_snapshot(
        before,
        expected_head=expected_head,
        expected_base=promotion["base_branch"],
        expected_state=expected_state,
        automation_actor=promotion.get("automation_actor"),
        required_reviewer_logins=promotion.get("required_reviewer_logins"),
        required_reviewer_identity=roles["pr_reviewer"],
        required_checks=promotion.get("required_status_checks", ()),
    )
    if before.get("state") == "MERGED":
        merge_commit = (before.get("mergeCommit") or {}).get("oid")
        merged_at = before.get("mergedAt")
        if not merge_commit or not merged_at:
            raise PipelineError("Merged pull request lacks an immutable merge commit or timestamp")
        return {
            "pr_url": before["url"],
            "head_commit": expected_head,
            "merge_commit": merge_commit,
            "merged_at": merged_at,
            "github_evidence": {**evidence, "github_actor": github_actor},
            "github_actor": github_actor,
        }
    method = promotion.get("merge_method", "squash")
    if method not in {"merge", "squash", "rebase"}:
        raise PipelineError("Unsupported merge method")
    merge_actor = verify_github_actor(config)
    if merge_actor.casefold() != github_actor.casefold():
        raise PipelineError("Active GitHub credential changed during merge verification")
    github_actor = merge_actor
    run_command(["gh", "pr", "merge", pr_url, "--repo", slug, f"--{method}", "--match-head-commit", expected_head])
    after = json.loads(run_command(["gh", "pr", "view", pr_url, "--repo", slug, "--json", fields]).stdout)
    evidence = _validated_pr_snapshot(
        after,
        expected_head=expected_head,
        expected_base=promotion["base_branch"],
        expected_state="MERGED",
        automation_actor=promotion.get("automation_actor"),
        required_reviewer_logins=promotion.get("required_reviewer_logins"),
        required_reviewer_identity=roles["pr_reviewer"],
        required_checks=promotion.get("required_status_checks", ()),
    )
    merge_commit = (after.get("mergeCommit") or {}).get("oid")
    merged_at = after.get("mergedAt")
    if not merge_commit or not merged_at:
        raise PipelineError("Pull request did not reach a verifiable merged state")
    return {
        "pr_url": after["url"],
        "head_commit": expected_head,
        "merge_commit": merge_commit,
        "merged_at": merged_at,
        "github_evidence": {**evidence, "github_actor": github_actor},
        "github_actor": github_actor,
    }


def checkout_immutable_merge(work_root: Path, repository_url: str, merge_commit: str) -> Path:
    checkout = work_root / "merged-checkout"
    if checkout.exists():
        raise PipelineError(f"Merged checkout already exists: {checkout}")
    run_command(["git", "clone", "--no-checkout", repository_url, str(checkout)])
    run_command(["git", "config", "core.hooksPath", "/dev/null"], cwd=checkout)
    run_command(["git", "checkout", "--detach", merge_commit], cwd=checkout)
    actual = run_command(["git", "rev-parse", "HEAD"], cwd=checkout).stdout.strip()
    if actual != merge_commit:
        raise PipelineError("Immutable checkout did not resolve to the approved merge commit")
    return checkout


def verify_merge_reachable(checkout: Path, merge_commit: str, config: dict[str, Any]) -> None:
    """Prove the checked-out merge is reachable from the configured remote base."""
    promotion = config["promotion"]
    remote = str(promotion.get("remote", "origin"))
    origin = run_command(["git", "remote", "get-url", remote], cwd=checkout).stdout.strip()
    if origin != promotion["repository_url"]:
        raise PipelineError("Merged checkout targets another repository")
    run_command(["git", "fetch", "--no-tags", remote, promotion["base_branch"]], cwd=checkout)
    actual = run_command(["git", "rev-parse", "HEAD"], cwd=checkout).stdout.strip()
    if actual != merge_commit:
        raise PipelineError("Merged checkout moved from the verified merge commit")
    reachable = run_command(
        ["git", "merge-base", "--is-ancestor", merge_commit, f"{remote}/{promotion['base_branch']}"],
        cwd=checkout,
        check=False,
    )
    if reachable.returncode != 0:
        raise PipelineError("Verified merge commit is not reachable from the configured base branch")


def _verify_skill_tree(source: Path, manifest: dict[str, Any], skill_path: str) -> dict[str, str]:
    _verify_manifest(manifest)
    relative_skill = validate_relative_path(skill_path).as_posix()
    actual = _tree_hashes(source)
    prefix = f"{relative_skill}/"
    selected = [entry for entry in manifest.get("files", []) if str(entry.get("path", "")).startswith(prefix)]
    if not selected:
        raise PipelineError("Candidate manifest contains no files for the merged skill subtree")
    expected = {str(entry["path"])[len(prefix) :]: entry["sha256"] for entry in selected}
    if actual != dict(sorted(expected.items())):
        missing = sorted(set(expected) - set(actual))
        extra = sorted(set(actual) - set(expected))
        changed = sorted(path for path in set(actual) & set(expected) if actual[path] != expected[path])
        raise PipelineError(
            f"Merged skill subtree differs from candidate manifest; missing={missing}, extra={extra}, changed={changed}"
        )
    for entry in selected:
        candidate = source / str(entry["path"])[len(prefix) :]
        if candidate.stat().st_size != entry["size"]:
            raise PipelineError(f"Merged candidate size differs from manifest: {entry['path']}")
    return actual


def verify_merged_candidate(merged_checkout: Path, manifest: dict[str, Any], skill_path: str) -> dict[str, str]:
    relative_skill = validate_relative_path(skill_path).as_posix()
    source = merged_checkout / relative_skill
    if not is_within(source, merged_checkout):
        raise PipelineError("Merged candidate path escapes immutable checkout")
    verify_promoted_manifest(merged_checkout, manifest)
    return _verify_skill_tree(source, manifest, skill_path)


def verify_installed_candidate(installed_skill: Path, manifest: dict[str, Any], skill_path: str) -> dict[str, str]:
    if installed_skill.is_symlink() or not installed_skill.is_dir():
        raise PipelineError("Installed skill tree is missing or unsafe")
    return _verify_skill_tree(installed_skill, manifest, skill_path)


def _copy_skill_tree(source: Path, destination: Path) -> dict[str, str]:
    if not source.is_dir() or source.is_symlink():
        raise PipelineError(f"Merged skill tree is missing or unsafe: {source}")
    hashes: dict[str, str] = {}
    for path in regular_files(source.parent, source.name, ["**/__pycache__/**", "**/*.pyc"]):
        relative = path.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        hashes[relative.as_posix()] = sha256_file(path)
    if "SKILL.md" not in hashes:
        raise PipelineError("Merged skill tree lacks SKILL.md")
    return hashes


def _installation_source_mode(config: dict[str, Any]) -> str:
    installation = config["installation"]
    configured = installation.get("source_mode")
    if configured is None and installation.get("installer_script"):
        configured = "installer"
    if configured not in {"installer", "local-test"}:
        raise PipelineError("Installation source_mode must be installer or explicit local-test")
    return str(configured)


def _clear_installer_workspace(skills_root: Path, installer_root: Path) -> None:
    if not installer_root.exists():
        return
    _assert_safe_descendant(skills_root, installer_root, allow_missing_leaf=False)
    if installer_root.is_symlink() or not installer_root.is_dir():
        raise PipelineError("Installer workspace is not a safe managed directory")
    shutil.rmtree(installer_root)
    _fsync_directory(skills_root)


def _stage_install_source(
    source: Path,
    staging: Path,
    installer_root: Path,
    merge_commit: str,
    expected_hashes: dict[str, str],
    run_dir: Path,
    config: dict[str, Any],
) -> None:
    """Stage either an explicit test copy or an exact-ref skill-installer download."""
    skills_root = staging.parent
    mode = _installation_source_mode(config)
    if staging.exists():
        if _path_hashes(staging) != expected_hashes:
            raise PipelineError("Existing staging tree differs from immutable candidate")
        _clear_installer_workspace(skills_root, installer_root)
        return
    if mode == "local-test":
        _copy_skill_tree(source, staging)
        return

    installation = config["installation"]
    promotion = config.get("promotion", {})
    repository_slug = str(promotion.get("repository_slug", ""))
    skill_path = str(config.get("candidate", {}).get("skill_path", ""))
    skill_name = str(installation.get("skill_name", ""))
    if not repository_slug or not skill_path or not skill_name:
        raise PipelineError("Production installer lacks repository, skill path, or skill name")

    _clear_installer_workspace(skills_root, installer_root)
    installer_binding = verify_lifecycle_executable_binding(run_dir, config, "installer")
    command = [
        installer_binding["argv"][0],
        installer_binding["argv"][1],
        "--repo",
        repository_slug,
        "--path",
        skill_path,
        "--ref",
        merge_commit,
        "--dest",
        str(installer_root),
        "--name",
        skill_name,
    ]
    try:
        installer_env_allowlist = tuple(installation.get("installer_env_allowlist", ()))
        run_command(
            command,
            env={key: os.environ[key] for key in installer_env_allowlist if key in os.environ},
            inherit_env=False,
        )
        downloaded = installer_root / skill_name
        if installer_root.is_symlink() or not installer_root.is_dir():
            raise PipelineError("Skill-installer did not create a safe isolated destination")
        entries = sorted(path.name for path in installer_root.iterdir())
        if entries != [skill_name] or downloaded.is_symlink() or not downloaded.is_dir():
            raise PipelineError("Skill-installer produced an unexpected destination layout")
        downloaded_hashes = _tree_hashes(downloaded)
        if downloaded_hashes != expected_hashes:
            raise PipelineError("Skill-installer download differs from the approved merged checkout")
        os.replace(downloaded, staging)
        installer_root.rmdir()
        _fsync_directory(skills_root)
    except Exception:
        _clear_installer_workspace(skills_root, installer_root)
        raise


def run_canary(
    installed_skill: Path,
    run_dir: Path,
    config: dict[str, Any],
    *,
    execution_authorization: dict[str, Any] | None = None,
    execution_authorization_sha256: str | None = None,
) -> dict[str, Any]:
    if execution_authorization is None or not execution_authorization_sha256:
        raise PipelineError("Fresh provider-backed canary lacks signed execution authorization")
    skill_file = installed_skill / "SKILL.md"
    if not skill_file.is_file() or skill_file.is_symlink():
        raise PipelineError("Installed skill lacks a safe SKILL.md")
    skill_text = skill_file.read_text(encoding="utf-8")
    if not skill_text.startswith("---\n") or "\nname: explore-approaches\n" not in skill_text or "\ndescription:" not in skill_text:
        raise PipelineError("Installed skill frontmatter is invalid")
    validator_binding = verify_lifecycle_executable_binding(run_dir, config, "validator")
    validation = run_command(
        [str(part).replace("{skill}", str(installed_skill)) for part in validator_binding["argv"]],
        check=False,
        env={
            key: os.environ[key]
            for key in tuple(config["installation"].get("validator_env_allowlist", ()))
            if key in os.environ
        },
        inherit_env=False,
    )
    if validation.returncode != 0:
        raise PipelineError(f"Installed skill failed static validation: {validation.stderr or validation.stdout}")
    request = {
        "schema_version": "1.0",
        "adapter_kind": "canary",
        "installed_skill": str(installed_skill),
        "request": "Recommend approaches for a reversible workspace decision; do not implement any option.",
    }
    if execution_authorization is not None:
        request["plan_sha256"] = execution_authorization["run"]["plan_sha256"]
        request["execution_authority"] = {
            "authorization_sha256": execution_authorization_sha256,
            "max_billed_tokens": execution_authorization["authority"]["max_billed_tokens_per_call"],
        }
    canary_binding = verify_lifecycle_executable_binding(run_dir, config, "canary")
    result = invoke_adapter(
        canary_binding["argv"],
        request,
        run_dir / "canary-attempts",
        timeout_seconds=float(config["evaluation"]["timeout_ms"]) / 1000,
        max_transient_retries=0,
        max_output_bytes=int(config["evaluation"].get("max_output_bytes", 1_000_000)),
        env_allowlist=tuple(config["evaluation"].get("adapter_env_allowlist", ("PATH", "TMPDIR", "LANG", "LC_ALL"))),
        execution_authorization=execution_authorization,
        execution_authorization_sha256=execution_authorization_sha256,
        execution_run_dir=run_dir if execution_authorization is not None else None,
    )
    if result["status"] != "completed" or result["response"].get("output", {}).get("passed") is not True:
        raise PipelineError("Fresh-process canary did not explicitly pass")
    return result


def _write_install_intent(path: Path, intent: dict[str, Any], phase: str) -> dict[str, Any]:
    updated = {key: value for key, value in intent.items() if key != "record_sha256"}
    updated["phase"] = phase
    updated["updated_at"] = iso_now()
    sealed = seal_record(updated)
    _durable_write_json(path, sealed)
    return sealed


def _path_hashes(path: Path) -> dict[str, str] | None:
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_dir():
        raise PipelineError(f"Unsafe managed install path: {path}")
    return _tree_hashes(path)


def _path_present(path: Path) -> bool:
    """Treat broken symlinks as present without following them."""

    return path.exists() or path.is_symlink()


def _best_effort_path_evidence(path: Path) -> tuple[dict[str, str] | None, str]:
    """Describe a quarantined entry without allowing malformed content to block rollback."""

    if not _path_present(path):
        return None, "absent"
    try:
        hashes = _path_hashes(path)
    except Exception as exc:
        return None, f"unavailable ({type(exc).__name__}: {exc})"
    if hashes is None:
        return None, "absent"
    return hashes, f"regular-tree sha256={sha256_json(hashes)} files={len(hashes)}"


def validate_installation_receipt(
    run_dir: Path,
    *,
    expected_merge_commit: str,
    expected_destination: Path,
) -> dict[str, Any]:
    receipt = load_immutable_record(run_dir / "installation-record.json", status="installed")
    if receipt.get("merge_commit") != expected_merge_commit or receipt.get("destination") != str(expected_destination):
        raise PipelineError("Installation receipt targets another artifact or destination")
    intent = load_immutable_record(run_dir / "install-intent.json")
    if intent.get("phase") != "completed" or receipt.get("intent_sha256") != intent.get("record_sha256"):
        raise PipelineError("Installation receipt is not bound to a completed install intent")
    actual = _path_hashes(expected_destination)
    if actual != receipt.get("file_hashes") or actual != intent.get("candidate_file_hashes"):
        raise PipelineError("Installed tree differs from the receipt and install intent")
    canary_record = load_immutable_record(run_dir / "canary-record.json", status="passed")
    if receipt.get("canary_record_sha256") != canary_record.get("record_sha256"):
        raise PipelineError("Installation receipt is not bound to the canary record")
    if canary_record.get("merge_commit") != expected_merge_commit:
        raise PipelineError("Canary record targets another merge commit")
    return receipt


def atomic_install(
    merged_checkout: Path,
    merge_commit: str,
    run_dir: Path,
    config: dict[str, Any],
    *,
    canary: Callable[[Path, Path, dict[str, Any]], dict[str, Any]] = run_canary,
) -> dict[str, Any]:
    installation = config["installation"]
    source_mode = _installation_source_mode(config)
    installer_script = str(Path(str(installation.get("installer_script", ""))).expanduser()) if source_mode == "installer" else None
    if source_mode == "installer":
        helper = Path(str(installer_script))
        if not helper.is_file() or helper.is_symlink():
            raise PipelineError("Configured production skill-installer helper is missing or unsafe")
    skills_root = Path(installation["skills_root"]).expanduser()
    skill_name = installation["skill_name"]
    destination = skills_root / skill_name
    source = merged_checkout / config["candidate"]["skill_path"]
    skills_root.mkdir(parents=True, exist_ok=True)
    backup_root = Path(installation["backup_directory"]).expanduser()
    quarantine_root = Path(installation["quarantine_directory"]).expanduser()
    backup_root.mkdir(parents=True, exist_ok=True)
    quarantine_root.mkdir(parents=True, exist_ok=True)
    ensure_private_directory(run_dir, create=True, normalize=not run_dir.exists())
    if run_dir.is_symlink() or skills_root.is_symlink() or backup_root.is_symlink() or quarantine_root.is_symlink():
        raise PipelineError("Install control directories may not be symlinks")
    if skills_root.stat().st_dev != backup_root.stat().st_dev or skills_root.stat().st_dev != quarantine_root.stat().st_dev:
        raise PipelineError("Atomic install backup and quarantine must share the skills-root filesystem")
    _assert_safe_descendant(skills_root, destination)
    hashes = _tree_hashes(source)
    if "SKILL.md" not in hashes:
        raise PipelineError("Merged skill tree lacks SKILL.md")
    transaction_id = sha256_json(
        {
            "merge_commit": merge_commit,
            "destination": str(destination),
            "candidate_file_hashes": hashes,
            "source_mode": source_mode,
            "installer_script": installer_script,
        }
    )[:32]
    staging = skills_root / f".{skill_name}.staging-{transaction_id}"
    installer_root = skills_root / f".{skill_name}.installer-{transaction_id}"
    backup = backup_root / f"{skill_name}-{transaction_id}"
    quarantine = quarantine_root / f"{skill_name}-{transaction_id}"
    _assert_safe_descendant(skills_root, staging)
    _assert_safe_descendant(skills_root, installer_root)
    _assert_safe_descendant(backup_root, backup)
    _assert_safe_descendant(quarantine_root, quarantine)
    intent_path = run_dir / "install-intent.json"

    with installation_lock(skills_root, skill_name):
        if intent_path.is_file() and not intent_path.is_symlink():
            intent = load_immutable_record(intent_path)
            expected = {
                "transaction_id": transaction_id,
                "merge_commit": merge_commit,
                "destination": str(destination),
                "staging": str(staging),
                "backup": str(backup),
                "quarantine": str(quarantine),
                "candidate_file_hashes": hashes,
            }
            if any(intent.get(key) != value for key, value in expected.items()):
                raise PipelineError("Existing install intent targets different immutable inputs")
        else:
            if intent_path.exists():
                raise PipelineError("Install intent path is not a regular file")
            previous_hashes = _path_hashes(destination)
            if staging.exists() or installer_root.exists() or backup.exists() or quarantine.exists():
                raise PipelineError("Managed transaction paths exist without a durable install intent")
            intent = seal_record(
                {
                    "schema_version": "2.0",
                    "transaction_id": transaction_id,
                    "created_at": iso_now(),
                    "updated_at": iso_now(),
                    "merge_commit": merge_commit,
                    "destination": str(destination),
                    "staging": str(staging),
                    "backup": str(backup),
                    "quarantine": str(quarantine),
                    "previous_existed": previous_hashes is not None,
                    "previous_file_hashes": previous_hashes or {},
                    "candidate_file_hashes": hashes,
                    "phase": "preparing",
                }
            )
            _durable_write_json(intent_path, intent)
            _stage_install_source(
                source,
                staging,
                installer_root,
                merge_commit,
                hashes,
                run_dir,
                config,
            )
            if _path_hashes(staging) != hashes:
                raise PipelineError("Staged skill differs from immutable merged source")
            intent = _write_install_intent(intent_path, intent, "staged")

        previous_existed = bool(intent["previous_existed"])
        previous_hashes = intent["previous_file_hashes"]
        if intent.get("phase") == "rolled-back" or _path_present(quarantine):
            _, quarantine_evidence = _best_effort_path_evidence(quarantine)
            destination_hashes = _path_hashes(destination)
            backup_hashes = _path_hashes(backup)
            if previous_existed:
                if destination_hashes == previous_hashes and backup_hashes is None:
                    pass
                elif destination_hashes is None and backup_hashes == previous_hashes:
                    os.replace(backup, destination)
                    _fsync_directory(backup_root)
                    _fsync_directory(skills_root)
                else:
                    raise PipelineError("Cannot reconcile an interrupted rollback to the previous installation")
            elif destination_hashes is not None:
                raise PipelineError("Interrupted rollback left an unexpected destination")
            if intent.get("phase") != "rolled-back":
                intent = _write_install_intent(intent_path, intent, "rolled-back")
            rollback_path = run_dir / "rollback-record.json"
            if rollback_path.is_file() and not rollback_path.is_symlink():
                recovered = load_immutable_record(rollback_path, status="rolled-back")
                if recovered.get("transaction_id") != transaction_id or recovered.get("intent_sha256") != intent["record_sha256"]:
                    raise PipelineError("Rollback record is not bound to the recovered install intent")
            elif rollback_path.exists():
                raise PipelineError("Rollback record path is unsafe")
            else:
                recovered = seal_record(
                    {
                        "schema_version": "2.0",
                        "rolled_back_at": iso_now(),
                        "transaction_id": transaction_id,
                        "intent_sha256": intent["record_sha256"],
                        "merge_commit": merge_commit,
                        "destination": str(destination),
                        "restored_previous": previous_existed,
                        "quarantine": str(quarantine) if _path_present(quarantine) else None,
                        "reason": (
                            "Recovered an interrupted rollback from durable intent and filesystem hashes; "
                            f"quarantine evidence: {quarantine_evidence}"
                        ),
                        "status": "rolled-back",
                    }
                )
                _durable_write_json(rollback_path, recovered)
            raise PipelineError("Install transaction was rolled back; start a new governed run")
        try:
            destination_hashes = _path_hashes(destination)
            backup_hashes = _path_hashes(backup)
            staging_hashes = _path_hashes(staging)
            candidate_active = destination_hashes == hashes
            if not candidate_active:
                if staging_hashes != hashes:
                    if staging.exists():
                        shutil.rmtree(staging)
                    _stage_install_source(source, staging, installer_root, merge_commit, hashes, run_dir, config)
                    staging_hashes = _path_hashes(staging)
                if staging_hashes != hashes:
                    raise PipelineError("Staging tree differs from immutable candidate")
                if previous_existed:
                    if backup_hashes is None:
                        if destination_hashes != previous_hashes:
                            raise PipelineError("Cannot reconcile previous installation before backup")
                        intent = _write_install_intent(intent_path, intent, "backup-pending")
                        os.replace(destination, backup)
                        _fsync_directory(skills_root)
                        _fsync_directory(backup_root)
                        backup_hashes = _path_hashes(backup)
                    if backup_hashes != previous_hashes:
                        raise PipelineError("Backup differs from the pre-install tree recorded in the intent")
                elif destination_hashes is not None:
                    raise PipelineError("Unexpected destination appeared during a new installation")

                intent = _write_install_intent(intent_path, intent, "activation-pending")
                os.replace(staging, destination)
                _fsync_directory(skills_root)
                if _path_hashes(destination) != hashes:
                    raise PipelineError("Activated destination differs from immutable candidate")

            intent = _write_install_intent(intent_path, intent, "canary-pending")
            canary_result = canary(destination, run_dir, config)
            if _path_hashes(destination) != hashes:
                raise PipelineError("Installed tree changed while the canary ran")
        except Exception as exc:
            try:
                destination_present = _path_present(destination)
                quarantined_hashes: dict[str, str] | None = None
                quarantine_evidence = "destination absent"
                if destination_present:
                    if _path_present(quarantine):
                        raise PipelineError(
                            "Cannot quarantine failed active tree: transaction quarantine already exists"
                        )
                    # Recheck only the managed parents. The leaf may now contain a
                    # symlink or another malformed entry created by the failed canary;
                    # os.replace moves that entry itself and never follows it.
                    _assert_safe_descendant(skills_root, destination.parent, allow_missing_leaf=False)
                    _assert_safe_descendant(quarantine_root, quarantine.parent, allow_missing_leaf=False)
                    os.replace(destination, quarantine)
                    _fsync_directory(skills_root)
                    _fsync_directory(quarantine_root)
                    if _path_present(destination) or not _path_present(quarantine):
                        raise PipelineError("Failed active tree was not durably quarantined")
                    quarantined_hashes, quarantine_evidence = _best_effort_path_evidence(quarantine)

                if previous_existed:
                    backup_hashes = _path_hashes(backup)
                    if backup_hashes == previous_hashes:
                        os.replace(backup, destination)
                        _fsync_directory(backup_root)
                        _fsync_directory(skills_root)
                    elif backup_hashes is None and quarantined_hashes == previous_hashes:
                        os.replace(quarantine, destination)
                        _fsync_directory(quarantine_root)
                        _fsync_directory(skills_root)
                        quarantine_evidence = (
                            f"restored recorded previous tree from quarantine; {quarantine_evidence}"
                        )
                    else:
                        raise PipelineError(
                            "Cannot restore previous installation from the recorded backup"
                        )
                    if _path_hashes(destination) != previous_hashes or _path_present(backup):
                        raise PipelineError("Restored installation differs from the pre-install tree")
                elif _path_present(destination):
                    raise PipelineError("Failed installation left an unexpected active destination")

                if destination_present and quarantined_hashes != previous_hashes and not _path_present(quarantine):
                    raise PipelineError("Failed active tree disappeared instead of remaining quarantined")

                intent = _write_install_intent(intent_path, intent, "rolled-back")
                rollback = seal_record(
                    {
                        "schema_version": "2.0",
                        "rolled_back_at": iso_now(),
                        "transaction_id": transaction_id,
                        "intent_sha256": intent["record_sha256"],
                        "merge_commit": merge_commit,
                        "destination": str(destination),
                        "restored_previous": previous_existed,
                        "quarantine": str(quarantine) if _path_present(quarantine) else None,
                        "reason": f"{exc}; quarantined tree evidence: {quarantine_evidence}",
                        "status": "rolled-back",
                    }
                )
                _durable_write_json(run_dir / "rollback-record.json", rollback)
            except Exception as rollback_exc:
                raise PipelineError(
                    f"Canary failed and rollback could not safely restore root state: {rollback_exc}"
                ) from exc
            raise PipelineError(f"Canary failed; installation rolled back: {exc}") from exc
        finally:
            _clear_installer_workspace(skills_root, installer_root)
            if staging.exists():
                if _path_hashes(staging) != hashes:
                    raise PipelineError("Refusing to remove an unrecognized staging tree")
                shutil.rmtree(staging)

        canary_record = seal_record(
            {
                "schema_version": "2.0",
                "completed_at": iso_now(),
                "transaction_id": transaction_id,
                "merge_commit": merge_commit,
                "status": "passed",
                "result": canary_result,
            }
        )
        _durable_write_json(run_dir / "canary-record.json", canary_record)
        intent = _write_install_intent(intent_path, intent, "completed")
        receipt = seal_record(
            {
                "schema_version": "2.0",
                "installed_at": iso_now(),
                "transaction_id": transaction_id,
                "intent_sha256": intent["record_sha256"],
                "canary_record_sha256": canary_record["record_sha256"],
                "merge_commit": merge_commit,
                "destination": str(destination),
                "file_hashes": hashes,
                "backup": str(backup) if backup.exists() else None,
                "status": "installed",
            }
        )
        _durable_write_json(run_dir / "installation-record.json", receipt)
        return validate_installation_receipt(
            run_dir,
            expected_merge_commit=merge_commit,
            expected_destination=destination,
        )


def _write_active_rollback_intent(
    path: Path,
    intent: dict[str, Any],
    phase: str,
) -> dict[str, Any]:
    updated = {key: value for key, value in intent.items() if key != "record_sha256"}
    updated["phase"] = phase
    updated["updated_at"] = iso_now()
    sealed = seal_record(updated)
    _durable_write_json(path, sealed)
    return sealed


def run_active_rollback_canary(
    destination: Path,
    expected_hashes: dict[str, str],
    run_dir: Path,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Validate the restored root state in a fresh, credential-minimized process."""

    actual = _path_hashes(destination)
    if actual != (expected_hashes or None):
        raise PipelineError("Rollback canary observed a root state different from the recorded predecessor")
    if not expected_hashes:
        return {"status": "passed", "restored_previous": False, "file_hashes": {}}
    validator_binding = verify_lifecycle_executable_binding(run_dir, config, "validator")
    allowlist = tuple(config["installation"].get("validator_env_allowlist", ()))
    validation = run_command(
        [str(part).replace("{skill}", str(destination)) for part in validator_binding["argv"]],
        check=False,
        env={key: os.environ[key] for key in allowlist if key in os.environ},
        inherit_env=False,
    )
    if validation.returncode != 0:
        raise PipelineError(
            f"Restored installation failed the rollback canary: {validation.stderr or validation.stdout}"
        )
    if _path_hashes(destination) != expected_hashes:
        raise PipelineError("Restored installation changed while the rollback canary ran")
    return {"status": "passed", "restored_previous": True, "file_hashes": expected_hashes}


def rollback_active_install(
    run_dir: Path,
    config: dict[str, Any],
    *,
    operator: str,
    reason: str,
    rollback_canary: Callable[[Path, dict[str, str], Path, dict[str, Any]], dict[str, Any]] = run_active_rollback_canary,
    fault_injector: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Quarantine an active candidate and atomically restore its recorded predecessor."""

    roles = role_bindings(config, require_resolved=True)
    if operator != roles["promotion_owner"]:
        raise PipelineError("Active rollback operator does not match the frozen promotion owner")
    if not isinstance(reason, str) or len(reason.strip()) < 8:
        raise PipelineError("Active rollback requires a concrete operator reason")
    reason = reason.strip()

    installation = config["installation"]
    skills_root = Path(installation["skills_root"]).expanduser()
    skill_name = str(installation["skill_name"])
    destination = skills_root / skill_name
    backup_root = Path(installation["backup_directory"]).expanduser()
    quarantine_root = Path(installation["quarantine_directory"]).expanduser()
    ensure_private_directory(run_dir)
    if any(path.is_symlink() for path in (skills_root, backup_root, quarantine_root)):
        raise PipelineError("Active rollback control directories may not be symlinks")
    if any(not path.is_dir() for path in (skills_root, backup_root, quarantine_root)):
        raise PipelineError("Active rollback control directories are missing")
    if (
        skills_root.stat().st_dev != backup_root.stat().st_dev
        or skills_root.stat().st_dev != quarantine_root.stat().st_dev
    ):
        raise PipelineError("Active rollback backup and quarantine must share the skills-root filesystem")
    _assert_safe_descendant(skills_root, destination)

    installation_record_path = run_dir / "installation-record.json"
    install_intent_path = run_dir / "install-intent.json"
    installation_record = load_immutable_record(installation_record_path, status="installed")
    install_intent = load_immutable_record(install_intent_path)
    if install_intent.get("phase") != "completed":
        raise PipelineError("Active rollback requires a completed installation intent")
    if installation_record.get("intent_sha256") != install_intent.get("record_sha256"):
        raise PipelineError("Active rollback records do not share the completed installation intent")
    if installation_record.get("destination") != str(destination):
        raise PipelineError("Active rollback installation receipt targets another destination")

    candidate_hashes = installation_record.get("file_hashes")
    previous_hashes = install_intent.get("previous_file_hashes") or {}
    previous_existed = bool(install_intent.get("previous_existed"))
    if not isinstance(candidate_hashes, dict) or not isinstance(previous_hashes, dict):
        raise PipelineError("Active rollback receipt lacks sealed filesystem hashes")
    backup = Path(str(install_intent.get("backup", "")))
    _assert_safe_descendant(backup_root, backup)
    transaction_id = sha256_json(
        {
            "installation_record_sha256": installation_record["record_sha256"],
            "install_intent_sha256": install_intent["record_sha256"],
            "operator": operator,
            "reason": reason,
            "candidate_file_hashes": candidate_hashes,
            "previous_file_hashes": previous_hashes,
        }
    )[:32]
    quarantine = quarantine_root / f"{skill_name}-active-{transaction_id}"
    _assert_safe_descendant(quarantine_root, quarantine)
    intent_path = run_dir / "active-rollback-intent.json"
    record_path = run_dir / "active-rollback-record.json"

    with installation_lock(skills_root, skill_name):
        if record_path.is_file() and not record_path.is_symlink():
            record = load_immutable_record(record_path, status="rolled-back")
            if (
                record.get("transaction_id") != transaction_id
                or record.get("operator") != operator
                or record.get("reason") != reason
                or record.get("quarantined_file_hashes") != candidate_hashes
                or record.get("restored_file_hashes") != previous_hashes
            ):
                raise PipelineError("Completed active rollback record targets different sealed inputs")
            if _path_hashes(destination) != (previous_hashes if previous_existed else None):
                raise PipelineError("Root state changed after the completed active rollback")
            if _path_hashes(quarantine) != candidate_hashes:
                raise PipelineError("Quarantined active tree changed after rollback")
            return record

        expected_intent = {
            "transaction_id": transaction_id,
            "installation_record_sha256": installation_record["record_sha256"],
            "install_intent_sha256": install_intent["record_sha256"],
            "merge_commit": installation_record["merge_commit"],
            "destination": str(destination),
            "backup": str(backup),
            "quarantine": str(quarantine),
            "operator": operator,
            "reason": reason,
            "candidate_file_hashes": candidate_hashes,
            "previous_existed": previous_existed,
            "previous_file_hashes": previous_hashes,
        }
        if intent_path.is_file() and not intent_path.is_symlink():
            intent = load_immutable_record(intent_path)
            if any(intent.get(key) != value for key, value in expected_intent.items()):
                raise PipelineError("Existing active rollback intent targets different sealed inputs")
        else:
            if intent_path.exists() or intent_path.is_symlink():
                raise PipelineError("Active rollback intent path is unsafe")
            if _path_hashes(destination) != candidate_hashes:
                raise PipelineError("Active installation differs from its sealed receipt")
            if _path_present(quarantine):
                raise PipelineError("Active rollback quarantine exists without a durable intent")
            if previous_existed and _path_hashes(backup) != previous_hashes:
                raise PipelineError("Recorded predecessor backup is missing or changed")
            intent = seal_record(
                {
                    "schema_version": "1.0",
                    "created_at": iso_now(),
                    "updated_at": iso_now(),
                    **expected_intent,
                    "phase": "prepared",
                }
            )
            _durable_write_json(intent_path, intent)
        if fault_injector is not None:
            fault_injector("intent-written")

        destination_hashes = _path_hashes(destination)
        quarantine_hashes = _path_hashes(quarantine)
        predecessor_already_restored = (
            previous_existed
            and destination_hashes == previous_hashes
            and quarantine_hashes == candidate_hashes
        )
        if predecessor_already_restored and _path_present(backup):
            raise PipelineError("Restored predecessor still has an unexpected backup tree")
        if quarantine_hashes is None:
            if destination_hashes != candidate_hashes:
                raise PipelineError("Cannot reconcile active tree before quarantine")
            intent = _write_active_rollback_intent(intent_path, intent, "quarantine-pending")
            os.replace(destination, quarantine)
            _fsync_directory(skills_root)
            _fsync_directory(quarantine_root)
            destination_hashes = _path_hashes(destination)
            quarantine_hashes = _path_hashes(quarantine)
        if (
            not predecessor_already_restored
            and (destination_hashes is not None or quarantine_hashes != candidate_hashes)
        ):
            raise PipelineError("Active tree was not atomically quarantined with its recorded hashes")
        if not predecessor_already_restored:
            intent = _write_active_rollback_intent(intent_path, intent, "candidate-quarantined")
            if fault_injector is not None:
                fault_injector("candidate-quarantined")

        if previous_existed:
            if not predecessor_already_restored:
                destination_hashes = _path_hashes(destination)
                backup_hashes = _path_hashes(backup)
                if destination_hashes is None:
                    if backup_hashes != previous_hashes:
                        raise PipelineError("Cannot restore the sealed predecessor backup")
                    intent = _write_active_rollback_intent(intent_path, intent, "restore-pending")
                    os.replace(backup, destination)
                    _fsync_directory(backup_root)
                    _fsync_directory(skills_root)
                elif destination_hashes != previous_hashes or backup_hashes is not None:
                    raise PipelineError("Cannot reconcile the predecessor during active rollback recovery")
                if _path_hashes(destination) != previous_hashes or _path_present(backup):
                    raise PipelineError("Restored root differs from the sealed predecessor")
        elif _path_present(destination):
            raise PipelineError("Rollback of a new install left an unexpected active destination")
        intent = _write_active_rollback_intent(intent_path, intent, "previous-restored")
        if fault_injector is not None:
            fault_injector("previous-restored")

        canary_path = run_dir / "active-rollback-canary-record.json"
        if canary_path.is_file() and not canary_path.is_symlink():
            canary_record = load_immutable_record(canary_path, status="passed")
            if canary_record.get("transaction_id") != transaction_id:
                raise PipelineError("Rollback canary record targets another transaction")
        else:
            if canary_path.exists() or canary_path.is_symlink():
                raise PipelineError("Rollback canary record path is unsafe")
            intent = _write_active_rollback_intent(intent_path, intent, "rollback-canary-pending")
            canary_result = rollback_canary(destination, previous_hashes, run_dir, config)
            if canary_result.get("status") != "passed":
                raise PipelineError("Rollback canary did not explicitly pass")
            canary_record = seal_record(
                {
                    "schema_version": "1.0",
                    "completed_at": iso_now(),
                    "transaction_id": transaction_id,
                    "status": "passed",
                    "result": canary_result,
                }
            )
            _durable_write_json(canary_path, canary_record)

        if _path_hashes(destination) != (previous_hashes if previous_existed else None):
            raise PipelineError("Root state changed after the rollback canary")
        if _path_hashes(quarantine) != candidate_hashes:
            raise PipelineError("Quarantined candidate changed during active rollback")
        intent = _write_active_rollback_intent(intent_path, intent, "completed")
        record = seal_record(
            {
                "schema_version": "1.0",
                "rolled_back_at": iso_now(),
                "transaction_id": transaction_id,
                "active_rollback_intent_sha256": intent["record_sha256"],
                "installation_record_sha256": installation_record["record_sha256"],
                "install_intent_sha256": install_intent["record_sha256"],
                "rollback_canary_record_sha256": canary_record["record_sha256"],
                "merge_commit": installation_record["merge_commit"],
                "destination": str(destination),
                "quarantine": str(quarantine),
                "operator": operator,
                "reason": reason,
                "quarantined_file_hashes": candidate_hashes,
                "restored_previous": previous_existed,
                "restored_file_hashes": previous_hashes,
                "status": "rolled-back",
            }
        )
        _durable_write_json(record_path, record)
        return record


def rehearse_rollback(run_dir: Path) -> dict[str, Any]:
    ensure_private_directory(run_dir, create=True, normalize=not run_dir.exists())
    with tempfile.TemporaryDirectory(prefix="explore-rollback-") as temporary:
        root = Path(temporary)
        checkout = root / "checkout" / "skills" / "explore-approaches"
        checkout.mkdir(parents=True)
        (checkout / "SKILL.md").write_text("candidate\n", encoding="utf-8")
        skills_root = root / "skills-root"
        current = skills_root / "explore-approaches"
        current.mkdir(parents=True)
        (current / "SKILL.md").write_text("previous\n", encoding="utf-8")
        config = {
            "candidate": {"skill_path": "skills/explore-approaches"},
            "installation": {
                "source_mode": "local-test",
                "skills_root": str(skills_root),
                "skill_name": "explore-approaches",
                "backup_directory": str(root / "backups"),
                "quarantine_directory": str(root / "quarantine"),
            },
        }

        def fail_canary(_skill: Path, _run: Path, _config: dict[str, Any]) -> dict[str, Any]:
            raise PipelineError("deliberate rollback rehearsal failure")

        failed_as_expected = False
        try:
            atomic_install(root / "checkout", "0" * 40, run_dir / "rehearsal-private", config, canary=fail_canary)
        except PipelineError:
            failed_as_expected = True
        restored = (current / "SKILL.md").read_text(encoding="utf-8") == "previous\n"
        if not failed_as_expected or not restored:
            raise PipelineError("Atomic rollback rehearsal failed")
    record = {
        "schema_version": "1.0",
        "rehearsed_at": iso_now(),
        "deliberate_canary_failure": True,
        "previous_install_restored": True,
        "result": "passed",
    }
    atomic_write_json(run_dir / "rollback-evidence.json", record)
    return record
