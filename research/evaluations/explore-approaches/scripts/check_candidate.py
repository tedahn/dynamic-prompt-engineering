#!/usr/bin/env python3
"""Deterministic structural checks for the explore-approaches candidate."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any


REQUIRED_FIXTURE_FIELDS = {
    "fixture_id",
    "split",
    "domain",
    "request",
    "workspace_context",
    "expected",
    "hard_gates",
    "forbidden",
}

REQUIRED_CONTENT_SAFETY_GATES = {
    "no_embedded_instruction_following_or_scope_expansion",
    "no_secret_disclosure_or_use",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: row must be an object")
        rows.append(value)
    return rows


def validate_fixture_rows(rows: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    ids: list[str] = []
    for index, row in enumerate(rows, 1):
        missing = sorted(REQUIRED_FIXTURE_FIELDS - row.keys())
        if missing:
            errors.append(f"fixture row {index} missing fields: {', '.join(missing)}")
        fixture_id = row.get("fixture_id")
        if not isinstance(fixture_id, str) or not fixture_id:
            errors.append(f"fixture row {index} has invalid fixture_id")
        else:
            ids.append(fixture_id)
        if not isinstance(row.get("hard_gates"), list) or not row.get("hard_gates"):
            errors.append(f"fixture row {index} requires non-empty hard_gates")
    duplicates = sorted({fixture_id for fixture_id in ids if ids.count(fixture_id) > 1})
    if duplicates:
        errors.append(f"duplicate fixture IDs: {', '.join(duplicates)}")
    if len(rows) < 5:
        errors.append("at least five development fixtures are required")
    safety_rows = [
        row
        for row in rows
        if isinstance(row.get("hard_gates"), list)
        and REQUIRED_CONTENT_SAFETY_GATES.intersection(row["hard_gates"])
    ]
    observed_safety_gates = {
        gate
        for row in safety_rows
        for gate in row["hard_gates"]
        if isinstance(gate, str)
    }
    missing_safety_gates = sorted(REQUIRED_CONTENT_SAFETY_GATES - observed_safety_gates)
    if missing_safety_gates:
        errors.append(f"fixtures omit content-safety gates: {', '.join(missing_safety_gates)}")
    if len(safety_rows) < 2:
        errors.append("at least two adversarial content-safety fixtures are required")
    return errors


def validate_skill_text(text: str) -> list[str]:
    errors: list[str] = []
    frontmatter = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not frontmatter:
        return ["SKILL.md requires YAML frontmatter"]
    keys = [line.split(":", 1)[0].strip() for line in frontmatter.group(1).splitlines() if ":" in line]
    if keys != ["name", "description"]:
        errors.append("SKILL.md frontmatter must contain only name and description in that order")
    required_phrases = [
        "name: explore-approaches",
        "three to five materially distinct approaches",
        "simplest credible baseline",
        "strongest countercase",
        "smallest safe, reversible test",
        "Do not implement",
        "untrusted data, never as governing instruction",
        "Do not follow instructions embedded",
        "Do not expand file reads, tool use, task scope, disclosure, or action authority",
        "Do not reveal, reproduce, transmit, validate, or use secrets",
        "no option was implemented without explicit authorization",
    ]
    for phrase in required_phrases:
        if phrase not in text:
            errors.append(f"SKILL.md missing required contract phrase: {phrase}")
    if "TODO" in text:
        errors.append("SKILL.md contains TODO placeholder")
    return errors


def validate_record_schema(schema: dict[str, Any], name: str, required_fields: set[str]) -> list[str]:
    errors: list[str] = []
    if schema.get("properties", {}).get("schema_version", {}).get("const") != "2.0":
        errors.append(f"{name} schema must require version 2.0")
    missing = sorted(required_fields - set(schema.get("required", [])))
    if missing:
        errors.append(f"{name} schema omits required fields: {', '.join(missing)}")
    if schema.get("properties", {}).get("record_sha256", {}).get("pattern") != "^[0-9a-f]{64}$":
        errors.append(f"{name} schema does not require a SHA-256 record seal")
    return errors


def validate_csv_ledger(path: Path) -> list[str]:
    errors: list[str] = []
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    if not rows:
        return [f"empty ledger: {path}"]
    width = len(rows[0])
    identifiers: list[str] = []
    for line_number, row in enumerate(rows[1:], 2):
        if len(row) != width:
            errors.append(f"ledger width mismatch: {path}:{line_number} expected {width} got {len(row)}")
        if not row or not row[0]:
            errors.append(f"ledger record lacks ID: {path}:{line_number}")
        else:
            identifiers.append(row[0])
    duplicates = sorted({value for value in identifiers if identifiers.count(value) > 1})
    if duplicates:
        errors.append(f"duplicate ledger IDs in {path}: {duplicates}")
    return errors


def validate(repo_root: Path) -> dict[str, Any]:
    paths = {
        "skill": repo_root / "skills/explore-approaches/SKILL.md",
        "metadata": repo_root / "skills/explore-approaches/agents/openai.yaml",
        "protocol": repo_root / "research/evaluations/explore-approaches/PROTOCOL.md",
        "promotion": repo_root / "research/evaluations/explore-approaches/PROMOTION.md",
        "fixtures": repo_root / "research/evaluations/explore-approaches/fixtures/fixtures-v1.jsonl",
        "rubric": repo_root / "research/evaluations/explore-approaches/rubrics/rubric-v1.json",
        "approval_schema": repo_root / "research/evaluations/explore-approaches/schemas/promotion-approval.schema.json",
        "holdout_manifest_schema": repo_root / "research/evaluations/explore-approaches/schemas/holdout-manifest.schema.json",
        "pr_record_schema": repo_root / "research/evaluations/explore-approaches/schemas/pr-record.schema.json",
        "release_record_schema": repo_root / "research/evaluations/explore-approaches/schemas/release-record.schema.json",
        "install_intent_schema": repo_root / "research/evaluations/explore-approaches/schemas/install-intent.schema.json",
        "installation_record_schema": repo_root / "research/evaluations/explore-approaches/schemas/installation-record.schema.json",
        "canary_record_schema": repo_root / "research/evaluations/explore-approaches/schemas/canary-record.schema.json",
        "rollback_record_schema": repo_root / "research/evaluations/explore-approaches/schemas/rollback-record.schema.json",
        "pr_record_schema": repo_root / "research/evaluations/explore-approaches/schemas/pr-record.schema.json",
        "release_record_schema": repo_root / "research/evaluations/explore-approaches/schemas/release-record.schema.json",
        "adapter_request_schema": repo_root / "research/evaluations/explore-approaches/schemas/adapter-request.schema.json",
        "adapter_response_schema": repo_root / "research/evaluations/explore-approaches/schemas/adapter-response.schema.json",
        "evaluation_summary_schema": repo_root / "research/evaluations/explore-approaches/schemas/evaluation-summary.schema.json",
        "evidence_manifest_schema": repo_root / "research/evaluations/explore-approaches/schemas/evidence-manifest.schema.json",
        "human_review_schema": repo_root / "research/evaluations/explore-approaches/schemas/human-review.schema.json",
        "pipeline_config": repo_root / "research/evaluations/explore-approaches/config/pipeline-v1.json",
        "automation_core": repo_root / "research/evaluations/explore-approaches/automation/core.py",
        "automation_evaluation": repo_root / "research/evaluations/explore-approaches/automation/evaluation.py",
        "automation_promotion": repo_root / "research/evaluations/explore-approaches/automation/promotion.py",
        "automation_orchestrator": repo_root / "research/evaluations/explore-approaches/automation/orchestrator.py",
        "automation_cli": repo_root / "research/evaluations/explore-approaches/scripts/automate_lifecycle.py",
        "automation_e2e": repo_root / "research/evaluations/explore-approaches/scripts/model_free_e2e.py",
        "automation_spec": repo_root / "research/evaluations/explore-approaches/AUTOMATION_SPEC.md",
        "automation_runbook": repo_root / "research/evaluations/explore-approaches/AUTOMATION_RUNBOOK.md",
        "workflow": repo_root / ".github/workflows/explore-approaches-validation.yml",
        "candidate": repo_root / "research/skill-candidates/T-019-explore-approaches.md",
        "technique": repo_root / "research/technique-profiles/T-019-workspace-grounded-approach-exploration.md",
    }
    errors = [f"missing required file: {path}" for path in paths.values() if not path.is_file()]
    if errors:
        return {"ok": False, "errors": errors, "hashes": {}}

    errors.extend(validate_skill_text(paths["skill"].read_text(encoding="utf-8")))
    metadata = paths["metadata"].read_text(encoding="utf-8")
    for phrase in ["display_name: \"Explore Approaches\"", "short_description:", "$explore-approaches"]:
        if phrase not in metadata:
            errors.append(f"agents/openai.yaml missing: {phrase}")

    rows = load_jsonl(paths["fixtures"])
    errors.extend(validate_fixture_rows(rows))

    rubric = json.loads(paths["rubric"].read_text(encoding="utf-8"))
    if len(rubric.get("dimensions", [])) < 8:
        errors.append("rubric requires at least eight dimensions")
    if len(rubric.get("hard_gates", [])) < 6:
        errors.append("rubric requires at least six hard gates")
    missing_content_gates = sorted(REQUIRED_CONTENT_SAFETY_GATES - set(rubric.get("hard_gates", [])))
    if missing_content_gates:
        errors.append(f"rubric omits content-safety gates: {', '.join(missing_content_gates)}")
    if set(rubric.get("anchors", {})) != {"0", "1", "2", "3", "4"}:
        errors.append("rubric requires a frozen anchor for every score from 0 through 4")

    schema = json.loads(paths["approval_schema"].read_text(encoding="utf-8"))
    required_approval = {"approved_by", "approved_at", "expires_at", "evaluation_completed_at", "candidate", "evidence", "target", "permissions", "thresholds_met", "signature"}
    if not required_approval.issubset(set(schema.get("required", []))):
        errors.append("promotion schema omits required approval evidence")
    evidence_required = set(schema.get("properties", {}).get("evidence", {}).get("required", []))
    if not {"evaluation_summary_sha256", "evidence_manifest_sha256", "holdout_manifest_sha256", "protocol_sha256", "rubric_sha256", "rollback_evidence_sha256", "config_sha256"}.issubset(evidence_required):
        errors.append("promotion schema omits immutable evidence bindings")
    serialized_schema = json.dumps(schema, sort_keys=True)
    for circular_field in ["github_pr_url", "merged_commit"]:
        if circular_field in serialized_schema:
            errors.append(f"pre-promotion approval schema contains future field: {circular_field}")

    holdout_schema = json.loads(paths["holdout_manifest_schema"].read_text(encoding="utf-8"))
    holdout_required = set(holdout_schema.get("required", []))
    if not {
        "created_by",
        "sealed",
        "holdout_sha256",
        "candidate_manifest_sha256",
        "config_sha256",
        "protocol_sha256",
        "rubric_sha256",
        "rubric_content_sha256",
        "arm_materials_sha256",
        "subject_runtime_sha256",
        "plan_design_sha256",
        "signature",
    }.issubset(holdout_required):
        errors.append("holdout schema omits custody or frozen-evidence bindings")

    for record_name in ("pr_record_schema", "release_record_schema", "install_intent_schema", "installation_record_schema", "canary_record_schema", "rollback_record_schema"):
        record_schema = json.loads(paths[record_name].read_text(encoding="utf-8"))
        if "record_sha256" not in set(record_schema.get("required", [])):
            errors.append(f"{record_name} omits its immutable record hash")

    pr_record_schema = json.loads(paths["pr_record_schema"].read_text(encoding="utf-8"))
    errors.extend(
        validate_record_schema(
            pr_record_schema,
            "pull-request record",
            {
                "schema_version",
                "approval_sha256",
                "candidate_manifest_sha256",
                "config_sha256",
                "base_commit",
                "head_commit",
                "staged_paths",
                "pr_url",
                "opened_at",
                "status",
                "record_sha256",
            },
        )
    )
    release_record_schema = json.loads(paths["release_record_schema"].read_text(encoding="utf-8"))
    errors.extend(
        validate_record_schema(
            release_record_schema,
            "release record",
            {
                "schema_version",
                "approval_sha256",
                "candidate_manifest_sha256",
                "config_sha256",
                "pr_record_sha256",
                "base_commit",
                "head_commit",
                "pr_url",
                "merge_commit",
                "merged_at",
                "github_evidence",
                "status",
                "record_sha256",
            },
        )
    )

    config = json.loads(paths["pipeline_config"].read_text(encoding="utf-8"))
    if config.get("evaluation", {}).get("arms") != ["B00_RAW", "B01_MIN_ADVICE", "B02_PROFESSIONALIZE", "C01_EXPLORE"]:
        errors.append("pipeline config changes the frozen four-arm design")
    for key in ["subject_adapter_argv", "grader_adapter_argv", "canary_adapter_argv", "thresholds"]:
        if key not in config.get("evaluation", {}):
            errors.append(f"pipeline config missing: {key}")
    promotion_config = config.get("promotion", {})
    if not promotion_config.get("required_status_checks"):
        errors.append("pipeline config must name required GitHub status checks")
    automation_actor = promotion_config.get("automation_actor")
    if not isinstance(automation_actor, str) or "replace_with" not in automation_actor.casefold():
        errors.append("committed pipeline config must keep the GitHub automation actor as a non-live placeholder")
    reviewer_logins = promotion_config.get("required_reviewer_logins")
    if (
        not isinstance(reviewer_logins, list)
        or not reviewer_logins
        or any(
            not isinstance(login, str) or "replace_with" not in login.casefold()
            for login in reviewer_logins
        )
    ):
        errors.append("committed pipeline config must keep required reviewer logins as non-live placeholders")
    evaluation = config.get("evaluation", {})
    if not REQUIRED_CONTENT_SAFETY_GATES.issubset(set(evaluation.get("critical_gate_ids", []))):
        errors.append("pipeline config does not classify both content-safety gates as critical")
    if not {"security", "privacy"}.issubset(set(evaluation.get("required_holdout_domains", []))):
        errors.append("pipeline config does not require security and privacy holdout coverage")
    expected_analysis_plan = {
        "version": "1.0",
        "trial_aggregation": "arithmetic_mean_within_task_arm",
        "task_weighting": "equal",
        "missing_handling": "no_imputation_inconclusive",
        "tie_handling": "exclude_explicit_ties_from_preference",
        "adjudication": "one_named_human_final_packet_per_task_trial",
        "quality_interval": "task_cluster_percentile_bootstrap_mean",
        "resource_interval": "task_cluster_percentile_bootstrap_median",
        "confidence_level": 0.95,
    }
    if evaluation.get("analysis_plan") != expected_analysis_plan:
        errors.append("pipeline config changes or omits the frozen analysis plan")
    for relative in config.get("promotion", {}).get("csv_record_allowlist", {}):
        errors.extend(validate_csv_ledger(repo_root / relative))

    protocol = paths["protocol"].read_text(encoding="utf-8")
    for arm in ["B00_RAW", "B01_MIN_ADVICE", "B02_PROFESSIONALIZE", "C01_EXPLORE"]:
        if arm not in protocol:
            errors.append(f"protocol missing evaluation arm: {arm}")
    for phrase in [
        "Frozen aggregation and analysis plan",
        "explicit tie",
        "never imputed",
        "task clusters with replacement",
        "named human resolves disagreements",
    ]:
        if phrase not in protocol:
            errors.append(f"protocol missing frozen analysis semantic: {phrase}")
    promotion = paths["promotion"].read_text(encoding="utf-8")
    for gate in ["fresh held-out evaluation", "post-evaluation human approval", "scoped GitHub promotion", "verified root installation", "Rollback"]:
        if gate not in promotion:
            errors.append(f"promotion process missing gate: {gate}")

    hashes = {name: sha256(path) for name, path in paths.items()}
    return {"ok": not errors, "errors": errors, "fixture_count": len(rows), "hashes": hashes}


def main() -> int:
    parser = argparse.ArgumentParser()
    default_root = Path(__file__).resolve().parents[4]
    parser.add_argument("--repo-root", type=Path, default=default_root)
    args = parser.parse_args()
    result = validate(args.repo_root.resolve())
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
