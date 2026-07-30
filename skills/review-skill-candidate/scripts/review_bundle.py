#!/usr/bin/env python3
"""Build and validate immutable, role-separated skill review bundles."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
from typing import Any
import unicodedata
from urllib.parse import quote_from_bytes


SCHEMA_VERSION = "1.1"
LEGACY_SCHEMA_VERSION = "1.0"
LEGACY_PACKET_CONTRACTS = {
    "96f8a21cf9748432187e25e8a6ce787a8ea49be941bea42bc1418567359ebc9c": {
        "review_id": "PR-001-8371f0f9634b",
        "repository": "tedahn/dynamic-prompt-engineering",
        "pull_request": 1,
        "target": {
            "base_sha": "506850f0d4cf7b21990231b40c560864fd82e9e2",
            "head_sha": "8371f0f9634bf86e3417bae09772418034239969",
            "diff_sha256": "24048aec899e9298b8fa5b08893e428e9de03aba518f9a99431f565c9a7943ca",
        },
    },
}
REQUIRED_ROLES = (
    "evidence-methodology",
    "engineering-reproducibility",
    "skill-safety-operations",
)
MARKDOWN_DISPLAY_PREFIX = "utf8pct-v1:"
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
SUPPORTED_SCHEMA_KEYWORDS = {
    "$defs", "$id", "$ref", "$schema", "additionalProperties", "const",
    "enum", "items", "minimum", "minItems", "minLength", "pattern",
    "properties", "required", "title", "type", "uniqueItems",
}
PACKET_SCHEMA_PATHS = {
    "review_submission": "schemas/review-submission.schema.json",
    "adjudication": "schemas/adjudication.schema.json",
    "human_decision": "schemas/human-decision.schema.json",
}


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


def canonical_identity(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = unicodedata.normalize("NFKC", value).strip().casefold()
    return normalized or None


def markdown_display_atom(value: Any) -> str:
    """Return a reversible Markdown-safe display form for an untrusted scalar.

    Packet JSON remains canonical. Generated Markdown uses this explicitly tagged,
    UTF-8 percent encoding so repository paths and claims cannot create headings,
    lists, fences, links, HTML, control characters, or additional table cells.
    """
    if not isinstance(value, str):
        value = str(value)
    return MARKDOWN_DISPLAY_PREFIX + quote_from_bytes(value.encode("utf-8"), safe=b"")


def sanitized_git_diagnostic(repo: Path, value: bytes | str, limit: int = 300) -> str:
    text = value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)
    text = text.replace(str(repo), "<repo>")
    text = " ".join(
        "".join(character if character.isprintable() else " " for character in text).split()
    )
    return (text[:limit].rstrip() + "...") if len(text) > limit else (text or "no diagnostic")


def run_git_bytes(
    repo: Path,
    operation: str,
    *args: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    safe_env = sanitized_git_environment(env)
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo,
            check=False,
            capture_output=True,
            env=safe_env,
        )
    except OSError as exc:
        diagnostic = sanitized_git_diagnostic(repo, str(exc))
        raise ReviewError(f"git {operation} could not start: {diagnostic}") from exc
    if result.returncode != 0:
        diagnostic = sanitized_git_diagnostic(repo, result.stderr)
        raise ReviewError(
            f"git {operation} failed with exit {result.returncode}: {diagnostic}"
        )
    return result


def sanitized_git_environment(source: dict[str, str] | None = None) -> dict[str, str]:
    source = os.environ if source is None else source
    # Ambient Git variables can redirect repository discovery, object reads, refs,
    # the index, attributes, or diff behavior. Remove the complete namespace and
    # add back only controls owned by this validator.
    env = {key: value for key, value in source.items() if not key.startswith("GIT_")}
    env.update({
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "LC_ALL": "C",
    })
    return env


def git(
    repo: Path,
    *args: str,
    binary: bool = False,
    env: dict[str, str] | None = None,
) -> bytes | str:
    safe_env = sanitized_git_environment(env)
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=repo,
            check=False,
            capture_output=True,
            text=not binary,
            env=safe_env,
        )
    except OSError as exc:
        diagnostic = sanitized_git_diagnostic(repo, str(exc))
        raise ReviewError(f"git {' '.join(args)} could not start: {diagnostic}") from exc
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", "replace") if binary else result.stderr
        diagnostic = sanitized_git_diagnostic(repo, stderr)
        raise ReviewError(f"git {' '.join(args)} failed: {diagnostic}")
    return result.stdout


def resolve_ref(repo: Path, ref: str, env: dict[str, str] | None = None) -> str:
    return str(
        git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}", env=env)
    ).strip()


def ensure_relative(path_text: str) -> str:
    path = PurePosixPath(path_text)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ReviewError(f"Path must be repository-relative: {path_text}")
    return path.as_posix()


def blob_at(repo: Path, commit: str, relative: str) -> bytes | None:
    relative = ensure_relative(relative)
    env = sanitized_git_environment()
    probe = run_git_bytes(
        repo,
        "ls-tree probe",
        "--literal-pathspecs",
        "ls-tree",
        "-z",
        "--full-tree",
        commit,
        "--",
        relative,
        env=env,
    )
    entries = [entry for entry in probe.stdout.split(b"\0") if entry]
    if not entries:
        return None
    if len(entries) != 1 or b"\t" not in entries[0]:
        raise ReviewError("git ls-tree probe returned an ambiguous result")
    metadata, listed_path = entries[0].split(b"\t", 1)
    fields = metadata.split(b" ")
    if len(fields) != 3 or listed_path != os.fsencode(relative):
        raise ReviewError("git ls-tree probe returned a malformed result")
    _mode, object_type, object_id = fields
    if object_type != b"blob" or not re.fullmatch(rb"[0-9a-f]{40,64}", object_id):
        kind = sanitized_git_diagnostic(repo, object_type, limit=30)
        raise ReviewError(f"git ls-tree probe resolved a non-blob object: {kind}")
    result = run_git_bytes(
        repo,
        "cat-file blob read",
        "cat-file",
        "blob",
        object_id.decode("ascii"),
        env=env,
    )
    return result.stdout


def json_fingerprint(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def schema_type_matches(value: Any, expected: str) -> bool:
    checks = {
        "array": isinstance(value, list),
        "boolean": isinstance(value, bool),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "null": value is None,
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "object": isinstance(value, dict),
        "string": isinstance(value, str),
    }
    if expected not in checks:
        raise ReviewError(f"Unsupported JSON Schema type: {expected}")
    return checks[expected]


def assert_supported_schema(schema: Any, schema_path: str = "#") -> None:
    if not isinstance(schema, dict):
        raise ReviewError(f"Unsupported JSON Schema node at {schema_path}")
    unsupported = sorted(set(schema) - SUPPORTED_SCHEMA_KEYWORDS)
    if unsupported:
        raise ReviewError(
            f"Unsupported JSON Schema keyword at {schema_path}: {', '.join(unsupported)}"
        )
    for container in ("properties", "$defs"):
        children = schema.get(container, {})
        if not isinstance(children, dict):
            raise ReviewError(f"Invalid JSON Schema {container} at {schema_path}")
        for key, child in children.items():
            assert_supported_schema(child, f"{schema_path}/{container}/{key}")
    if "items" in schema:
        assert_supported_schema(schema["items"], f"{schema_path}/items")
    additional = schema.get("additionalProperties", True)
    if not isinstance(additional, bool):
        assert_supported_schema(additional, f"{schema_path}/additionalProperties")


def resolve_schema_ref(root_schema: dict[str, Any], reference: Any) -> dict[str, Any]:
    if not isinstance(reference, str) or not reference.startswith("#/"):
        raise ReviewError(f"Unsupported non-local JSON Schema reference: {reference!r}")
    current: Any = root_schema
    for raw_token in reference[2:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or token not in current:
            raise ReviewError(f"Unresolvable JSON Schema reference: {reference}")
        current = current[token]
    if not isinstance(current, dict):
        raise ReviewError(f"JSON Schema reference is not an object: {reference}")
    return current


def instance_path(parent: str, key: str) -> str:
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", key):
        return f"{parent}.{key}"
    return f"{parent}[{json.dumps(key, ensure_ascii=False)}]"


def validate_schema_node(
    value: Any,
    schema: dict[str, Any] | None,
    root_schema: dict[str, Any],
    path: str,
    errors: list[str],
) -> None:
    if "$ref" in schema:
        validate_schema_node(
            value,
            resolve_schema_ref(root_schema, schema["$ref"]),
            root_schema,
            path,
            errors,
        )
    if "const" in schema and json_fingerprint(value) != json_fingerprint(schema["const"]):
        errors.append(f"{path}: must equal {schema['const']!r}")
    if "enum" in schema:
        allowed = {json_fingerprint(item) for item in schema["enum"]}
        if json_fingerprint(value) not in allowed:
            errors.append(f"{path}: value is not in the allowed enum")

    expected_type = schema.get("type")
    if expected_type is not None:
        type_names = expected_type if isinstance(expected_type, list) else [expected_type]
        if not type_names or not all(isinstance(item, str) for item in type_names):
            raise ReviewError(f"Invalid JSON Schema type at {path}")
        if not any(schema_type_matches(value, item) for item in type_names):
            errors.append(f"{path}: expected type {' or '.join(type_names)}")
            return

    if isinstance(value, dict):
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
            raise ReviewError(f"Invalid JSON Schema required list at {path}")
        for key in required:
            if key not in value:
                errors.append(f"{path}: missing required property {key!r}")
        for key, child_value in value.items():
            if key in properties:
                validate_schema_node(
                    child_value,
                    properties[key],
                    root_schema,
                    instance_path(path, key),
                    errors,
                )
            else:
                additional = schema.get("additionalProperties", True)
                if additional is False:
                    errors.append(f"{path}: additional property {key!r} is not allowed")
                elif isinstance(additional, dict):
                    validate_schema_node(
                        child_value,
                        additional,
                        root_schema,
                        instance_path(path, key),
                        errors,
                    )

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: requires at least {schema['minItems']} item(s)")
        if schema.get("uniqueItems") is True:
            seen: dict[str, int] = {}
            for index, item in enumerate(value):
                fingerprint = json_fingerprint(item)
                if fingerprint in seen:
                    errors.append(
                        f"{path}: items at indexes {seen[fingerprint]} and {index} are not unique"
                    )
                else:
                    seen[fingerprint] = index
        if "items" in schema:
            for index, item in enumerate(value):
                validate_schema_node(
                    item,
                    schema["items"],
                    root_schema,
                    f"{path}[{index}]",
                    errors,
                )

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: length must be at least {schema['minLength']}")
        if "pattern" in schema:
            try:
                matches = re.search(schema["pattern"], value)
            except (TypeError, re.error) as exc:
                raise ReviewError(f"Invalid JSON Schema pattern at {path}: {exc}") from exc
            if matches is None:
                errors.append(f"{path}: does not match required pattern {schema['pattern']!r}")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: must be at least {schema['minimum']}")


def validate_json_schema(value: Any, schema: Any) -> list[str]:
    assert_supported_schema(schema)
    assert isinstance(schema, dict)
    errors: list[str] = []
    validate_schema_node(value, schema, schema, "$", errors)
    return errors


def load_packet_schemas(verified_files: dict[str, bytes]) -> dict[str, dict[str, Any]]:
    schemas: dict[str, dict[str, Any]] = {}
    for name, relative in PACKET_SCHEMA_PATHS.items():
        data = verified_files.get(relative)
        if data is None:
            raise ReviewError(f"Verified packet schema is unavailable: {relative}")
        try:
            value = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ReviewError(f"Cannot load verified packet schema {relative}: {exc}") from exc
        if not isinstance(value, dict):
            raise ReviewError(f"Verified packet schema is not an object: {relative}")
        schemas[name] = value
    return schemas


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


def validation_record(value: Any) -> dict[str, str]:
    if not isinstance(value, str):
        raise ReviewError("Validation record must be a JSON object string")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ReviewError(
            "Validation record must be JSON with claim and artifact_path"
        ) from exc
    if not isinstance(parsed, dict):
        raise ReviewError("Validation record must be a JSON object")
    if set(parsed) != {"claim", "artifact_path"}:
        raise ReviewError("Validation record requires only claim and artifact_path")
    claim = parsed.get("claim")
    if not isinstance(claim, str) or not claim.strip():
        raise ReviewError("Validation record claim must be a non-empty string")
    artifact_path = parsed.get("artifact_path")
    if not isinstance(artifact_path, str):
        raise ReviewError("Validation record artifact_path must be a repository-relative string")
    return {
        "claim": claim.strip(),
        "artifact_path": ensure_relative(artifact_path),
    }


def bind_validation_records(
    raw_records: list[str], evidence_index: list[dict[str, Any]]
) -> list[dict[str, str]]:
    evidence_by_path = {str(row.get("path")): row for row in evidence_index}
    records: list[dict[str, str]] = []
    for raw_record in raw_records:
        record = validation_record(raw_record)
        evidence = evidence_by_path.get(record["artifact_path"])
        if evidence is None:
            raise ReviewError(
                "Validation artifact is not present in evidence_index: "
                f"{record['artifact_path']}"
            )
        artifact_sha256 = evidence.get("head_sha256")
        if not isinstance(artifact_sha256, str):
            raise ReviewError(
                "Validation artifact is not present in the frozen head: "
                f"{record['artifact_path']}"
            )
        records.append({**record, "artifact_sha256": artifact_sha256})
    return records


def validate_evidence_index(
    repo: Path,
    target: dict[str, str],
    manifest: dict[str, Any],
    errors: list[str],
) -> dict[str, dict[str, Any]]:
    raw_index = manifest.get("evidence_index")
    if not isinstance(raw_index, list) or not raw_index:
        errors.append("manifest evidence_index must be a non-empty array")
        return {}
    evidence_by_path: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(raw_index, 1):
        if not isinstance(row, dict):
            errors.append(f"evidence_index record {index} is not an object")
            continue
        path_value = row.get("path")
        try:
            if not isinstance(path_value, str):
                raise ReviewError("Path must be a string")
            relative = ensure_relative(path_value)
        except ReviewError as exc:
            errors.append(f"evidence_index record {index} path is invalid: {exc}")
            continue
        if relative in evidence_by_path:
            errors.append(f"evidence_index path is duplicated: {relative}")
            continue
        try:
            actual = file_record(repo, target["base_sha"], target["head_sha"], relative)
        except (KeyError, ReviewError) as exc:
            errors.append(f"evidence_index record cannot be verified: {relative}: {exc}")
            continue
        if row != actual:
            errors.append(f"evidence_index record hash or state mismatch: {relative}")
        evidence_by_path[relative] = row
    return evidence_by_path


def validate_validation_records(
    manifest: dict[str, Any],
    evidence_by_path: dict[str, dict[str, Any]],
    errors: list[str],
) -> None:
    records = manifest.get("validation_records")
    if not isinstance(records, list):
        errors.append("manifest validation_records must be an array")
        return
    required = {"claim", "artifact_path", "artifact_sha256"}
    for index, record in enumerate(records, 1):
        prefix = f"validation record {index}"
        if not isinstance(record, dict):
            errors.append(f"{prefix} is not a hash-bound object")
            continue
        if set(record) != required:
            errors.append(f"{prefix} requires only claim, artifact_path, and artifact_sha256")
            continue
        claim = record.get("claim")
        if not isinstance(claim, str) or not claim.strip():
            errors.append(f"{prefix} claim is invalid")
        artifact_path = record.get("artifact_path")
        try:
            if not isinstance(artifact_path, str):
                raise ReviewError("Path must be a string")
            relative = ensure_relative(artifact_path)
        except ReviewError as exc:
            errors.append(f"{prefix} artifact_path is invalid: {exc}")
            continue
        evidence = evidence_by_path.get(relative)
        if evidence is None:
            errors.append(f"{prefix} artifact is not present in evidence_index: {relative}")
            continue
        expected_hash = evidence.get("head_sha256")
        if not isinstance(expected_hash, str):
            errors.append(f"{prefix} artifact is not present in the frozen head: {relative}")
        elif record.get("artifact_sha256") != expected_hash:
            errors.append(f"{prefix} artifact_sha256 does not match evidence_index: {relative}")


def changed_files(repo: Path, base_sha: str, head_sha: str) -> list[str]:
    env = sanitized_git_environment()
    output = git(
        repo, "diff", "--name-only", "-z", base_sha, head_sha,
        binary=True, env=env,
    )
    assert isinstance(output, bytes)
    return sorted(
        ensure_relative(item.decode("utf-8"))
        for item in output.split(b"\0")
        if item
    )


def target_record(repo: Path, base_ref: str, head_ref: str) -> dict[str, str]:
    env = sanitized_git_environment()
    base_sha = resolve_ref(repo, base_ref, env=env)
    head_sha = resolve_ref(repo, head_ref, env=env)
    diff = git(
        repo,
        "-c", "color.ui=false",
        "-c", f"core.attributesFile={os.devnull}",
        "-c", "core.quotePath=true",
        "-c", "diff.algorithm=myers",
        "-c", "diff.indentHeuristic=false",
        "-c", "diff.mnemonicPrefix=false",
        "-c", "diff.noprefix=false",
        "-c", "diff.relative=false",
        "-c", "diff.renames=false",
        "-c", "diff.submodule=short",
        "-c", "diff.suppressBlankEmpty=false",
        "diff",
        "--patch",
        "--binary",
        "--full-index",
        "--no-color",
        "--no-ext-diff",
        "--no-textconv",
        "--no-renames",
        "--no-indent-heuristic",
        "--diff-algorithm=myers",
        "--src-prefix=a/",
        "--dst-prefix=b/",
        "--line-prefix=",
        "--unified=3",
        "--inter-hunk-context=0",
        "--no-function-context",
        "--output-indicator-new=+",
        "--output-indicator-old=-",
        "--output-indicator-context= ",
        "--ignore-submodules=none",
        "--submodule=short",
        "--no-relative",
        f"-O{os.devnull}",
        base_sha,
        head_sha,
        "--",
        binary=True,
        env=env,
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
        f"| {index:03d} | `{markdown_display_atom(row['path'])}` | "
        f"{markdown_display_atom(row['state'])} | "
        f"`{markdown_display_atom(row['head_sha256'] or row['base_sha256'])}` |"
        for index, row in enumerate(manifest["evidence_index"], 1)
    )
    validation = "\n".join(
        f"- {markdown_display_atom(item['claim'])} — "
        f"`{markdown_display_atom(item['artifact_path'])}` @ "
        f"`{markdown_display_atom(item['artifact_sha256'])}`"
        for item in manifest["validation_records"]
    ) or "- None recorded"
    policies = "\n".join(
        f"- `{markdown_display_atom(row['path'])}`" for row in manifest["policy_index"]
    )
    packet_authors = ", ".join(
        f"`{markdown_display_atom(item)}`" for item in manifest["packet_author_ids"]
    )
    return f"""# {markdown_display_atom(manifest['review_id'])} — frozen review context

- Version: {markdown_display_atom(manifest['schema_version'])}
- Built at: {markdown_display_atom(manifest['built_at'])}
- Owner: {markdown_display_atom(manifest['decision_owner'])}
- Packet author identities: {packet_authors}
- Consumer: isolated reviewers and adjudicator
- Supported gate: merge readiness only
- Repository: {markdown_display_atom(manifest['repository'])}
- Base SHA: `{markdown_display_atom(target['base_sha'])}`
- Head SHA: `{markdown_display_atom(target['head_sha'])}`
- Diff SHA-256: `{markdown_display_atom(target['diff_sha256'])}`
- Dynamic-value display encoding: `utf8pct-v1`; percent-decode the payload as UTF-8 to recover the exact value in `manifest.json`.
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

The target is frozen for review. Each validation claim below is bound to a frozen-head artifact hash; it remains reported evidence, not a substitute for inspection.

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

Use `$review-skill-candidate` to review `{markdown_display_atom(manifest['repository'])}` at the immutable target below.

- Review ID: `{markdown_display_atom(manifest['review_id'])}`
- Base SHA: `{markdown_display_atom(target['base_sha'])}`
- Head SHA: `{markdown_display_atom(target['head_sha'])}`
- Diff SHA-256: `{markdown_display_atom(target['diff_sha256'])}`
- Decision: merge eligibility for named-human review only
- Role: `{role}`
- Dynamic-value display encoding: `utf8pct-v1`; percent-decode the payload as UTF-8 to recover the exact value in `manifest.json`.

Read `context-pack.md`, then inspect the frozen commits and only the source pointers needed for this role. {ROLE_FOCUS[role]}

Do not read `submissions/` or another assignment. Do not modify files, approve merge, infer behavioral efficacy, or authorize promotion or installation.

Write exactly one JSON object matching `schemas/review-submission.schema.json` to `submissions/{role}.json`. Use reviewer role `{role}`, set `independent_context` to true only if isolation held, declare reviewed and not-reviewed scope, and anchor every finding to repository-relative file lines. An empty findings array is allowed only after the declared concerns were inspected.
"""


def render_gate(manifest: dict[str, Any]) -> str:
    target = manifest["target"]
    packet_authors = ", ".join(
        f"`{markdown_display_atom(item)}`" for item in manifest["packet_author_ids"]
    )
    return f"""# {markdown_display_atom(manifest['review_id'])} — merge-readiness decision

- Gate: G5 review handoff; merge decision only
- Status: proposed
- Decision owner: {markdown_display_atom(manifest['decision_owner'])}
- Requested by: {markdown_display_atom(manifest['requested_by'])}
- Packet author identities: {packet_authors}
- Opened at: {markdown_display_atom(manifest['built_at'])}
- Decided at: null
- Expires at: target or policy change
- Supersedes: null
- Evidence snapshot: `{markdown_display_atom(target['head_sha'])} / {markdown_display_atom(target['diff_sha256'])}`
- Dynamic-value display encoding: `utf8pct-v1`; percent-decode the payload as UTF-8 to recover the exact value in `manifest.json`.

## Decision requested

After independent reviews and adjudication, decide whether the exact frozen target may merge.

## Why now

The target is published for review and requires evidence beyond deterministic tests.

## In scope / out of scope

In scope: merge coherence, evidence integrity, implementation reproducibility, skill safety, and operational reviewability. Out of scope: behavioral-efficacy claims, skill promotion, installation, deployment, or broader adoption.

## Roles

- Responsible: three isolated reviewers and one adjudicator
- Accountable: {markdown_display_atom(manifest['decision_owner'])}
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
    packet_author_ids = [item.strip() for item in args.packet_author_id]
    canonical_authors = [canonical_identity(item) for item in packet_author_ids]
    if any(item is None for item in canonical_authors):
        raise ReviewError("Packet author identities must be non-empty strings")
    if len(canonical_authors) != len(set(canonical_authors)):
        raise ReviewError("Packet author identities must be unique")

    evidence_index = [
        file_record(repo, target["base_sha"], target["head_sha"], item)
        for item in artifacts
    ]
    validation_records = bind_validation_records(list(args.validation), evidence_index)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "review_id": review_id,
        "repository": args.repository,
        "pull_request": int(args.pr_number),
        "built_at": args.built_at,
        "decision": "merge_readiness",
        "decision_owner": args.decision_owner,
        "requested_by": args.requested_by,
        "packet_author_ids": packet_author_ids,
        "target": target,
        "required_roles": list(REQUIRED_ROLES),
        "validation_records": validation_records,
        "changed_files": changed,
        "evidence_index": evidence_index,
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


def validate_legacy_packet_contract(bundle: Path, manifest: dict[str, Any]) -> None:
    index_path = bundle / "packet-index.json"
    if not index_path.is_file():
        raise ReviewError("Legacy schema_version 1.0 requires the frozen PR-001 packet index")
    contract = LEGACY_PACKET_CONTRACTS.get(sha256_file(index_path))
    if contract is None:
        raise ReviewError(
            "Legacy schema_version 1.0 is accepted only for the frozen PR-001 contract"
        )
    for key in ("review_id", "repository", "pull_request", "target"):
        if manifest.get(key) != contract[key]:
            raise ReviewError(
                "Legacy schema_version 1.0 cannot authorize a different packet or target"
            )


def validate_packet_index(
    bundle: Path,
    errors: list[str],
    expected_schema_version: str = SCHEMA_VERSION,
) -> dict[str, bytes] | None:
    index_path = bundle / "packet-index.json"
    if not index_path.is_file():
        errors.append("missing packet-index.json")
        return None
    index = load_json(index_path)
    files = index.get("files") if isinstance(index, dict) else None
    version_matches = (
        isinstance(index, dict) and index.get("schema_version") == expected_schema_version
    )
    if not version_matches:
        errors.append("packet-index.json schema_version mismatch")
    if not isinstance(files, dict) or not files:
        errors.append("packet-index.json has no file map")
        return None
    valid = version_matches
    verified_files: dict[str, bytes] = {}
    required_schema_paths = set(PACKET_SCHEMA_PATHS.values())
    for relative, expected in files.items():
        try:
            normalized = ensure_relative(str(relative))
        except ReviewError as exc:
            errors.append(f"packet-index.json path is invalid: {exc}")
            valid = False
            continue
        path = bundle / normalized
        if not path.is_file():
            errors.append(f"packet file missing: {relative}")
            valid = False
            continue
        try:
            data = path.read_bytes()
        except OSError as exc:
            errors.append(f"packet file cannot be read: {relative}: {exc}")
            valid = False
            continue
        if sha256_bytes(data) != expected:
            errors.append(f"packet file hash mismatch: {relative}")
            valid = False
        elif normalized in required_schema_paths:
            verified_files[normalized] = data
    missing_schemas = sorted(required_schema_paths - set(verified_files))
    if missing_schemas:
        errors.append(f"packet-index.json lacks verified schemas: {', '.join(missing_schemas)}")
        valid = False
    return verified_files if valid else None


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
    schema: dict[str, Any],
    errors: list[str],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if not path.is_file():
        errors.append(f"missing reviewer submission: {role}")
        return None, []
    if schema is None:
        errors.append(f"{role} submission validation skipped: verified packet schema unavailable")
        return None, []
    value = load_json(path)
    schema_errors = validate_json_schema(value, schema)
    if schema_errors:
        errors.extend(f"{role} submission schema {item}" for item in schema_errors)
        return None, []
    assert isinstance(value, dict)
    target = manifest["target"]
    if value.get("schema_version") != manifest.get("schema_version"):
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
    reviewer_ids: set[str],
    packet_author_ids: set[str],
    strict_identity_separation: bool,
    schema: dict[str, Any] | None,
    errors: list[str],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    path = bundle / "adjudication" / "adjudication.json"
    if not path.is_file():
        errors.append("missing adjudication/adjudication.json")
        return None, []
    if schema is None:
        errors.append("adjudication validation skipped: verified packet schema unavailable")
        return None, []
    value = load_json(path)
    schema_errors = validate_json_schema(value, schema)
    if schema_errors:
        errors.extend(f"adjudication schema {item}" for item in schema_errors)
        return None, []
    assert isinstance(value, dict)
    if value.get("review_id") != manifest["review_id"] or not exact_target(value.get("target"), manifest["target"]):
        errors.append("adjudication target or review_id mismatch")
    adjudicator = value.get("adjudicator")
    if not strict_identity_separation:
        if (
            not isinstance(adjudicator, dict)
            or adjudicator.get("independent_from_authors") is not True
        ):
            errors.append("adjudicator independence is missing")
    elif not isinstance(adjudicator, dict):
        errors.append("adjudicator independence is missing")
    else:
        adjudicator_id = canonical_identity(adjudicator.get("adjudicator_id"))
        if adjudicator_id is None:
            errors.append("adjudicator identity is missing")
        if adjudicator.get("independent_from_authors") is not True:
            errors.append("adjudicator independence from authors is missing")
        if adjudicator.get("independent_from_reviewers") is not True:
            errors.append("adjudicator independence from reviewers is missing")
        if adjudicator_id in reviewer_ids:
            errors.append("adjudicator identity matches a reviewer identity")
        if adjudicator_id in packet_author_ids:
            errors.append("adjudicator identity matches a packet author identity")
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
    schema: dict[str, Any] | None,
    errors: list[str],
) -> dict[str, Any] | None:
    path = bundle / "human-decision" / "decision.json"
    if not path.exists():
        return None
    if schema is None:
        errors.append("human decision validation skipped: verified packet schema unavailable")
        return None
    value = load_json(path)
    schema_errors = validate_json_schema(value, schema)
    if schema_errors:
        errors.extend(f"human decision schema {item}" for item in schema_errors)
        return None
    assert isinstance(value, dict)
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
    if not isinstance(manifest, dict):
        raise ReviewError("Manifest schema_version is invalid")
    bundle_schema_version = manifest.get("schema_version")
    legacy_contract = bundle_schema_version == LEGACY_SCHEMA_VERSION
    if legacy_contract:
        validate_legacy_packet_contract(bundle, manifest)
    elif bundle_schema_version != SCHEMA_VERSION:
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
    verified_files = validate_packet_index(bundle, errors, str(bundle_schema_version))
    schemas: dict[str, dict[str, Any]] = {}
    if verified_files is not None:
        try:
            schemas = load_packet_schemas(verified_files)
        except ReviewError as exc:
            errors.append(f"verified packet schemas cannot be loaded: {exc}")

    packet_author_ids: set[str] = set()
    if not legacy_contract:
        raw_packet_author_ids = manifest.get("packet_author_ids")
        if not isinstance(raw_packet_author_ids, list) or not raw_packet_author_ids:
            errors.append("manifest packet_author_ids must be a non-empty array")
        else:
            for value in raw_packet_author_ids:
                identity = canonical_identity(value)
                if identity is None:
                    errors.append("manifest packet author identity is invalid")
                else:
                    packet_author_ids.add(identity)
            if len(packet_author_ids) != len(raw_packet_author_ids):
                errors.append("manifest packet author identities are not unique")

        evidence_by_path = validate_evidence_index(repo, target, manifest, errors)
        validate_validation_records(manifest, evidence_by_path, errors)

    submissions: dict[str, dict[str, Any]] = {}
    findings: dict[str, dict[str, Any]] = {}
    reviewer_ids: list[str] = []
    for role in REQUIRED_ROLES:
        submission, role_findings = validate_submission(
            repo,
            bundle / "submissions" / f"{role}.json",
            role,
            manifest,
            schemas.get("review_submission"),
            errors,
        )
        if submission is not None:
            submissions[role] = submission
            reviewer = submission.get("reviewer")
            if isinstance(reviewer, dict) and reviewer.get("reviewer_id"):
                if legacy_contract:
                    reviewer_ids.append(str(reviewer["reviewer_id"]))
                else:
                    identity = canonical_identity(reviewer["reviewer_id"])
                    if identity is None:
                        errors.append(f"{role} reviewer identity is invalid")
                    else:
                        reviewer_ids.append(identity)
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
        bundle,
        manifest,
        submissions,
        findings,
        set(reviewer_ids),
        packet_author_ids,
        not legacy_contract,
        schemas.get("adjudication"),
        errors,
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
    decision = validate_human_decision(
        bundle, manifest, computed_gate, schemas.get("human_decision"), errors
    )
    if errors:
        computed_gate = "blocked"
    decision_status = decision.get("decision") if decision else "provisional"
    if decision is None:
        warnings.append("named-human merge decision is absent")
    warnings.append("behavioral efficacy is outside this review and remains unknown")
    warnings.append("promotion and installation require separate evidence and human gates")

    summary = {
        "schema_version": bundle_schema_version,
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
    init.add_argument(
        "--packet-author-id",
        action="append",
        required=True,
        help="stable target or packet author identity; repeat for every author",
    )
    init.add_argument("--output", required=True)
    init.add_argument("--review-id")
    init.add_argument("--built-at", required=True)
    init.add_argument("--policy", action="append", default=[])
    init.add_argument("--artifact", action="append", default=[])
    init.add_argument(
        "--validation-record",
        "--validation",
        dest="validation",
        action="append",
        default=[],
        metavar="JSON",
        help=(
            "repeatable JSON object with claim and artifact_path; the artifact must be "
            "present in evidence_index and is bound to its frozen-head SHA-256"
        ),
    )
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
