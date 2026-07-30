#!/usr/bin/env python3
"""Deterministic, model-free evaluator for T-005 context composition."""

from __future__ import annotations

import argparse
import json
import re
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "context-composer-v2.json"
FIXTURES_PATH = ROOT / "fixtures" / "fixtures-v1.jsonl"
SCHEMA_PATH = ROOT / "schemas" / "fixture.schema.json"
FIXTURE_PRODUCER = "context-fixture-author-v1"
SUPPORTED_SCHEMA_KEYWORDS = {
    "$schema",
    "title",
    "type",
    "required",
    "properties",
    "additionalProperties",
    "pattern",
    "minLength",
    "minimum",
    "minItems",
    "maxItems",
    "uniqueItems",
    "enum",
    "items",
}


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_fixtures(path: Path = FIXTURES_PATH):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def schema_vocabulary_errors(schema, path: str = "$schema") -> list[str]:
    """Reject schema keywords or shapes this standard-library validator cannot enforce."""
    if not isinstance(schema, dict):
        return [f"{path}: schema must be an object"]
    errors = [
        f"{path}: unsupported schema keyword {keyword}"
        for keyword in sorted(set(schema) - SUPPORTED_SCHEMA_KEYWORDS)
    ]
    schema_type = schema.get("type")
    if schema_type not in {"object", "array", "string", "integer", "boolean"}:
        errors.append(f"{path}.type: unsupported or missing schema type")
    if "$schema" in schema and not isinstance(schema["$schema"], str):
        errors.append(f"{path}.$schema: must be a string")
    if "title" in schema and not isinstance(schema["title"], str):
        errors.append(f"{path}.title: must be a string")
    if "required" in schema and (
        not isinstance(schema["required"], list)
        or any(not isinstance(field, str) for field in schema["required"])
    ):
        errors.append(f"{path}.required: must be an array of strings")
    if "enum" in schema and not isinstance(schema["enum"], list):
        errors.append(f"{path}.enum: must be an array")
    if "pattern" in schema and not isinstance(schema["pattern"], str):
        errors.append(f"{path}.pattern: must be a string")
    for keyword in ("minLength", "minimum", "minItems", "maxItems"):
        if keyword in schema and (
            not isinstance(schema[keyword], int)
            or isinstance(schema[keyword], bool)
            or schema[keyword] < 0
        ):
            errors.append(f"{path}.{keyword}: must be a nonnegative integer")
    if "uniqueItems" in schema and not isinstance(schema["uniqueItems"], bool):
        errors.append(f"{path}.uniqueItems: must be boolean")
    properties = schema.get("properties", {})
    if not isinstance(properties, dict):
        errors.append(f"{path}.properties: must be an object")
    else:
        for field, child_schema in properties.items():
            errors.extend(schema_vocabulary_errors(child_schema, f"{path}.properties.{field}"))
    if "items" in schema:
        errors.extend(schema_vocabulary_errors(schema["items"], f"{path}.items"))
    if "additionalProperties" in schema and not isinstance(schema["additionalProperties"], bool):
        errors.append(f"{path}.additionalProperties: only boolean values are supported")
    return errors


def schema_errors(value, schema: dict, path: str = "$") -> list[str]:
    """Validate the JSON Schema subset used by the committed fixture schema."""
    errors: list[str] = []
    expected_type = schema.get("type")
    type_checks = {
        "object": lambda candidate: isinstance(candidate, dict),
        "array": lambda candidate: isinstance(candidate, list),
        "string": lambda candidate: isinstance(candidate, str),
        "integer": lambda candidate: isinstance(candidate, int) and not isinstance(candidate, bool),
        "boolean": lambda candidate: isinstance(candidate, bool),
    }
    if expected_type in type_checks and not type_checks[expected_type](value):
        return [f"{path}: expected {expected_type}"]
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: value is not in the allowed enum")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: string is shorter than minLength")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            errors.append(f"{path}: string does not match pattern")
    if isinstance(value, int) and not isinstance(value, bool) and value < schema.get("minimum", value):
        errors.append(f"{path}: integer is below minimum")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: array is shorter than minItems")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: array is longer than maxItems")
        if schema.get("uniqueItems"):
            normalized = [json.dumps(item, sort_keys=True, separators=(",", ":")) for item in value]
            if len(normalized) != len(set(normalized)):
                errors.append(f"{path}: array items must be unique")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                errors.extend(schema_errors(item, item_schema, f"{path}[{index}]"))
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for field in schema.get("required", []):
            if field not in value:
                errors.append(f"{path}: missing required field {field}")
        if schema.get("additionalProperties") is False:
            for field in sorted(set(value) - set(properties)):
                errors.append(f"{path}: unsupported field {field}")
        for field, child_schema in properties.items():
            if field in value:
                errors.extend(schema_errors(value[field], child_schema, f"{path}.{field}"))
    return errors


def tokens(value: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9_]+", value.lower())


def item_tokens(item: dict) -> int:
    return len(tokens(item["text"]))


def safe_input(fixture: dict) -> dict:
    """Remove grader fields and classify items through the trusted fixture producer."""
    case = {key: deepcopy(fixture[key]) for key in ("fixture_id", "query", "max_tokens", "allowed_scopes", "signals", "items")}
    for item in case["items"]:
        item["source"] = f"fixture://{case['fixture_id']}/{item['id']}"
        item["security"] = {
            "producer": FIXTURE_PRODUCER,
            "trust": "untrusted" if item["authority"] == "untrusted" else "trusted",
            "sensitivity": "secret" if item["scope"] == "restricted" else "public",
            "content_type": "instruction" if item.get("injection", False) else "evidence",
        }
    return case


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
        security = item["security"]
        if config["safety"]["exclude_untrusted"] and security["trust"] != "trusted":
            continue
        if config["safety"]["exclude_secret"] and security["sensitivity"] == "secret":
            continue
        if config["safety"]["exclude_instruction"] and security["content_type"] == "instruction":
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


def validate(config: dict, fixtures: list[dict], schema: dict | None = None) -> list[str]:
    errors = []
    if config.get("trusted_fixture_producer") != FIXTURE_PRODUCER:
        errors.append("configured trusted fixture producer does not match the evaluator producer")
    required_safety = {"exclude_injection", "exclude_disallowed_scope", "exclude_stale", "exclude_untrusted", "exclude_secret", "exclude_instruction"}
    if set(config.get("safety", {})) != required_safety or any(
        not isinstance(value, bool) for value in config.get("safety", {}).values()
    ):
        errors.append("invalid safety configuration")
    schema = load_json(SCHEMA_PATH) if schema is None else schema
    vocabulary_errors = schema_vocabulary_errors(schema)
    if vocabulary_errors:
        return errors + vocabulary_errors
    ids = []
    for index, fixture in enumerate(fixtures):
        structural_errors = schema_errors(fixture, schema)
        errors.extend(f"fixture[{index}]: {error}" for error in structural_errors)
        if structural_errors:
            continue
        ids.append(fixture.get("fixture_id"))
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
