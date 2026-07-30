#!/usr/bin/env python3
"""Create a deterministic context-pack-v1 manifest from structured evidence."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

AUTHORITY = {"canonical": 3.0, "primary": 2.0, "secondary": 1.0, "untrusted": 0.0}
FRESHNESS = {"current": 2.0, "undated": 0.5, "stale": -3.0, "superseded": -5.0}
TRUSTED_METADATA_PRODUCERS = {"context-fixture-author-v1", "workspace-evidence-indexer-v1"}
TRUST = {"trusted", "untrusted"}
SENSITIVITY = {"public", "internal", "confidential", "secret"}
CONTENT_TYPES = {"evidence", "instruction"}
FULL_CONTEXT_ITEM_LIMIT = 4


class ContractError(ValueError):
    pass


def words(value: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9_]+", value.lower())


def token_count(item: dict) -> int:
    return len(words(item["text"]))


def validate(payload: dict) -> None:
    if not isinstance(payload, dict):
        raise ContractError("payload must be an object")
    required = {"query", "max_tokens", "allowed_scopes", "items"}
    missing = required - payload.keys()
    if missing:
        raise ContractError(f"missing fields: {sorted(missing)}")
    if not isinstance(payload["query"], str) or not payload["query"].strip():
        raise ContractError("query must be nonempty")
    if not isinstance(payload["max_tokens"], int) or isinstance(payload["max_tokens"], bool) or payload["max_tokens"] <= 0:
        raise ContractError("max_tokens must be a positive integer")
    if not isinstance(payload["allowed_scopes"], list) or not payload["allowed_scopes"]:
        raise ContractError("allowed_scopes must be a nonempty list")
    if any(not isinstance(scope, str) or not scope.strip() for scope in payload["allowed_scopes"]):
        raise ContractError("allowed_scopes must contain nonempty strings")
    signals = payload.get("signals", {})
    if not isinstance(signals, dict):
        raise ContractError("signals must be an object")
    allowed_signals = {"needs_clarification", "update_sensitive", "allow_stale_history"}
    if set(signals) - allowed_signals:
        raise ContractError(f"signals has unsupported fields: {sorted(set(signals) - allowed_signals)}")
    if any(not isinstance(value, bool) for value in signals.values()):
        raise ContractError("signal values must be boolean")
    if not isinstance(payload["items"], list):
        raise ContractError("items must be a list")
    ids = []
    for index, item in enumerate(payload["items"]):
        if not isinstance(item, dict):
            raise ContractError(f"item {index} must be an object")
        for field in ("id", "text", "source", "scope", "status", "authority", "security"):
            if field not in item:
                raise ContractError(f"item {index} missing {field}")
        for field in ("id", "text", "source", "scope"):
            if not isinstance(item[field], str) or not item[field].strip():
                raise ContractError(f"item {index} {field} must be a nonempty string")
        if not isinstance(item["authority"], str) or item["authority"] not in AUTHORITY:
            raise ContractError(f"item {item['id']} has unsupported authority")
        if not isinstance(item["status"], str) or item["status"] not in FRESHNESS:
            raise ContractError(f"item {item['id']} has unsupported status")
        security = item["security"]
        required_security = {"producer", "trust", "sensitivity", "content_type"}
        if not isinstance(security, dict) or set(security) != required_security:
            raise ContractError(f"item {item['id']} security metadata must contain exactly {sorted(required_security)}")
        if not isinstance(security["producer"], str) or security["producer"] not in TRUSTED_METADATA_PRODUCERS:
            raise ContractError(f"item {item['id']} has an untrusted metadata producer")
        if not isinstance(security["trust"], str) or security["trust"] not in TRUST:
            raise ContractError(f"item {item['id']} has unsupported trust metadata")
        if not isinstance(security["sensitivity"], str) or security["sensitivity"] not in SENSITIVITY:
            raise ContractError(f"item {item['id']} has unsupported sensitivity metadata")
        if not isinstance(security["content_type"], str) or security["content_type"] not in CONTENT_TYPES:
            raise ContractError(f"item {item['id']} has unsupported content_type metadata")
        if "injection" in item and not isinstance(item["injection"], bool):
            raise ContractError(f"item {item['id']} injection must be boolean")
        for field in ("retrieval_terms", "depends_on"):
            if field in item and (
                not isinstance(item[field], list)
                or any(not isinstance(value, str) or not value for value in item[field])
            ):
                raise ContractError(f"item {item['id']} {field} must contain nonempty strings")
        ids.append(item["id"])
    if len(ids) != len(set(ids)):
        raise ContractError("item IDs must be unique")
    known = set(ids)
    for item in payload["items"]:
        if not set(item.get("depends_on", [])).issubset(known):
            raise ContractError(f"item {item['id']} has an unknown dependency")
    dependency_order(payload["items"])


def relevance(query: str, item: dict) -> float:
    query_terms = set(words(query))
    evidence_terms = set(words(item["text"])) | {str(term).lower() for term in item.get("retrieval_terms", [])}
    return len(query_terms & evidence_terms) / max(1, len(query_terms))


def rank_key(query: str, item: dict) -> tuple:
    authority = AUTHORITY[item["authority"]]
    score = relevance(query, item) * 10 + authority + FRESHNESS[item["status"]]
    return score, authority, item.get("timestamp", ""), item["id"]


def dependency_order(items: list[dict]) -> list[dict]:
    by_id = {item["id"]: item for item in items}
    ordered, visiting, visited = [], set(), set()

    def visit(item: dict) -> None:
        item_id = item["id"]
        if item_id in visited:
            return
        if item_id in visiting:
            raise ContractError(f"dependency cycle at {item_id}")
        visiting.add(item_id)
        for dependency_id in item.get("depends_on", []):
            if dependency_id in by_id:
                visit(by_id[dependency_id])
        visiting.remove(item_id)
        visited.add(item_id)
        ordered.append(item)

    for item in items:
        visit(item)
    return ordered


def filter_items(payload: dict) -> tuple[list[dict], list[dict]]:
    eligible, excluded = [], []
    signals = payload.get("signals", {})
    for item in payload["items"]:
        reason = None
        if item["scope"] not in payload["allowed_scopes"]:
            reason = "disallowed_scope"
        elif item["security"]["trust"] != "trusted":
            reason = "untrusted_source"
        elif item["security"]["sensitivity"] == "secret":
            reason = "secret"
        elif item["security"]["content_type"] == "instruction":
            reason = "instruction_bearing"
        elif item.get("injection", False):
            reason = "retrieved_injection"
        elif item["status"] == "superseded":
            reason = "superseded"
        elif item["status"] == "stale" and not signals.get("allow_stale_history", False):
            reason = "stale"
        if reason:
            excluded.append({"id": item["id"], "reason": reason})
        else:
            eligible.append(item)
    changed = True
    while changed:
        changed = False
        eligible_ids = {item["id"] for item in eligible}
        retained = []
        for item in eligible:
            missing = sorted(set(item.get("depends_on", [])) - eligible_ids)
            if missing:
                excluded.append({"id": item["id"], "reason": f"missing_dependency:{','.join(missing)}"})
                changed = True
            else:
                retained.append(item)
        eligible = retained
    return eligible, excluded


def compose(payload: dict) -> dict:
    validate(payload)
    signals = payload.get("signals", {})
    if signals.get("needs_clarification", False):
        return {"schema_version": "context-pack-v1", "route": "clarify", "query": payload["query"], "max_tokens": payload["max_tokens"], "used_tokens": 0, "selected": [], "excluded": [], "omitted": [], "warnings": ["Material ambiguity must be resolved before context selection."]}

    eligible, excluded = filter_items(payload)
    total = sum(token_count(item) for item in eligible)
    if not signals.get("update_sensitive", False) and len(eligible) <= FULL_CONTEXT_ITEM_LIMIT and total <= payload["max_tokens"]:
        route, ranked = "full_context", [item for item in payload["items"] if item in eligible]
    else:
        route = "composed"
        ranked = sorted(eligible, key=lambda item: rank_key(payload["query"], item), reverse=True)
        ranked = dependency_order(ranked)

    selected, omitted, used = [], [], 0
    for item in ranked:
        selected_ids = {selected_item["id"] for selected_item in selected}
        missing_selected = sorted(set(item.get("depends_on", [])) - selected_ids)
        if missing_selected:
            omitted.append({"id": item["id"], "reason": f"missing_selected_dependency:{','.join(missing_selected)}"})
            continue
        size = token_count(item)
        if used + size <= payload["max_tokens"]:
            selected.append({"id": item["id"], "text": item["text"], "source": item["source"], "security": dict(item["security"]), "authority": item["authority"], "status": item["status"], "scope": item["scope"], "timestamp": item.get("timestamp", ""), "depends_on": item.get("depends_on", []), "approx_tokens": size, "relevance": round(relevance(payload["query"], item), 4)})
            used += size
        else:
            omitted.append({"id": item["id"], "reason": "budget"})

    warnings = []
    if signals.get("allow_stale_history", False) and any(item["status"] == "stale" for item in eligible):
        warnings.append("Stale material was explicitly retained for historical context.")
    if omitted:
        warnings.append("Some eligible evidence was omitted by the context budget.")
    return {"schema_version": "context-pack-v1", "route": route, "query": payload["query"], "max_tokens": payload["max_tokens"], "used_tokens": used, "selected": selected, "excluded": excluded, "omitted": omitted, "warnings": warnings}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    args = parser.parse_args()
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        print(json.dumps(compose(payload), indent=2, sort_keys=True))
        return 0
    except (OSError, json.JSONDecodeError, ContractError) as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
