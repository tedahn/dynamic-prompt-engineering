#!/usr/bin/env python3
"""Build and validate immutable, role-separated skill review bundles."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
from typing import Any


SCHEMA_VERSION = "1.0"
REQUIRED_ROLES = (
    "evidence-methodology",
    "engineering-reproducibility",
    "skill-safety-operations",
)
ALLOWED_SEVERITIES = {"P0", "P1", "P2", "P3"}
ALLOWED_FINDING_STATUSES = {
    "open",
    "resolved",
    "accepted_risk",
    "rejected",
    "unresolved",
}
SKILL_ROOT = Path(__file__).resolve().parents[1]
ASSET_ROOT = SKILL_ROOT / "assets"


class ReviewError(RuntimeError):
    """A controlled review-bundle failure."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def canonical_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_json(path: Path, value: Any) -> None:
    write_text(path, canonical_json(value))


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewError(f"Cannot load JSON {path}: {exc}") from exc


def git(repo: Path, *args: str, binary: bool = False) -> bytes | str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=False,
        capture_output=True,
        text=not binary,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", "replace") if binary else result.stderr
        raise ReviewError(f"git {' '.join(args)} failed: {stderr.strip()}")
    return result.stdout


def resolve_ref(repo: Path, ref: str) -> str:
    return str(git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")).strip()


def ensure_relative(path_text: str) -> str:
    path = PurePosixPath(path_text)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ReviewError(f"Path must be repository-relative: {path_text}")
    return path.as_posix()


def blob_at(repo: Path, commit: str, relative: str) -> bytes | None:
    result = subprocess.run(
        ["git", "show", f"{commit}:{relative}"],
        cwd=repo,
        check=False,
        capture_output=True,
    )
    return result.stdout if result.returncode == 0 else None


def file_record(repo: Path, base_sha: str, head_sha: str, relative: str) -> dict[str, Any]:
    relative = ensure_relative(relative)
    head_blob = blob_at(repo, head_sha, relative)
    base_blob = blob_at(repo, base_sha, relative)
    if head_blob is None and base_blob is None:
        raise ReviewError(f"Artifact is absent from both target commits: {relative}")
    state = "modified"
    if base_blob is None:
        state = "added"
    elif head_blob is None:
        state = "deleted"
    elif head_blob == base_blob:
        state = "unchanged"
    return {
        "path": relative,
        "state": state,
        "base_sha256": sha256_bytes(base_blob) if base_blob is not None else None,
        "head_sha256": sha256_bytes(head_blob) if head_blob is not None else None,
    }


def changed_files(repo: Path, base_sha: str, head_sha: str) -> list[str]:
    output = git(repo, "diff", "--name-only", "-z", base_sha, head_sha, binary=True)
    assert isinstance(output, bytes)
    return sorted(
        ensure_relative(item.decode("utf-8"))
        for item in output.split(b"\0")
        if item
    )


def target_record(repo: Path, base_ref: str, head_ref: str) -> dict[str, str]:
    base_sha = resolve_ref(repo, base_ref)
    head_sha = resolve_ref(repo, head_ref)
    diff = git(
        repo,
        "diff",
        "--binary",
        "--full-index",
        "--no-ext-diff",
        base_sha,
        head_sha,
        binary=True,
    )
    assert isinstance(diff, bytes)
    return {
        "base_sha": base_sha,
        "head_sha": head_sha,
        "diff_sha256": sha256_bytes(diff),
    }


def render_context(manifest: dict[str, Any]) -> str:
    target = manifest["target"]
    evidence_rows = "\n".join(
        f"| {index:03d} | `{row['path']}` | {row['state']} | "
        f"`{row['head_sha256'] or row['base_sha256']}` |"
        for index, row in enumerate(manifest["evidence_index"], 1)
    )
    validation = "\n".join(f"- {item}" for item in manifest["known_validation"]) or "- None recorded"
    policies = "\n".join(f"- `{row['path']}`" for row in manifest["policy_index"])
    return f"""# {manifest['review_id']} — frozen review context

- Version: {SCHEMA_VERSION}
- Built at: {manifest['built_at']}
- Owner: {manifest['decision_owner']}
- Consumer: isolated reviewers and adjudicator
- Supported gate: merge readiness only
- Repository: {manifest['repository']}
- Base SHA: `{target['base_sha']}`
- Head SHA: `{target['head_sha']}`
- Diff SHA-256: `{target['diff_sha256']}`
- Context budget: changed files plus allowlisted policies; retrieve exact excerpts only as needed
- Refresh trigger: any target, policy, evaluation, or authority change

## Decision and success criteria

Decide whether the frozen target is coherent and safe enough to become eligible for a named-human merge decision. Success requires three independent role submissions, evidence-bound adjudication, target integrity, and no upheld unresolved P0/P1 finding.

## Authorized actions

- Read the frozen commits and allowlisted policies.
- Run read-only or local deterministic validation.
- Produce one structured reviewer submission or adjudication artifact.

## Forbidden actions

- Modify the target, merge, install, promote, deploy, contact people, or spend money.
- Read another reviewer submission before independent review closes.
- Treat merge readiness as behavioral, promotion, or installation evidence.

## Current state

The target is frozen for review. Existing validation is reported evidence, not a substitute for inspection.

## Known validation

{validation}

## Canonical policies

{policies}

## Evidence index

| ID | Exact location | State | Content SHA-256 |
|---|---|---|---|
{evidence_rows}

## Contradiction register

- Mechanical or unit-test success does not establish behavioral efficacy.
- Publication or merge does not authorize skill installation or production promotion.
- Reviewer agreement does not replace evidence quality or human authority.

## Material unknowns

- ChatGPT transfer is untested unless a ChatGPT run is separately recorded.
- Reviewer coverage outside the declared `reviewed_files` is unknown.
- Behavioral efficacy and adoption readiness remain outside this merge review.

## Excluded context

| Item | Reason | Reconsider when |
|---|---|---|
| Other reviewer outputs | Preserve independence | Adjudication begins |
| Uncommitted working tree | Target is the frozen commits | A superseding review is opened |
| Secrets and private local state | Outside public review boundary | Never include raw values |

## Required output

One schema-valid role submission with explicit coverage, evidence anchors, counterevidence, confidence, limitations, and no self-approval.

## Validation

Run `review_bundle.py validate` after all role submissions and adjudication exist. Only the named human may decide merge.

## Stop and fallback rules

Stop on target mismatch, missing authority, secret or privacy exposure, contaminated reviewer context, unavailable evidence, or material uncovered scope. Record `blocked` or `unresolved`; do not simulate completion.

## Handoff

Return the structured submission to the adjudicator after all independent reviews close. Preserve raw artifacts and hashes.
"""


ROLE_FOCUS = {
    "evidence-methodology": (
        "Inspect claim-source traceability, evidence states, contradictions, null results, "
        "evaluation design, leakage, graders, thresholds, and transfer claims."
    ),
    "engineering-reproducibility": (
        "Inspect implementation correctness, isolation, frozen hashes, deterministic behavior, "
        "failure handling, schemas, tests, portability, and rollback mechanics."
    ),
    "skill-safety-operations": (
        "Inspect triggers, non-triggers, input trust, injection boundaries, privacy, authority, "
        "high-stakes behavior, maintenance, observability, rollout, and rollback."
    ),
}


def render_assignment(manifest: dict[str, Any], role: str) -> str:
    target = manifest["target"]
    return f"""# Assignment — {role}

Use `$review-skill-candidate` to review `{manifest['repository']}` at the immutable target below.

- Review ID: `{manifest['review_id']}`
- Base SHA: `{target['base_sha']}`
- Head SHA: `{target['head_sha']}`
- Diff SHA-256: `{target['diff_sha256']}`
- Decision: merge eligibility for named-human review only
- Role: `{role}`

Read `context-pack.md`, then inspect the frozen commits and only the source pointers needed for this role. {ROLE_FOCUS[role]}

Do not read `submissions/` or another assignment. Do not modify files, approve merge, infer behavioral efficacy, or authorize promotion or installation.

Write exactly one JSON object matching `schemas/review-submission.schema.json` to `submissions/{role}.json`. Use reviewer role `{role}`, set `independent_context` to true only if isolation held, declare reviewed and not-reviewed scope, and anchor every finding to repository-relative file lines. An empty findings array is allowed only after the declared concerns were inspected.
"""


def render_gate(manifest: dict[str, Any]) -> str:
    target = manifest["target"]
    return f"""# {manifest['review_id']} — merge-readiness decision

- Gate: G5 review handoff; merge decision only
- Status: proposed
- Decision owner: {manifest['decision_owner']}
- Requested by: {manifest['requested_by']}
- Opened at: {manifest['built_at']}
- Decided at: null
- Expires at: target or policy change
- Supersedes: null
- Evidence snapshot: `{target['head_sha']} / {target['diff_sha256']}`

## Decision requested

After independent reviews and adjudication, decide whether the exact frozen target may merge.

## Why now

The target is published for review and requires evidence beyond deterministic tests.

## In scope / out of scope

In scope: merge coherence, evidence integrity, implementation reproducibility, skill safety, and operational reviewability. Out of scope: behavioral-efficacy claims, skill promotion, installation, deployment, or broader adoption.

## Roles

- Responsible: three isolated reviewers and one adjudicator
- Accountable: {manifest['decision_owner']}
- Consulted: repository maintainers and evidence owners as needed

## Evidence

Use only the frozen context packet, target commits, allowlisted policies, raw submissions, and deterministic validation summary.

## Acceptance criteria

Target and packet integrity pass; all required roles are independent; every finding is adjudicated; no upheld unresolved P0/P1 remains; the named human decides.

## Stop conditions

Stop on target drift, missing role coverage, contaminated independence, secrets, privacy risk, invalid evidence anchors, or unavailable decision authority.

## Decision

Pending named-human decision. Models and harnesses may not change this status to approved.

## Reversal evidence

Any target, policy, evidence, reviewer-independence, or authority change reopens the gate.

## Handoff

Adjudicator receives immutable submissions after independence closes; the decision owner receives adjudication plus validation and retains final authority.
"""


def create_packet_index(bundle: Path) -> None:
    paths: list[Path] = []
    for relative in ("manifest.json", "context-pack.md", "gate.md"):
        paths.append(bundle / relative)
    for folder in ("assignments", "schemas", "templates"):
        paths.extend(sorted(path for path in (bundle / folder).glob("*") if path.is_file()))
    index = {
        path.relative_to(bundle).as_posix(): sha256_file(path)
        for path in sorted(paths)
    }
    write_json(bundle / "packet-index.json", {"schema_version": SCHEMA_VERSION, "files": index})


def init_bundle(args: argparse.Namespace) -> dict[str, Any]:
    repo = Path(args.repo_root).resolve()
    bundle = Path(args.output).resolve()
    if not (repo / ".git").exists() and not str(git(repo, "rev-parse", "--git-dir")).strip():
        raise ReviewError(f"Not a git repository: {repo}")
    if bundle.exists():
        raise ReviewError(f"Output already exists; preserve or supersede it: {bundle}")

    target = target_record(repo, args.base, args.head)
    changed = changed_files(repo, target["base_sha"], target["head_sha"])
    if not changed:
        raise ReviewError("Frozen target has no changed files")
    artifacts = sorted(set(changed + [ensure_relative(item) for item in args.artifact]))
    policies = sorted(set(ensure_relative(item) for item in args.policy))
    review_id = args.review_id or f"PR-{int(args.pr_number):03d}-{target['head_sha'][:12]}"

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "review_id": review_id,
        "repository": args.repository,
        "pull_request": int(args.pr_number),
        "built_at": args.built_at,
        "decision": "merge_readiness",
        "decision_owner": args.decision_owner,
        "requested_by": args.requested_by,
        "target": target,
        "required_roles": list(REQUIRED_ROLES),
        "known_validation": list(args.validation),
        "changed_files": changed,
        "evidence_index": [
            file_record(repo, target["base_sha"], target["head_sha"], item)
            for item in artifacts
        ],
        "policy_index": [
            file_record(repo, target["base_sha"], target["head_sha"], item)
            for item in policies
        ],
        "authority": {
            "authorized": ["read frozen target", "run local deterministic checks", "submit review artifacts"],
            "forbidden": ["modify target", "merge", "install", "promote", "deploy", "external side effects"],
        },
    }

    for folder in ("assignments", "submissions", "adjudication", "human-decision", "schemas", "templates"):
        (bundle / folder).mkdir(parents=True, exist_ok=False)
    write_json(bundle / "manifest.json", manifest)
    write_text(bundle / "context-pack.md", render_context(manifest))
    write_text(bundle / "gate.md", render_gate(manifest))
    for role in REQUIRED_ROLES:
        write_text(bundle / "assignments" / f"{role}.md", render_assignment(manifest, role))
    for path in sorted((ASSET_ROOT / "schemas").glob("*.json")):
        shutil.copy2(path, bundle / "schemas" / path.name)
    for path in sorted((ASSET_ROOT / "templates").glob("*.json")):
        shutil.copy2(path, bundle / "templates" / path.name)
    create_packet_index(bundle)
    return {"ok": True, "review_id": review_id, "bundle": str(bundle), "target": target}


def exact_target(value: Any, target: dict[str, str]) -> bool:
    return isinstance(value, dict) and all(value.get(key) == target[key] for key in target)


def validate_packet_index(bundle: Path, errors: list[str]) -> None:
    index_path = bundle / "packet-index.json"
    if not index_path.is_file():
        errors.append("missing packet-index.json")
        return
    index = load_json(index_path)
    files = index.get("files") if isinstance(index, dict) else None
    if not isinstance(files, dict) or not files:
        errors.append("packet-index.json has no file map")
        return
    for relative, expected in files.items():
        path = bundle / ensure_relative(str(relative))
        if not path.is_file():
            errors.append(f"packet file missing: {relative}")
        elif sha256_file(path) != expected:
            errors.append(f"packet file hash mismatch: {relative}")


def line_count_for_anchor(repo: Path, target: dict[str, str], relative: str) -> int | None:
    for commit in (target["head_sha"], target["base_sha"]):
        blob = blob_at(repo, commit, relative)
        if blob is not None:
            return len(blob.decode("utf-8", "replace").splitlines()) or 1
    return None


def validate_submission(
    repo: Path,
    path: Path,
    role: str,
    manifest: dict[str, Any],
    errors: list[str],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if not path.is_file():
        errors.append(f"missing reviewer submission: {role}")
        return None, []
    value = load_json(path)
    if not isinstance(value, dict):
        errors.append(f"submission is not an object: {role}")
        return None, []
    target = manifest["target"]
    if value.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"{role} schema_version mismatch")
    if value.get("review_id") != manifest["review_id"]:
        errors.append(f"{role} review_id mismatch")
    if not exact_target(value.get("target"), target):
        errors.append(f"{role} target mismatch")
    reviewer = value.get("reviewer")
    if not isinstance(reviewer, dict) or reviewer.get("role") != role:
        errors.append(f"{role} reviewer role mismatch")
    elif reviewer.get("independent_context") is not True:
        errors.append(f"{role} independence not affirmed")
    elif not reviewer.get("reviewer_id"):
        errors.append(f"{role} reviewer_id missing")
    scope = value.get("scope")
    if not isinstance(scope, dict) or not scope.get("reviewed_files") or not scope.get("concerns_checked"):
        errors.append(f"{role} scope is incomplete")
    if value.get("verdict") not in {"pass", "pass_with_findings", "changes_required", "blocked"}:
        errors.append(f"{role} verdict is invalid")
    findings = value.get("findings")
    if not isinstance(findings, list):
        errors.append(f"{role} findings must be an array")
        return value, []
    for index, finding in enumerate(findings, 1):
        prefix = f"{role} finding {index}"
        if not isinstance(finding, dict):
            errors.append(f"{prefix} is not an object")
            continue
        required = {
            "finding_id", "severity", "status", "title", "claim", "impact",
            "evidence", "recommendation", "counterevidence", "confidence",
        }
        if missing := sorted(required - set(finding)):
            errors.append(f"{prefix} missing fields: {', '.join(missing)}")
        if finding.get("severity") not in ALLOWED_SEVERITIES:
            errors.append(f"{prefix} severity is invalid")
        if finding.get("status") not in ALLOWED_FINDING_STATUSES:
            errors.append(f"{prefix} status is invalid")
        if finding.get("confidence") not in {"high", "medium", "low"}:
            errors.append(f"{prefix} confidence is invalid")
        anchors = finding.get("evidence")
        if not isinstance(anchors, list) or not anchors:
            errors.append(f"{prefix} has no evidence anchors")
            continue
        for anchor_index, anchor in enumerate(anchors, 1):
            if not isinstance(anchor, dict):
                errors.append(f"{prefix} anchor {anchor_index} is not an object")
                continue
            try:
                relative = ensure_relative(str(anchor.get("path", "")))
            except ReviewError as exc:
                errors.append(f"{prefix} anchor {anchor_index}: {exc}")
                continue
            start, end = anchor.get("line_start"), anchor.get("line_end")
            count = line_count_for_anchor(repo, target, relative)
            if count is None:
                errors.append(f"{prefix} anchor path absent from target: {relative}")
            elif not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start or end > count:
                errors.append(f"{prefix} anchor range invalid for {relative} ({count} lines)")
    if not isinstance(value.get("limitations"), list):
        errors.append(f"{role} limitations must be an array")
    return value, findings


def validate_adjudication(
    bundle: Path,
    manifest: dict[str, Any],
    submissions: dict[str, dict[str, Any]],
    findings: dict[str, dict[str, Any]],
    errors: list[str],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    path = bundle / "adjudication" / "adjudication.json"
    if not path.is_file():
        errors.append("missing adjudication/adjudication.json")
        return None, []
    value = load_json(path)
    if not isinstance(value, dict):
        errors.append("adjudication is not an object")
        return None, []
    if value.get("review_id") != manifest["review_id"] or not exact_target(value.get("target"), manifest["target"]):
        errors.append("adjudication target or review_id mismatch")
    adjudicator = value.get("adjudicator")
    if not isinstance(adjudicator, dict) or adjudicator.get("independent_from_authors") is not True:
        errors.append("adjudicator independence is missing")
    hashes = value.get("submission_hashes")
    for role, submission in submissions.items():
        expected = sha256_file(bundle / "submissions" / f"{role}.json")
        if not isinstance(hashes, dict) or hashes.get(role) != expected:
            errors.append(f"adjudication submission hash mismatch: {role}")
    dispositions = value.get("finding_dispositions")
    if not isinstance(dispositions, list):
        errors.append("adjudication finding_dispositions must be an array")
        return value, []
    covered: list[str] = []
    for index, item in enumerate(dispositions, 1):
        if not isinstance(item, dict):
            errors.append(f"adjudication disposition {index} is not an object")
            continue
        ids = item.get("finding_ids")
        if not isinstance(ids, list) or not ids:
            errors.append(f"adjudication disposition {index} has no finding_ids")
            continue
        for finding_id in ids:
            if finding_id not in findings:
                errors.append(f"adjudication references unknown finding: {finding_id}")
            covered.append(finding_id)
        if item.get("final_severity") not in ALLOWED_SEVERITIES:
            errors.append(f"adjudication disposition {index} severity is invalid")
        if item.get("final_status") not in ALLOWED_FINDING_STATUSES:
            errors.append(f"adjudication disposition {index} status is invalid")
        if item.get("disposition") not in {"upheld", "merged", "revised", "rejected", "unresolved"}:
            errors.append(f"adjudication disposition {index} is invalid")
        if not item.get("rationale") or not item.get("evidence_basis"):
            errors.append(f"adjudication disposition {index} lacks rationale or evidence")
    if len(covered) != len(set(covered)):
        errors.append("a finding is adjudicated more than once")
    missing = sorted(set(findings) - set(covered))
    if missing:
        errors.append(f"findings missing adjudication: {', '.join(missing)}")
    return value, dispositions


def validate_human_decision(
    bundle: Path,
    manifest: dict[str, Any],
    computed_gate: str,
    errors: list[str],
) -> dict[str, Any] | None:
    path = bundle / "human-decision" / "decision.json"
    if not path.exists():
        return None
    value = load_json(path)
    if not isinstance(value, dict):
        errors.append("human decision is not an object")
        return None
    if value.get("review_id") != manifest["review_id"] or not exact_target(value.get("target"), manifest["target"]):
        errors.append("human decision target or review_id mismatch")
    if value.get("decision_owner") != manifest["decision_owner"] or value.get("actor_type") != "human":
        errors.append("human decision owner or actor_type mismatch")
    decision = value.get("decision")
    if decision not in {"approved", "approved_with_conditions", "rejected", "deferred"}:
        errors.append("human decision value is invalid")
    if computed_gate != "eligible_for_human_decision" and decision in {"approved", "approved_with_conditions"}:
        errors.append("human approval conflicts with unresolved merge gate")
    for key in ("rationale", "decided_at", "reversal_evidence", "authorized_actions", "forbidden_actions"):
        if not value.get(key):
            errors.append(f"human decision missing {key}")
    return value


def validate_bundle(args: argparse.Namespace) -> dict[str, Any]:
    repo = Path(args.repo_root).resolve()
    bundle = Path(args.bundle).resolve()
    errors: list[str] = []
    warnings: list[str] = []
    manifest_path = bundle / "manifest.json"
    if not manifest_path.is_file():
        raise ReviewError(f"Missing manifest: {manifest_path}")
    manifest = load_json(manifest_path)
    if not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA_VERSION:
        raise ReviewError("Manifest schema_version is invalid")
    target = manifest.get("target")
    if not isinstance(target, dict):
        raise ReviewError("Manifest target is invalid")

    try:
        current = target_record(repo, target["base_sha"], target["head_sha"])
        if current != target:
            errors.append("frozen target diff hash mismatch")
    except (KeyError, ReviewError) as exc:
        errors.append(f"frozen target cannot be verified: {exc}")
    validate_packet_index(bundle, errors)

    submissions: dict[str, dict[str, Any]] = {}
    findings: dict[str, dict[str, Any]] = {}
    reviewer_ids: list[str] = []
    for role in REQUIRED_ROLES:
        submission, role_findings = validate_submission(
            repo,
            bundle / "submissions" / f"{role}.json",
            role,
            manifest,
            errors,
        )
        if submission is not None:
            submissions[role] = submission
            reviewer = submission.get("reviewer")
            if isinstance(reviewer, dict) and reviewer.get("reviewer_id"):
                reviewer_ids.append(str(reviewer["reviewer_id"]))
        for finding in role_findings:
            finding_id = finding.get("finding_id")
            if not finding_id:
                continue
            if finding_id in findings:
                errors.append(f"duplicate finding_id: {finding_id}")
            findings[finding_id] = finding
    if len(reviewer_ids) != len(set(reviewer_ids)):
        errors.append("reviewer identities are not unique")

    adjudication, dispositions = validate_adjudication(
        bundle, manifest, submissions, findings, errors
    )
    blocking = [
        item
        for item in dispositions
        if item.get("final_severity") in {"P0", "P1"}
        and item.get("final_status") in {"open", "unresolved"}
    ]
    computed_gate = "blocked" if errors else (
        "changes_required" if blocking else "eligible_for_human_decision"
    )
    if adjudication is not None and adjudication.get("merge_gate") != computed_gate:
        errors.append(
            f"adjudication merge_gate {adjudication.get('merge_gate')} does not match computed {computed_gate}"
        )
        computed_gate = "blocked"
    decision = validate_human_decision(bundle, manifest, computed_gate, errors)
    if errors:
        computed_gate = "blocked"
    decision_status = decision.get("decision") if decision else "provisional"
    if decision is None:
        warnings.append("named-human merge decision is absent")
    warnings.append("behavioral efficacy is outside this review and remains unknown")
    warnings.append("promotion and installation require separate evidence and human gates")

    summary = {
        "schema_version": SCHEMA_VERSION,
        "review_id": manifest["review_id"],
        "target": target,
        "ok": not errors,
        "computed_merge_gate": computed_gate,
        "decision_status": decision_status,
        "required_roles": list(REQUIRED_ROLES),
        "completed_roles": sorted(submissions),
        "finding_counts": {
            severity: sum(1 for item in findings.values() if item.get("severity") == severity)
            for severity in sorted(ALLOWED_SEVERITIES)
        },
        "adjudicated_findings": len(dispositions),
        "unresolved_blocking_findings": len(blocking),
        "behavioral_efficacy": "unknown",
        "promotion_ready": False,
        "installation_ready": False,
        "errors": errors,
        "warnings": warnings,
    }
    if args.write_summary:
        write_json(bundle / "validation-summary.json", summary)
    return summary


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="create a frozen review packet")
    init.add_argument("--repo-root", required=True)
    init.add_argument("--repository", required=True)
    init.add_argument("--base", required=True)
    init.add_argument("--head", required=True)
    init.add_argument("--pr-number", required=True, type=int)
    init.add_argument("--decision-owner", required=True)
    init.add_argument("--requested-by", required=True)
    init.add_argument("--output", required=True)
    init.add_argument("--review-id")
    init.add_argument("--built-at", required=True)
    init.add_argument("--policy", action="append", default=[])
    init.add_argument("--artifact", action="append", default=[])
    init.add_argument("--validation", action="append", default=[])
    validate = sub.add_parser("validate", help="validate a completed review bundle")
    validate.add_argument("--repo-root", required=True)
    validate.add_argument("--bundle", required=True)
    validate.add_argument("--write-summary", action="store_true")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result = init_bundle(args) if args.command == "init" else validate_bundle(args)
    except ReviewError as exc:
        print(canonical_json({"ok": False, "error": str(exc)}), end="")
        return 1
    print(canonical_json(result), end="")
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
