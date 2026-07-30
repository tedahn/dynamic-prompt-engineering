#!/usr/bin/env python3
"""Drive the governed explore-approaches lifecycle to its next honest gate."""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

EVALUATION_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(EVALUATION_ROOT))

from automation.core import (  # noqa: E402
    PipelineError,
    assess_summary,
    atomic_write_json,
    build_candidate_manifest,
    load_config,
    load_json,
    sha256_file,
    sha256_json,
)
from automation.evaluation import (  # noqa: E402
    _verified_plan,
    build_blind_bundle,
    build_holdout_manifest_template,
    build_summary,
    freeze_plan,
    holdout_manifest_payload,
    run_provisional_grading,
    run_subjects,
    verify_frozen_holdout_signature,
)
from automation.event_store import EventStore  # noqa: E402
from automation.orchestrator import Lifecycle  # noqa: E402
from automation.promotion import (  # noqa: E402
    REQUIRED_PERMISSIONS,
    approval_payload,
    atomic_install,
    build_pr_record,
    build_release_record,
    checkout_immutable_merge,
    load_immutable_record,
    merge_reviewed_pr,
    prepare_clean_promotion,
    push_and_open_pr,
    rehearse_rollback,
    validate_approval,
    validate_installation_receipt,
    validate_prepared_promotion,
    validate_release_record,
    verify_installed_candidate,
    verify_merge_reachable,
    verify_merged_candidate,
    write_immutable_record,
)

DEFAULT_CONFIG = EVALUATION_ROOT / "config" / "pipeline-v1.json"


def _path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def _config(path: Path, run_dir: Path | None = None) -> dict[str, Any]:
    if run_dir is not None and (run_dir / "plan.json").is_file():
        frozen_path = run_dir / "frozen" / "config.json"
        if not frozen_path.is_file() or frozen_path.is_symlink():
            raise PipelineError("Frozen run is missing its immutable pipeline configuration")
        value = load_json(frozen_path)
        plan = load_json(run_dir / "plan.json")
        if plan.get("config_sha256") != sha256_json(value):
            raise PipelineError("Frozen pipeline configuration hash mismatch")
        configured = load_json(path)
        configured["repo_root"] = str(REPO_ROOT)
        if configured != value:
            raise PipelineError("Frozen pipeline configuration hash mismatch")
    else:
        value = load_config(path)
        value["repo_root"] = str(REPO_ROOT)
    for settings_name in ("holdout_verification", "approval_verification"):
        settings = value.get(settings_name, {})
        if settings.get("expected_identity"):
            for protected_root in (REPO_ROOT, run_dir):
                if protected_root is None:
                    continue
                try:
                    path.relative_to(protected_root)
                except ValueError:
                    pass
                else:
                    raise PipelineError("Signer trust configuration must remain outside repository and run data")
            signer_path = Path(str(settings.get("allowed_signers_path", "")))
            if (
                not signer_path.is_file()
                or signer_path.is_symlink()
                or signer_path.stat().st_uid != os.getuid()
                or signer_path.stat().st_mode & 0o022
            ):
                raise PipelineError(f"Unsafe operator-controlled signer trust file for {settings_name}")
            for protected_root in (REPO_ROOT, run_dir):
                if protected_root is None:
                    continue
                try:
                    signer_path.resolve().relative_to(protected_root.resolve())
                except ValueError:
                    pass
                else:
                    raise PipelineError("Allowed-signers trust file must remain outside repository and run data")
    return value


def _lifecycle(run_dir: Path) -> tuple[EventStore, Lifecycle]:
    store = EventStore(run_dir / "lifecycle.sqlite3")
    lifecycle = Lifecycle(store, "explore-approaches")
    audit = lifecycle.audit()
    if audit.get("ok") is not True:
        store.close()
        raise PipelineError(f"Lifecycle audit failed: {audit.get('errors', [])}")
    return store, lifecycle


def _manifest(run_dir: Path, config: dict[str, Any]) -> dict[str, Any]:
    path = run_dir / "candidate-manifest.json"
    if path.is_file():
        return load_json(path)
    value = build_candidate_manifest(REPO_ROOT, config)
    atomic_write_json(path, value)
    return value


def _advance(lifecycle: Lifecycle, next_state: str, event: str, payload: dict[str, Any]) -> None:
    lifecycle.advance(
        next_state,
        event,
        payload,
        actor="automation",
        idempotency_key=f"{event}:{next_state}:{payload.get('sha256') or payload.get('run_id') or payload.get('id', '')}",
    )


def _require_event_hash(lifecycle: Lifecycle, event_type: str, expected_sha256: str) -> None:
    matches = [row for row in lifecycle.store.events(lifecycle.stream) if row["event_type"] == event_type]
    if len(matches) != 1:
        raise PipelineError(f"Lifecycle lacks one immutable {event_type} event")
    payload = json.loads(matches[0]["payload_json"])
    if payload.get("sha256") != expected_sha256:
        raise PipelineError(f"Lifecycle {event_type} event does not bind the expected artifact")


def _freeze(
    run_dir: Path,
    holdout: Path | None,
    holdout_manifest: Path | None,
    config: dict[str, Any],
    lifecycle: Lifecycle,
) -> dict[str, Any]:
    manifest = _manifest(run_dir, config)
    if (run_dir / "plan.json").is_file():
        plan, _ = _verified_plan(run_dir, config)
        if plan.get("candidate_manifest_sha256") != manifest.get("manifest_sha256"):
            raise PipelineError("Frozen candidate manifest no longer matches the run")
    else:
        if holdout is None or holdout_manifest is None:
            raise PipelineError("Private holdout and signed holdout manifest are required for a new run")
        plan = freeze_plan(
            REPO_ROOT,
            run_dir,
            holdout,
            holdout_manifest,
            config,
            manifest,
            base_commit=_git_head(),
        )
    verify_frozen_holdout_signature(run_dir, config)
    if lifecycle.current["state"] == "draft":
        _advance(lifecycle, "frozen", "CANDIDATE_FROZEN", {"sha256": manifest["manifest_sha256"]})
    if lifecycle.current["state"] == "frozen":
        _advance(
            lifecycle,
            "holdout-ready",
            "SIGNED_HOLDOUT_VALIDATED",
            {
                "sha256": plan["holdout_manifest_sha256"],
                "holdout_sha256": plan["holdout"]["sha256"],
                "run_id": plan["run_id"],
            },
        )
    if lifecycle.current["state"] != "holdout-ready":
        raise PipelineError(f"Cannot freeze from lifecycle state {lifecycle.current['state']}")
    return plan


def _git_head() -> str:
    import subprocess

    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        shell=False,
    )
    if completed.returncode != 0:
        raise PipelineError(f"Cannot resolve repository HEAD: {completed.stderr.strip()}")
    return completed.stdout.strip()


def _run_subject_stage(run_dir: Path, config: dict[str, Any], lifecycle: Lifecycle) -> None:
    plan = load_json(run_dir / "plan.json")
    if lifecycle.current["state"] == "holdout-ready":
        _advance(lifecycle, "running", "EVALUATION_STARTED", {"run_id": plan["run_id"]})
    elif lifecycle.current["state"] != "running":
        raise PipelineError(f"Cannot run subjects from lifecycle state {lifecycle.current['state']}")
    result = run_subjects(REPO_ROOT, run_dir, config)
    if result["failed"]:
        lifecycle.block("subject-cells-failed", result)
        raise PipelineError(f"Subject evaluation has {result['failed']} failed cells")
    _advance(lifecycle, "grading", "SUBJECT_EVALUATION_COMPLETED", {"run_id": plan["run_id"], **result})


def _summarize_stage(
    run_dir: Path,
    final_grades: Path,
    human_review: Path,
    config: dict[str, Any],
    lifecycle: Lifecycle,
) -> dict[str, Any]:
    if not (run_dir / "grading" / "blind-packet.jsonl").is_file():
        build_blind_bundle(run_dir, config)
    summary = build_summary(run_dir, config, final_grades, human_review)
    assessment = assess_summary(summary, config)
    atomic_write_json(run_dir / "assessment.json", assessment)
    state = assessment["classification"]
    _advance(lifecycle, state, "EVIDENCE_CLASSIFIED", {"sha256": sha256_file(run_dir / "evaluation-summary.json"), "classification": state})
    if state == "promotable":
        _advance(lifecycle, "awaiting-human-approval", "HUMAN_APPROVAL_REQUESTED", {"sha256": sha256_file(run_dir / "evaluation-summary.json")})
    return assessment


def _approval_template(run_dir: Path, config: dict[str, Any]) -> dict[str, Any]:
    plan = load_json(run_dir / "plan.json")
    summary_path = run_dir / "evaluation-summary.json"
    summary = load_json(summary_path)
    assessment = load_json(run_dir / "assessment.json")
    recomputed = assess_summary(summary, config)
    if assessment != recomputed:
        raise PipelineError("Recorded assessment differs from the frozen deterministic classification")
    if recomputed.get("promotable") is not True or recomputed.get("classification") != "promotable":
        raise PipelineError("Cannot create a promotion approval template for inconclusive evidence")
    manifest = _manifest(run_dir, config)
    rollback_path = run_dir / "rollback-evidence.json"
    if not rollback_path.is_file():
        rehearse_rollback(run_dir)
    promotion = config["promotion"]
    installation = config["installation"]
    return {
        "schema_version": "2.0",
        "approval_id": f"APPROVAL-{uuid.uuid4().hex[:16]}",
        "decision": "promote",
        "approved_by": "REPLACE_WITH_NAMED_HUMAN",
        "approved_at": "REPLACE_WITH_POST_RESULT_RFC3339_TIME",
        "expires_at": "REPLACE_WITH_RFC3339_EXPIRY",
        "evaluation_completed_at": summary["completed_at"],
        "candidate": {
            "name": config["candidate"]["name"],
            "version": config["candidate"]["version"],
            "manifest_sha256": manifest["manifest_sha256"],
            "base_commit": plan["base_commit"],
        },
        "evidence": {
            "evaluation_summary_sha256": sha256_file(summary_path),
            "evidence_manifest_sha256": sha256_file(run_dir / "evidence-manifest.json"),
            "holdout_manifest_sha256": sha256_file(run_dir / "holdout-manifest.json"),
            "protocol_sha256": plan["protocol_sha256"],
            "rubric_sha256": plan["rubric_sha256"],
            "rollback_evidence_sha256": sha256_file(rollback_path),
            "config_sha256": plan["config_sha256"],
        },
        "target": {
            "repository_url": promotion["repository_url"],
            "repository_slug": promotion["repository_slug"],
            "base_branch": promotion["base_branch"],
            "feature_branch": promotion["feature_branch"],
            "root_skills_path": str(Path(installation["skills_root"]) / installation["skill_name"]),
        },
        "permissions": sorted(REQUIRED_PERMISSIONS),
        "thresholds_met": True,
        "accepted_exceptions": [],
        "signature": {
            "algorithm": "ssh-keygen-y",
            "identity": config["approval_verification"].get("expected_identity") or "REPLACE_WITH_SIGNER_IDENTITY",
            "namespace": config["approval_verification"]["namespace"],
            "value": "REPLACE_WITH_BASE64_DETACHED_SSH_SIGNATURE",
        },
        "notes": "Human must inspect evidence before signing. The automation never signs its own authorization.",
    }


def _verify_promotion_inputs(run_dir: Path, approval_path: Path, config: dict[str, Any]) -> dict[str, Any]:
    plan, _ = _verified_plan(run_dir, config)
    verify_frozen_holdout_signature(run_dir, config)
    assessment = load_json(run_dir / "assessment.json")
    recomputed = assess_summary(load_json(run_dir / "evaluation-summary.json"), config)
    if assessment != recomputed:
        raise PipelineError("Recorded assessment differs from the frozen deterministic classification")
    if recomputed.get("promotable") is not True:
        raise PipelineError("Evidence is not conclusively promotable")
    manifest = _manifest(run_dir, config)
    if plan.get("candidate_manifest_sha256") != manifest.get("manifest_sha256"):
        raise PipelineError("Candidate manifest changed after evaluation freeze")
    approval = load_json(approval_path)
    validate_approval(
        approval,
        config,
        manifest,
        run_dir / "evaluation-summary.json",
        run_dir / "holdout-manifest.json",
        run_dir / "rollback-evidence.json",
    )
    return approval


def _verified_approval(
    run_dir: Path, approval_path: Path | None, config: dict[str, Any]
) -> tuple[Path, dict[str, Any]]:
    """Persist and revalidate the exact signed approval used for all recovery."""
    persisted = run_dir / "verified-approval.json"
    if approval_path is not None:
        approval = _verify_promotion_inputs(run_dir, approval_path, config)
        if persisted.exists():
            if persisted.is_symlink() or not persisted.is_file():
                raise PipelineError("Persisted approval path is unsafe")
            if load_json(persisted) != approval:
                raise PipelineError("Provided approval differs from the immutable persisted approval")
        else:
            atomic_write_json(persisted, approval)
    elif not persisted.is_file() or persisted.is_symlink():
        raise PipelineError("Active recovery lacks the exact persisted signed approval")
    approval = _verify_promotion_inputs(run_dir, persisted, config)
    return persisted, approval


def _promote(run_dir: Path, approval_path: Path | None, config: dict[str, Any], lifecycle: Lifecycle, apply: bool) -> dict[str, Any]:
    persisted_approval_path, approval = _verified_approval(run_dir, approval_path, config)
    approval_sha256 = sha256_file(persisted_approval_path)
    manifest = _manifest(run_dir, config)
    summary_sha256 = sha256_file(run_dir / "evaluation-summary.json")
    _require_event_hash(lifecycle, "EVIDENCE_CLASSIFIED", summary_sha256)
    _require_event_hash(lifecycle, "HUMAN_APPROVAL_REQUESTED", summary_sha256)
    if lifecycle.current["state"] == "awaiting-human-approval":
        _advance(lifecycle, "approved", "SIGNED_APPROVAL_VERIFIED", {"id": approval["approval_id"], "sha256": approval_sha256})
    else:
        _require_event_hash(lifecycle, "SIGNED_APPROVAL_VERIFIED", approval_sha256)

    prepared_path = run_dir / "prepared-promotion.json"
    if prepared_path.is_file():
        prepared = load_immutable_record(prepared_path)
    else:
        if lifecycle.current["state"] != "approved":
            raise PipelineError("Prepared promotion receipt is missing during recovery")
        prepared = prepare_clean_promotion(
            REPO_ROOT,
            run_dir / f"promotion-work-{uuid.uuid4().hex}",
            config,
            manifest,
            expected_base_commit=approval["candidate"]["base_commit"],
            approval_sha256=approval_sha256,
            config_sha256=sha256_json(config),
        )
        prepared = write_immutable_record(prepared_path, prepared)
    if prepared.get("base_commit") != approval["candidate"]["base_commit"]:
        raise PipelineError("Prepared promotion targets another signed base commit")
    validate_prepared_promotion(
        prepared,
        run_dir,
        config,
        manifest,
        approval_sha256=approval_sha256,
    )
    if not apply:
        return {**prepared, "dry_run": True}
    if lifecycle.current["state"] == "approved":
        _advance(lifecycle, "promoting", "PROMOTION_STARTED", {"id": approval["approval_id"], "sha256": prepared["record_sha256"]})

    pr_path = run_dir / "pr-record.json"
    if pr_path.is_file():
        pr_record = load_immutable_record(pr_path, status="pr-open")
    else:
        if lifecycle.current["state"] != "promoting":
            raise PipelineError("Pull-request receipt is missing during recovery")
        opened = push_and_open_pr(Path(prepared["clone"]), config)
        pr_record = build_pr_record(
            prepared,
            opened,
            approval_sha256=approval_sha256,
            candidate_manifest_sha256=manifest["manifest_sha256"],
            config_sha256=sha256_json(config),
        )
        pr_record = write_immutable_record(pr_path, pr_record)
    expected_pr_bindings = {
        "approval_sha256": approval_sha256,
        "candidate_manifest_sha256": manifest["manifest_sha256"],
        "config_sha256": sha256_json(config),
        "base_commit": approval["candidate"]["base_commit"],
        "head_commit": prepared["head_commit"],
    }
    if any(pr_record.get(key) != value for key, value in expected_pr_bindings.items()):
        raise PipelineError("Pull-request receipt differs from the approved promotion")
    if lifecycle.current["state"] == "promoting":
        _advance(
            lifecycle,
            "pr-open",
            "PULL_REQUEST_OPENED",
            {"id": pr_record["pr_url"], "sha256": pr_record["record_sha256"], "head_commit": pr_record["head_commit"]},
        )
    else:
        _require_event_hash(lifecycle, "PULL_REQUEST_OPENED", pr_record["record_sha256"])
    return pr_record


def _merge_and_install(
    run_dir: Path, approval_path: Path | None, config: dict[str, Any], lifecycle: Lifecycle
) -> dict[str, Any]:
    persisted_approval_path, approval = _verified_approval(run_dir, approval_path, config)
    approval_sha256 = sha256_file(persisted_approval_path)
    _require_event_hash(lifecycle, "SIGNED_APPROVAL_VERIFIED", approval_sha256)
    manifest = _manifest(run_dir, config)
    pr_record = load_immutable_record(run_dir / "pr-record.json", status="pr-open")
    _require_event_hash(lifecycle, "PULL_REQUEST_OPENED", pr_record["record_sha256"])
    expected_pr_bindings = {
        "approval_sha256": approval_sha256,
        "candidate_manifest_sha256": manifest["manifest_sha256"],
        "config_sha256": sha256_json(config),
        "base_commit": approval["candidate"]["base_commit"],
    }
    if any(pr_record.get(key) != value for key, value in expected_pr_bindings.items()):
        raise PipelineError("Pull-request receipt differs from the approved promotion")

    # GitHub is the source of truth even when a crash left a pre-event release receipt.
    merged = merge_reviewed_pr(pr_record["pr_url"], pr_record["head_commit"], config)
    release_path = run_dir / "release-record.json"
    if release_path.is_file():
        release = load_immutable_record(release_path, status="merged")
        validate_release_record(release, pr_record, merged)
    else:
        if lifecycle.current["state"] != "pr-open":
            raise PipelineError("Release receipt is missing during recovery")
        release = write_immutable_record(release_path, build_release_record(pr_record, merged))
    if release.get("pr_record_sha256") != pr_record["record_sha256"]:
        raise PipelineError("Release receipt is not bound to the pull-request receipt")

    checkout: Path | None = None
    if lifecycle.current["state"] == "pr-open":
        checkout = checkout_immutable_merge(
            run_dir / f"install-work-{uuid.uuid4().hex}",
            config["promotion"]["repository_url"],
            release["merge_commit"],
        )
        verify_merge_reachable(checkout, release["merge_commit"], config)
        verify_merged_candidate(checkout, manifest, config["candidate"]["skill_path"])
        _advance(
            lifecycle,
            "merged",
            "REVIEWED_PULL_REQUEST_MERGED",
            {"id": release["pr_url"], "sha256": release["record_sha256"], "merge_commit": release["merge_commit"]},
        )
    else:
        _require_event_hash(lifecycle, "REVIEWED_PULL_REQUEST_MERGED", release["record_sha256"])

    destination = Path(config["installation"]["skills_root"]).expanduser() / config["installation"]["skill_name"]
    if lifecycle.current["state"] == "active":
        receipt = validate_installation_receipt(
            run_dir,
            expected_merge_commit=release["merge_commit"],
            expected_destination=destination,
        )
        verify_installed_candidate(destination, manifest, config["candidate"]["skill_path"])
        _require_event_hash(lifecycle, "CANARY_PASSED", receipt["record_sha256"])
        return receipt

    if checkout is None:
        checkout = checkout_immutable_merge(
            run_dir / f"install-work-{uuid.uuid4().hex}",
            config["promotion"]["repository_url"],
            release["merge_commit"],
        )
        verify_merge_reachable(checkout, release["merge_commit"], config)
        verify_merged_candidate(checkout, manifest, config["candidate"]["skill_path"])

    if lifecycle.current["state"] == "merged":
        _advance(lifecycle, "installing", "ROOT_INSTALL_STARTED", {"sha256": release["record_sha256"], "merge_commit": release["merge_commit"]})
    if lifecycle.current["state"] == "installing":
        _advance(lifecycle, "canary", "CANARY_STARTED", {"sha256": release["record_sha256"], "merge_commit": release["merge_commit"]})
    if lifecycle.current["state"] == "canary":
        try:
            receipt = atomic_install(checkout, release["merge_commit"], run_dir, config)
        except PipelineError as exc:
            if (run_dir / "rollback-record.json").is_file():
                _advance(lifecycle, "quarantined", "CANARY_FAILED_AND_QUARANTINED", {"id": str(exc)})
                _advance(lifecycle, "rolled-back", "PREVIOUS_ROOT_STATE_RESTORED", {"sha256": release["merge_commit"]})
            else:
                lifecycle.block("install-failed-before-root-mutation", {"detail": str(exc)})
            raise
        verify_installed_candidate(destination, manifest, config["candidate"]["skill_path"])
        _advance(
            lifecycle,
            "active",
            "CANARY_PASSED",
            {"sha256": receipt["record_sha256"], "merge_commit": release["merge_commit"]},
        )
        return receipt
    raise PipelineError(f"Cannot install from lifecycle state {lifecycle.current['state']}")


def command_manifest(args: argparse.Namespace) -> int:
    config = _config(args.config)
    value = build_candidate_manifest(REPO_ROOT, config)
    atomic_write_json(args.output, value)
    print(json.dumps({"manifest": str(args.output), "sha256": value["manifest_sha256"]}, sort_keys=True))
    return 0


def command_holdout_template(args: argparse.Namespace) -> int:
    config = _config(args.config)
    candidate_manifest = build_candidate_manifest(REPO_ROOT, config)
    value = build_holdout_manifest_template(REPO_ROOT, args.holdout, config, candidate_manifest)
    atomic_write_json(args.output, value)
    payload_path = args.output.with_suffix(args.output.suffix + ".payload")
    payload_path.parent.mkdir(parents=True, exist_ok=True)
    payload_path.write_bytes(holdout_manifest_payload(value))
    print(
        json.dumps(
            {
                "unsigned_template": str(args.output),
                "sign_this_file": str(payload_path),
                "namespace": value["signature"]["namespace"],
            },
            sort_keys=True,
        )
    )
    return 0


def command_status(args: argparse.Namespace) -> int:
    store, lifecycle = _lifecycle(args.run_dir)
    try:
        print(json.dumps({"current": lifecycle.current, "audit": lifecycle.audit()}, indent=2, sort_keys=True))
    finally:
        store.close()
    return 0


def command_freeze(args: argparse.Namespace) -> int:
    config = _config(args.config, args.run_dir)
    store, lifecycle = _lifecycle(args.run_dir)
    try:
        plan = _freeze(args.run_dir, args.holdout, args.holdout_manifest, config, lifecycle)
        print(json.dumps({"state": lifecycle.current["state"], "run_id": plan["run_id"], "cells": len(plan["cells"])}, sort_keys=True))
    finally:
        store.close()
    return 0


def command_run(args: argparse.Namespace) -> int:
    config = _config(args.config, args.run_dir)
    store, lifecycle = _lifecycle(args.run_dir)
    try:
        _run_subject_stage(args.run_dir, config, lifecycle)
        packet = build_blind_bundle(args.run_dir, config)
        print(json.dumps({"state": lifecycle.current["state"], **packet}, sort_keys=True))
    finally:
        store.close()
    return 0


def command_grade(args: argparse.Namespace) -> int:
    config = _config(args.config, args.run_dir)
    print(json.dumps(run_provisional_grading(args.run_dir, config), sort_keys=True))
    return 0


def command_summarize(args: argparse.Namespace) -> int:
    config = _config(args.config, args.run_dir)
    store, lifecycle = _lifecycle(args.run_dir)
    try:
        assessment = _summarize_stage(args.run_dir, args.final_grades, args.human_review, config, lifecycle)
        print(json.dumps({"state": lifecycle.current["state"], "assessment": assessment}, indent=2, sort_keys=True))
        return 0 if assessment["promotable"] else 10
    finally:
        store.close()


def command_approval_template(args: argparse.Namespace) -> int:
    config = _config(args.config, args.run_dir)
    value = _approval_template(args.run_dir, config)
    atomic_write_json(args.output, value)
    print(json.dumps({"unsigned_template": str(args.output)}, sort_keys=True))
    return 0


def command_approval_payload(args: argparse.Namespace) -> int:
    approval = load_json(args.approval)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(approval_payload(approval))
    print(json.dumps({"sign_this_file": str(args.output)}, sort_keys=True))
    return 0


def command_attach_signature(args: argparse.Namespace) -> int:
    approval = load_json(args.approval)
    signature = args.signature.read_bytes()
    if not signature.startswith(b"-----BEGIN SSH SIGNATURE-----"):
        raise PipelineError("Detached signature is not an armored SSH signature")
    approval.setdefault("signature", {})["value"] = base64.b64encode(signature).decode("ascii")
    atomic_write_json(args.output, approval)
    print(json.dumps({"signed_approval": str(args.output)}, sort_keys=True))
    return 0


def command_rehearse(args: argparse.Namespace) -> int:
    print(json.dumps(rehearse_rollback(args.run_dir), sort_keys=True))
    return 0


def command_verify_approval(args: argparse.Namespace) -> int:
    config = _config(args.config, args.run_dir)
    _verify_promotion_inputs(args.run_dir, args.approval, config)
    print(json.dumps({"approval": "verified", "sha256": sha256_file(args.approval)}, sort_keys=True))
    return 0


def command_promote(args: argparse.Namespace) -> int:
    config = _config(args.config, args.run_dir)
    store, lifecycle = _lifecycle(args.run_dir)
    try:
        result = _promote(args.run_dir, args.approval, config, lifecycle, args.apply)
        print(json.dumps({"state": lifecycle.current["state"], **result}, indent=2, sort_keys=True))
    finally:
        store.close()
    return 0


def command_merge_install(args: argparse.Namespace) -> int:
    if not args.apply:
        raise PipelineError("merge-install requires --apply")
    config = _config(args.config, args.run_dir)
    store, lifecycle = _lifecycle(args.run_dir)
    try:
        result = _merge_and_install(args.run_dir, args.approval, config, lifecycle)
        print(json.dumps({"state": lifecycle.current["state"], "installation": result}, indent=2, sort_keys=True))
    finally:
        store.close()
    return 0


def command_auto(args: argparse.Namespace) -> int:
    config = _config(args.config, args.run_dir)
    store, lifecycle = _lifecycle(args.run_dir)
    try:
        state = lifecycle.current["state"]
        if state in {"draft", "frozen"}:
            if not (args.run_dir / "plan.json").is_file() and (args.holdout is None or args.holdout_manifest is None):
                lifecycle.block("private-holdout-and-signed-manifest-required")
                return 20
            _freeze(args.run_dir, args.holdout, args.holdout_manifest, config, lifecycle)
            state = lifecycle.current["state"]
        if state in {"holdout-ready", "running"}:
            _run_subject_stage(args.run_dir, config, lifecycle)
            state = lifecycle.current["state"]
        if state == "grading":
            if not (args.run_dir / "grading" / "blind-packet.jsonl").is_file():
                build_blind_bundle(args.run_dir, config)
            if config["evaluation"].get("grader_adapter_argv") and not (args.run_dir / "grading" / "provisional-grades.jsonl").is_file():
                run_provisional_grading(args.run_dir, config)
            if args.final_grades is None or args.human_review is None:
                lifecycle.block("human-final-grades-and-review-required")
                print(json.dumps({"state": lifecycle.current["state"], "next_gate": "human-final-grades-and-review"}, sort_keys=True))
                return 20
            assessment = _summarize_stage(args.run_dir, args.final_grades, args.human_review, config, lifecycle)
            if not assessment["promotable"]:
                print(json.dumps({"state": lifecycle.current["state"], "assessment": assessment}, sort_keys=True))
                return 10
            state = lifecycle.current["state"]
        if state == "promotable":
            summary_sha256 = sha256_file(args.run_dir / "evaluation-summary.json")
            _advance(lifecycle, "awaiting-human-approval", "HUMAN_APPROVAL_REQUESTED", {"sha256": summary_sha256})
            state = lifecycle.current["state"]
        if state == "awaiting-human-approval":
            if not (args.run_dir / "rollback-evidence.json").is_file():
                rehearse_rollback(args.run_dir)
            if args.approval is None:
                template_path = args.run_dir / "promotion-approval.unsigned.json"
                atomic_write_json(template_path, _approval_template(args.run_dir, config))
                lifecycle.block("signed-post-result-human-approval-required", {"template": str(template_path)})
                print(json.dumps({"state": lifecycle.current["state"], "next_gate": "signed-human-approval", "template": str(template_path)}, sort_keys=True))
                return 20
            persisted_approval, approval = _verified_approval(args.run_dir, args.approval, config)
            _advance(
                lifecycle,
                "approved",
                "SIGNED_APPROVAL_VERIFIED",
                {"id": approval["approval_id"], "sha256": sha256_file(persisted_approval)},
            )
            state = lifecycle.current["state"]
        if state in {"approved", "promoting"}:
            if args.approval is None and not (args.run_dir / "verified-approval.json").is_file():
                lifecycle.block("signed-post-result-human-approval-required-for-recovery")
                return 20
            if not args.apply:
                lifecycle.block("apply-required-for-external-effects")
                print(json.dumps({"state": lifecycle.current["state"], "next_gate": "rerun-with-apply"}, sort_keys=True))
                return 20
            _promote(args.run_dir, args.approval, config, lifecycle, True)
            state = lifecycle.current["state"]
        if state == "pr-open":
            if not args.apply:
                return 20
            deadline = time.monotonic() + max(0, args.max_review_wait_seconds)
            while True:
                try:
                    result = _merge_and_install(args.run_dir, args.approval, config, lifecycle)
                    print(json.dumps({"state": lifecycle.current["state"], "installation": result}, sort_keys=True))
                    return 0
                except PipelineError as exc:
                    pending_review = any(
                        marker in str(exc)
                        for marker in ("lacks approval", "CLEAN merge status", "no successful required checks", "check did not succeed", "status did not succeed")
                    )
                    if not pending_review or time.monotonic() >= deadline:
                        lifecycle.block("independent-pr-review-required", {"detail": str(exc)})
                        print(json.dumps({"state": lifecycle.current["state"], "next_gate": "independent-pr-review", "detail": str(exc)}, sort_keys=True))
                        return 20
                    time.sleep(max(1, args.poll_seconds))
        if state in {"merged", "installing", "canary"}:
            if (args.approval is None and not (args.run_dir / "verified-approval.json").is_file()) or not args.apply:
                lifecycle.block("signed-approval-and-apply-required-for-install-recovery")
                return 20
            result = _merge_and_install(args.run_dir, args.approval, config, lifecycle)
            print(json.dumps({"state": lifecycle.current["state"], "installation": result}, sort_keys=True))
            return 0
        if state == "active":
            result = _merge_and_install(args.run_dir, args.approval, config, lifecycle)
            print(json.dumps({"state": lifecycle.current["state"], "installation": result}, sort_keys=True))
            return 0
        print(json.dumps({"state": lifecycle.current["state"]}, sort_keys=True))
        return 0 if lifecycle.current["state"] == "active" else 10
    finally:
        store.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=_path, default=DEFAULT_CONFIG)
    subparsers = parser.add_subparsers(dest="command", required=True)

    manifest = subparsers.add_parser("manifest")
    manifest.add_argument("--output", type=_path, required=True)
    manifest.set_defaults(function=command_manifest)

    holdout_template = subparsers.add_parser("holdout-template")
    holdout_template.add_argument("--holdout", type=_path, required=True)
    holdout_template.add_argument("--output", type=_path, required=True)
    holdout_template.set_defaults(function=command_holdout_template)

    status = subparsers.add_parser("status")
    status.add_argument("--run-dir", type=_path, required=True)
    status.set_defaults(function=command_status)

    freeze = subparsers.add_parser("freeze")
    freeze.add_argument("--run-dir", type=_path, required=True)
    freeze.add_argument("--holdout", type=_path, required=True)
    freeze.add_argument("--holdout-manifest", type=_path, required=True)
    freeze.set_defaults(function=command_freeze)

    run = subparsers.add_parser("run")
    run.add_argument("--run-dir", type=_path, required=True)
    run.set_defaults(function=command_run)

    grade = subparsers.add_parser("grade")
    grade.add_argument("--run-dir", type=_path, required=True)
    grade.set_defaults(function=command_grade)

    summarize = subparsers.add_parser("summarize")
    summarize.add_argument("--run-dir", type=_path, required=True)
    summarize.add_argument("--final-grades", type=_path, required=True)
    summarize.add_argument("--human-review", type=_path, required=True)
    summarize.set_defaults(function=command_summarize)

    approval_template = subparsers.add_parser("approval-template")
    approval_template.add_argument("--run-dir", type=_path, required=True)
    approval_template.add_argument("--output", type=_path, required=True)
    approval_template.set_defaults(function=command_approval_template)

    approval_payload_parser = subparsers.add_parser("approval-payload")
    approval_payload_parser.add_argument("--approval", "--document", dest="approval", type=_path, required=True)
    approval_payload_parser.add_argument("--output", type=_path, required=True)
    approval_payload_parser.set_defaults(function=command_approval_payload)

    attach_signature = subparsers.add_parser("attach-signature")
    attach_signature.add_argument("--approval", "--document", dest="approval", type=_path, required=True)
    attach_signature.add_argument("--signature", type=_path, required=True)
    attach_signature.add_argument("--output", type=_path, required=True)
    attach_signature.set_defaults(function=command_attach_signature)

    rehearse = subparsers.add_parser("rehearse-rollback")
    rehearse.add_argument("--run-dir", type=_path, required=True)
    rehearse.set_defaults(function=command_rehearse)

    verify = subparsers.add_parser("verify-approval")
    verify.add_argument("--run-dir", type=_path, required=True)
    verify.add_argument("--approval", type=_path, required=True)
    verify.set_defaults(function=command_verify_approval)

    promote = subparsers.add_parser("promote")
    promote.add_argument("--run-dir", type=_path, required=True)
    promote.add_argument("--approval", type=_path, required=True)
    promote.add_argument("--apply", action="store_true")
    promote.set_defaults(function=command_promote)

    merge_install = subparsers.add_parser("merge-install")
    merge_install.add_argument("--run-dir", type=_path, required=True)
    merge_install.add_argument("--approval", type=_path, required=True)
    merge_install.add_argument("--apply", action="store_true")
    merge_install.set_defaults(function=command_merge_install)

    auto = subparsers.add_parser("auto")
    auto.add_argument("--run-dir", type=_path, required=True)
    auto.add_argument("--holdout", type=_path)
    auto.add_argument("--holdout-manifest", type=_path)
    auto.add_argument("--final-grades", type=_path)
    auto.add_argument("--human-review", type=_path)
    auto.add_argument("--approval", type=_path)
    auto.add_argument("--apply", action="store_true")
    auto.add_argument("--poll-seconds", type=int, default=30)
    auto.add_argument("--max-review-wait-seconds", type=int, default=0)
    auto.set_defaults(function=command_auto)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return int(args.function(args))
    except PipelineError as exc:
        print(json.dumps({"error": str(exc), "status": "blocked"}, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
