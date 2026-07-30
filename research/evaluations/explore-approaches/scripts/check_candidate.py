#!/usr/bin/env python3
"""Deterministic structural checks for the explore-approaches candidate."""

from __future__ import annotations

import argparse
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
        "no option was implemented without explicit authorization",
    ]
    for phrase in required_phrases:
        if phrase not in text:
            errors.append(f"SKILL.md missing required contract phrase: {phrase}")
    if "TODO" in text:
        errors.append("SKILL.md contains TODO placeholder")
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

    schema = json.loads(paths["approval_schema"].read_text(encoding="utf-8"))
    required_approval = {"approved_by", "approved_at", "candidate_commit", "evaluation_summary_sha256", "github_pr_url", "merged_commit", "rollback_tested"}
    if not required_approval.issubset(set(schema.get("required", []))):
        errors.append("promotion schema omits required approval evidence")

    protocol = paths["protocol"].read_text(encoding="utf-8")
    for arm in ["B00_RAW", "B01_MIN_ADVICE", "B02_PROFESSIONALIZE", "C01_EXPLORE"]:
        if arm not in protocol:
            errors.append(f"protocol missing evaluation arm: {arm}")
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
