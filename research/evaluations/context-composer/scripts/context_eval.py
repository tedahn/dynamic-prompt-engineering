#!/usr/bin/env python3
"""Deterministic, model-free evaluator for T-005 context composition."""

from __future__ import annotations

import argparse
import json
import re
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "context-composer-v1.json"
FIXTURES_PATH = ROOT / "fixtures" / "fixtures-v1.jsonl"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_fixtures(path: Path = FIXTURES_PATH):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def tokens(value: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9_]+", value.lower())


def item_tokens(item: dict) -> int:
    return len(tokens(item["text"]))


def safe_input(fixture: dict) -> dict:
    """Remove every grader-only field before a condition sees a fixture."""
    return {key: deepcopy(fixture[key]) for key in ("fixture_id", "query", "max_tokens", "allowed_scopes", "signals", "items")}


def pack(items: list[dict], max_tokens: int, enforce_dependencies: bool = False) -> list[dict]:
    selected, used = [], 0
    for item in items:
        selected_ids = {selected_item["id"] for selected_item in selected}
        if enforce_dependencies and not set(item.get("depends_on", [])).issubset(selected_ids):
            continue
        size = item_tokens(item)
        if used + size <= max_tokens:
            selected.append(item)
            used += size
    return selected


def overlap_score(query: str, item: dict) -> float:
    query_terms = set(tokens(query))
    item_terms = set(tokens(item["text"])) | {term.lower() for term in item.get("retrieval_terms", [])}
    return len(query_terms & item_terms) / max(1, len(query_terms))


def composed_rank(query: str, item: dict, config: dict) -> tuple:
    relevance = overlap_score(query, item) * 10
    authority = config["authority_weights"].get(item.get("authority", "untrusted"), 0)
    freshness = config["freshness_weights"].get(item.get("status", "undated"), 0)
    timestamp = item.get("timestamp", "")
    return (relevance + authority + freshness, authority, timestamp, item["id"])


def eligible_items(case: dict, config: dict) -> list[dict]:
    result = []
    for item in case["items"]:
        if config["safety"]["exclude_disallowed_scope"] and item.get("scope") not in case["allowed_scopes"]:
            continue
        if config["safety"]["exclude_injection"] and item.get("injection", False):
            continue
        if config["safety"]["exclude_stale"] and item.get("status") in {"stale", "superseded"}:
            continue
        result.append(item)
    changed = True
    while changed:
        changed = False
        eligible_ids = {item["id"] for item in result}
        retained = [item for item in result if set(item.get("depends_on", [])).issubset(eligible_ids)]
        if len(retained) != len(result):
            changed = True
            result = retained
    return result


def dependency_order(items: list[dict]) -> list[dict]:
    """Place selected prerequisites before dependents without grader knowledge."""
    by_id = {item["id"]: item for item in items}
    ordered: list[dict] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(item: dict) -> None:
        item_id = item["id"]
        if item_id in visited:
            return
        if item_id in visiting:
            raise ValueError(f"dependency cycle at {item_id}")
        visiting.add(item_id)
        for dependency_id in item.get("depends_on", []):
            dependency = by_id.get(dependency_id)
            if dependency is not None:
                visit(dependency)
        visiting.remove(item_id)
        visited.add(item_id)
        ordered.append(item)

    for item in items:
        visit(item)
    return ordered


def select(condition: str, case: dict, config: dict) -> dict:
    items = case["items"]
    route = "composed"
    if condition == "B0_FULL_DUMP":
        route, ranked = "full_context", items
    elif condition == "B1_RECENCY":
        route, ranked = "recency", sorted(items, key=lambda item: (item.get("timestamp", ""), item["id"]), reverse=True)
    elif condition == "B2_KEYWORD_TOPK":
        route = "retrieval"
        ranked = sorted(items, key=lambda item: (overlap_score(case["query"], item), item["id"]), reverse=True)
    elif condition in {"C1_COMPOSED", "C2_ROUTED"}:
        if condition == "C2_ROUTED" and case["signals"].get("needs_clarification"):
            return {"route": "clarify", "selected": [], "used_tokens": 0}
        ranked = sorted(eligible_items(case, config), key=lambda item: composed_rank(case["query"], item, config), reverse=True)
        ranked = dependency_order(ranked)
        total = sum(item_tokens(item) for item in ranked)
        if condition == "C2_ROUTED" and not case["signals"].get("update_sensitive") and len(ranked) <= config["full_context_item_limit"] and total <= case["max_tokens"]:
            route = "full_context"
            ranked = [item for item in items if item in ranked]
    else:
        raise ValueError(f"unknown condition: {condition}")
    selected = pack(ranked, case["max_tokens"], enforce_dependencies=condition in {"C1_COMPOSED", "C2_ROUTED"})
    return {"route": route, "selected": selected, "used_tokens": sum(item_tokens(item) for item in selected)}


def grade(fixture: dict, result: dict) -> dict:
    expected = fixture["expected"]
    selected_ids = [item["id"] for item in result["selected"]]
    selected = set(selected_ids)
    required = set(expected["required_ids"])
    forbidden = set(expected["forbidden_ids"])
    stale = set(expected["stale_ids"])
    recall = 1.0 if not required else len(selected & required) / len(required)
    precision = 1.0 if not selected else len(selected & required) / len(selected)
    ordering_ok = True
    for first, second in expected.get("before", []):
        if first in selected and second in selected and selected_ids.index(first) > selected_ids.index(second):
            ordering_ok = False
    return {
        "required_recall": recall,
        "precision": precision,
        "forbidden_inclusions": sorted(selected & forbidden),
        "stale_inclusions": sorted(selected & stale),
        "budget_ok": result["used_tokens"] <= fixture["max_tokens"],
        "route_ok": result["route"] == expected["route"],
        "ordering_ok": ordering_ok,
        "selected_ids": selected_ids,
        "used_tokens": result["used_tokens"],
    }


def validate(config: dict, fixtures: list[dict]) -> list[str]:
    errors = []
    required = {"fixture_id", "family", "query", "max_tokens", "allowed_scopes", "signals", "items", "expected"}
    ids = []
    for fixture in fixtures:
        ids.append(fixture.get("fixture_id"))
        missing = sorted(required - fixture.keys())
        if missing:
            errors.append(f"{fixture.get('fixture_id', '?')}: missing {missing}")
        item_ids = [item.get("id") for item in fixture.get("items", [])]
        if len(item_ids) != len(set(item_ids)):
            errors.append(f"{fixture.get('fixture_id', '?')}: duplicate item IDs")
        referenced = set(fixture.get("expected", {}).get("required_ids", [])) | set(fixture.get("expected", {}).get("forbidden_ids", [])) | set(fixture.get("expected", {}).get("stale_ids", []))
        if not referenced.issubset(set(item_ids)):
            errors.append(f"{fixture.get('fixture_id', '?')}: expectation references missing item")
        for item in fixture.get("items", []):
            if not set(item.get("depends_on", [])).issubset(set(item_ids)):
                errors.append(f"{fixture.get('fixture_id', '?')}: dependency references missing item")
        try:
            dependency_order(fixture.get("items", []))
        except ValueError as error:
            errors.append(f"{fixture.get('fixture_id', '?')}: {error}")
        if fixture.get("max_tokens", 0) <= 0:
            errors.append(f"{fixture.get('fixture_id', '?')}: invalid budget")
    if len(ids) != len(set(ids)):
        errors.append("duplicate fixture IDs")
    if set(config["conditions"]) != {"B0_FULL_DUMP", "B1_RECENCY", "B2_KEYWORD_TOPK", "C1_COMPOSED", "C2_ROUTED"}:
        errors.append("unexpected condition registry")
    return errors


def evaluate(config: dict, fixtures: list[dict]) -> dict:
    rows = []
    for condition in config["conditions"]:
        for fixture in fixtures:
            result = select(condition, safe_input(fixture), config)
            rows.append({"condition": condition, "fixture_id": fixture["fixture_id"], **grade(fixture, result)})
    summary = {}
    for condition in config["conditions"]:
        subset = [row for row in rows if row["condition"] == condition]
        summary[condition] = {
            "fixtures": len(subset),
            "required_recall_macro": round(sum(row["required_recall"] for row in subset) / len(subset), 4),
            "precision_macro": round(sum(row["precision"] for row in subset) / len(subset), 4),
            "critical_failures": sum(bool(row["forbidden_inclusions"]) for row in subset),
            "stale_failures": sum(bool(row["stale_inclusions"]) for row in subset),
            "budget_failures": sum(not row["budget_ok"] for row in subset),
            "route_accuracy": round(sum(row["route_ok"] for row in subset) / len(subset), 4),
            "ordering_failures": sum(not row["ordering_ok"] for row in subset),
        }
    return {"schema_version": "context-eval-report-v1", "config_version": config["version"], "fixture_count": len(fixtures), "summary": summary, "rows": rows}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("validate", "evaluate"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    config, fixtures = load_json(CONFIG_PATH), load_fixtures()
    errors = validate(config, fixtures)
    if errors:
        print(json.dumps({"valid": False, "errors": errors}, indent=2))
        return 1
    if args.command == "validate":
        print(json.dumps({"valid": True, "fixtures": len(fixtures), "conditions": config["conditions"]}, indent=2))
        return 0
    report = evaluate(config, fixtures)
    output = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(output, encoding="utf-8")
        print(json.dumps({"written": str(args.output), "fixtures": len(fixtures)}))
    else:
        print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
