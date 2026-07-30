"""Signed, bounded authority for every provider-backed lifecycle call."""

from __future__ import annotations

import base64
import fcntl
import json
import os
import stat
import tempfile
import unicodedata
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .core import (
    PipelineError,
    canonical_json_bytes,
    ensure_private_directory,
    ensure_private_file,
    iso_now,
    load_json,
    parse_time,
    run_command,
    sha256_json,
    utc_now,
)


ROLE_FIELDS = (
    "candidate_author",
    "holdout_owner",
    "human_reviewer_adjudicator",
    "provider_execution_approver",
    "promotion_owner",
    "automation_actor",
    "pr_reviewer",
)

REQUIRED_STOP_CONDITIONS = {
    "authorization_expired",
    "call_budget_exhausted",
    "token_budget_exhausted",
    "adapter_permanent_error",
    "operator_cancelled",
}


def _canonical_identity(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def execution_authorization_payload(document: dict[str, Any]) -> bytes:
    return canonical_json_bytes({key: value for key, value in document.items() if key != "signature"})


def role_bindings(config: dict[str, Any], *, require_resolved: bool) -> dict[str, str]:
    roles = config.get("roles")
    if not isinstance(roles, dict) or set(roles) != set(ROLE_FIELDS):
        raise PipelineError("Pipeline role bindings do not match the frozen separation contract")
    normalized: dict[str, str] = {}
    for field in ROLE_FIELDS:
        value = roles.get(field)
        if not isinstance(value, str) or not value.strip():
            raise PipelineError(f"Pipeline role binding is missing: {field}")
        value = value.strip()
        if require_resolved and "REPLACE_WITH" in value:
            raise PipelineError(f"Pipeline role binding is unresolved: {field}")
        normalized[field] = value
    folded = [_canonical_identity(value) for value in normalized.values()]
    if len(set(folded)) != len(folded):
        raise PipelineError("Governed lifecycle roles must be assigned to unique identities")

    expected = {
        "holdout_owner": config.get("holdout_verification", {}).get("expected_identity"),
        "human_reviewer_adjudicator": config.get("human_review_verification", {}).get("expected_identity"),
        "provider_execution_approver": config.get("execution_verification", {}).get("expected_identity"),
        "promotion_owner": config.get("approval_verification", {}).get("expected_identity"),
        "automation_actor": config.get("promotion", {}).get("automation_actor"),
    }
    for field, configured in expected.items():
        if configured and _canonical_identity(str(configured)) != _canonical_identity(normalized[field]):
            raise PipelineError(f"Role binding for {field} differs from its enforcement configuration")
        if require_resolved and not configured:
            raise PipelineError(f"Enforcement identity is missing for role: {field}")
    reviewer_logins = config.get("promotion", {}).get("required_reviewer_logins", [])
    if not isinstance(reviewer_logins, list) or _canonical_identity(normalized["pr_reviewer"]) not in {
        _canonical_identity(str(value)) for value in reviewer_logins
    }:
        raise PipelineError("Frozen PR reviewer role is absent from the required reviewer allowlist")
    return normalized


def roles_sha256(config: dict[str, Any], *, require_resolved: bool = True) -> str:
    return sha256_json(role_bindings(config, require_resolved=require_resolved))


def build_execution_authorization_template(
    run_dir: Path,
    config: dict[str, Any],
    plan: dict[str, Any],
) -> dict[str, Any]:
    roles = role_bindings(config, require_resolved=True)
    limits = config.get("provider_execution_limits", {})
    return {
        "schema_version": "1.0",
        "authorization_id": f"EXEC-{uuid.uuid4().hex[:16]}",
        "decision": "execute-provider-calls",
        "authorized_by": roles["provider_execution_approver"],
        "authorized_at": "REPLACE_WITH_POST_FREEZE_RFC3339_TIME",
        "expires_at": "REPLACE_WITH_RFC3339_EXPIRY",
        "run": {
            "run_id": plan["run_id"],
            "plan_sha256": plan["plan_sha256"],
            "config_sha256": plan["config_sha256"],
            "candidate_manifest_sha256": plan["candidate_manifest_sha256"],
            "subject_runtime_sha256": plan["subject_runtime_sha256"],
            "lifecycle_executables_sha256": plan["lifecycle_executables_sha256"],
            "roles_sha256": roles_sha256(config),
        },
        "authority": {
            "max_subject_calls": int(limits.get("max_subject_calls", 0)),
            "max_grader_calls": int(limits.get("max_grader_calls", 0)),
            "max_canary_calls": int(limits.get("max_canary_calls", 0)),
            "max_total_calls": int(limits.get("max_total_calls", 0)),
            "max_transient_retries": int(limits.get("max_transient_retries", 0)),
            "max_billed_tokens_per_call": int(limits.get("max_billed_tokens_per_call", 0)),
            "max_total_billed_tokens": int(limits.get("max_total_billed_tokens", 0)),
            "stop_conditions": sorted(REQUIRED_STOP_CONDITIONS),
        },
        "signature": {
            "algorithm": "ssh-keygen-y",
            "identity": config["execution_verification"]["expected_identity"],
            "namespace": config["execution_verification"]["namespace"],
            "value": "REPLACE_WITH_BASE64_DETACHED_SSH_SIGNATURE",
        },
        "notes": "This authority is separate from promotion approval and is consumed conservatively before each provider call.",
    }


def verify_execution_signature(document: dict[str, Any], config: dict[str, Any]) -> None:
    settings = config.get("execution_verification", {})
    allowed_signers = Path(str(settings.get("allowed_signers_path", "")))
    expected_identity = str(settings.get("expected_identity", ""))
    namespace = str(settings.get("namespace", ""))
    signature = document.get("signature", {})
    if not expected_identity or not namespace or not allowed_signers.is_file() or allowed_signers.is_symlink():
        raise PipelineError("SSH execution-authorization verification is not fully configured")
    if signature.get("algorithm") != "ssh-keygen-y":
        raise PipelineError("Execution-authorization signature algorithm is unsupported")
    if signature.get("identity") != expected_identity or signature.get("namespace") != namespace:
        raise PipelineError("Execution-authorization signer identity or namespace does not match configuration")
    try:
        decoded = base64.b64decode(signature.get("value", ""), validate=True)
    except (TypeError, ValueError) as exc:
        raise PipelineError("Execution-authorization signature is not valid base64") from exc
    with tempfile.TemporaryDirectory(prefix="explore-execution-authorization-") as temporary:
        signature_path = Path(temporary) / "authorization.sig"
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
            input_text=execution_authorization_payload(document).decode("utf-8"),
            check=False,
        )
    if result.returncode != 0:
        raise PipelineError(f"SSH execution-authorization verification failed: {result.stderr.strip()}")


def validate_execution_authorization(
    document: dict[str, Any],
    config: dict[str, Any],
    plan: dict[str, Any],
    *,
    signature_verifier=verify_execution_signature,
) -> None:
    required = {
        "schema_version",
        "authorization_id",
        "decision",
        "authorized_by",
        "authorized_at",
        "expires_at",
        "run",
        "authority",
        "signature",
    }
    if set(document) - (required | {"notes"}) or not required.issubset(document):
        raise PipelineError("Execution authorization fields do not match the v1 contract")
    if document.get("schema_version") != "1.0" or document.get("decision") != "execute-provider-calls":
        raise PipelineError("Signed document does not authorize provider execution")
    roles = role_bindings(config, require_resolved=True)
    if document.get("authorized_by") != roles["provider_execution_approver"]:
        raise PipelineError("Execution authorization attribution does not match the frozen approver")
    try:
        authorized_at = parse_time(str(document.get("authorized_at")))
        expires_at = parse_time(str(document.get("expires_at")))
        frozen_at = parse_time(str(plan.get("frozen_at")))
    except (TypeError, ValueError) as exc:
        raise PipelineError("Execution authorization timestamps are invalid") from exc
    max_ttl = int(config.get("provider_execution_limits", {}).get("max_authorization_ttl_seconds", 0))
    now = utc_now()
    if authorized_at <= frozen_at or expires_at <= authorized_at or now >= expires_at:
        raise PipelineError("Execution authorization is pre-freeze, expired, or has an invalid time window")
    if (authorized_at - now).total_seconds() > 300:
        raise PipelineError("Execution authorization was issued too far in the future")
    if (
        max_ttl <= 0
        or (expires_at - authorized_at).total_seconds() > max_ttl
        or (expires_at - now).total_seconds() > max_ttl
    ):
        raise PipelineError("Execution authorization exceeds the configured maximum lifetime")

    expected_run = {
        "run_id": plan.get("run_id"),
        "plan_sha256": plan.get("plan_sha256"),
        "config_sha256": plan.get("config_sha256"),
        "candidate_manifest_sha256": plan.get("candidate_manifest_sha256"),
        "subject_runtime_sha256": plan.get("subject_runtime_sha256"),
        "lifecycle_executables_sha256": plan.get("lifecycle_executables_sha256"),
        "roles_sha256": roles_sha256(config),
    }
    if document.get("run") != expected_run:
        raise PipelineError("Execution authorization does not bind the frozen plan, runtime, roles, and candidate")

    authority = document.get("authority")
    caps = config.get("provider_execution_limits", {})
    integer_fields = (
        "max_subject_calls",
        "max_grader_calls",
        "max_canary_calls",
        "max_total_calls",
        "max_transient_retries",
        "max_billed_tokens_per_call",
        "max_total_billed_tokens",
    )
    if not isinstance(authority, dict) or set(authority) != set(integer_fields) | {"stop_conditions"}:
        raise PipelineError("Execution authority limits do not match the bounded v1 contract")
    for field in integer_fields:
        value = authority.get(field)
        cap = caps.get(field)
        minimum = 0 if field == "max_transient_retries" else 1
        if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
            raise PipelineError(f"Execution authority has an invalid {field}")
        if not isinstance(cap, int) or isinstance(cap, bool) or cap < minimum or value > cap:
            raise PipelineError(f"Execution authority exceeds the configured {field} cap")
    if authority["max_transient_retries"] > int(config["evaluation"]["max_transient_retries"]):
        raise PipelineError("Execution authority exceeds the frozen retry policy")
    if set(authority.get("stop_conditions", [])) != REQUIRED_STOP_CONDITIONS:
        raise PipelineError("Execution authority stop conditions are incomplete or over-broad")
    if authority["max_total_calls"] > sum(
        authority[field] for field in ("max_subject_calls", "max_grader_calls", "max_canary_calls")
    ):
        raise PipelineError("Execution authority total-call budget exceeds its scoped call budgets")
    if authority["max_total_billed_tokens"] < authority["max_billed_tokens_per_call"]:
        raise PipelineError("Execution authority total-token budget cannot fund one bounded call")
    signature_verifier(document, config)


@contextmanager
def _budget_lock(run_dir: Path) -> Iterator[None]:
    budget_dir = run_dir / "execution"
    ensure_private_directory(budget_dir, create=True, normalize=not budget_dir.exists())
    lock_path = budget_dir / ".budget.lock"
    descriptor = os.open(
        lock_path,
        os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        lock_stat = os.fstat(descriptor)
        if (
            not stat.S_ISREG(lock_stat.st_mode)
            or lock_stat.st_uid != os.geteuid()
            or lock_stat.st_nlink != 1
        ):
            raise PipelineError("Execution budget lock is not a private regular file")
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def reserve_provider_call(
    run_dir: Path,
    authorization: dict[str, Any],
    authorization_sha256: str,
    *,
    adapter_kind: str,
    plan_sha256: str,
    request_sha256: str,
) -> dict[str, Any]:
    if adapter_kind not in {"subject", "grader", "canary"}:
        raise PipelineError("Provider-call reservation has an unsupported adapter kind")
    if authorization.get("run", {}).get("plan_sha256") != plan_sha256:
        raise PipelineError("Provider-call reservation targets another frozen plan")
    if utc_now() >= parse_time(str(authorization.get("expires_at"))):
        raise PipelineError("Execution authorization expired before the provider call")
    stop_path = run_dir / "execution" / "STOP"
    if stop_path.exists() or stop_path.is_symlink():
        raise PipelineError("Provider execution was stopped by the operator kill switch")

    authority = authorization["authority"]
    with _budget_lock(run_dir):
        reservation_dir = run_dir / "execution" / "call-reservations"
        ensure_private_directory(reservation_dir, create=True, normalize=not reservation_dir.exists())
        reservations: list[dict[str, Any]] = []
        for path in sorted(reservation_dir.glob("*.json")):
            if path.is_symlink() or not path.is_file():
                raise PipelineError("Execution budget contains an unsafe reservation")
            ensure_private_file(path)
            value = load_json(path)
            body = {key: item for key, item in value.items() if key != "record_sha256"}
            if value.get("record_sha256") != sha256_json(body):
                raise PipelineError("Execution budget reservation hash mismatch")
            if value.get("execution_authorization_sha256") != authorization_sha256:
                raise PipelineError("Execution budget contains a reservation from another authorization")
            reservations.append(value)

        kind_field = f"max_{adapter_kind}_calls"
        kind_count = sum(1 for value in reservations if value.get("adapter_kind") == adapter_kind)
        total_count = len(reservations)
        per_call = int(authority["max_billed_tokens_per_call"])
        if kind_count >= int(authority[kind_field]) or total_count >= int(authority["max_total_calls"]):
            raise PipelineError("Execution authorization call budget is exhausted")
        if (total_count + 1) * per_call > int(authority["max_total_billed_tokens"]):
            raise PipelineError("Execution authorization token budget is exhausted")

        body = {
            "schema_version": "1.0",
            "reservation_id": f"CALL-{uuid.uuid4().hex}",
            "reserved_at": iso_now(),
            "execution_authorization_sha256": authorization_sha256,
            "adapter_kind": adapter_kind,
            "plan_sha256": plan_sha256,
            "request_sha256": request_sha256,
            "max_billed_tokens": per_call,
            "status": "reserved",
        }
        record = {**body, "record_sha256": sha256_json(body)}
        path = reservation_dir / f"{record['reservation_id']}.json"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(record, handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            directory_descriptor = os.open(reservation_dir, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return record


def verify_billed_token_telemetry(response: dict[str, Any], authorization: dict[str, Any]) -> None:
    telemetry = response.get("telemetry")
    if not isinstance(telemetry, dict):
        raise PipelineError("Authorized provider response lacks billed-token telemetry")
    input_tokens = telemetry.get("input_tokens")
    output_tokens = telemetry.get("output_tokens")
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in (input_tokens, output_tokens)):
        raise PipelineError("Authorized provider response has invalid billed-token telemetry")
    if input_tokens + output_tokens > int(authorization["authority"]["max_billed_tokens_per_call"]):
        raise PipelineError("Provider response exceeded the authorized per-call billed-token bound")
