#!/usr/bin/env python3
"""Validate the repository's loadable skill-package surface without third-party dependencies."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
AGENT_FIELD_PATTERN = re.compile(r"^  ([a-z_]+):\s*(.+)$")
REQUIRED_AGENT_FIELDS = {"display_name", "short_description", "default_prompt"}
SAFE_PLAIN_SCALAR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 .,_;()/'$+\-]*$")


class PackageError(ValueError):
    pass


def _scalar(raw: str, label: str, *, allow_plain: bool) -> str:
    raw = raw.strip()
    if not raw:
        raise PackageError(f"{label} must not be empty")
    if raw.startswith('"'):
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as error:
            raise PackageError(f"{label} has invalid JSON-string quoting") from error
    elif allow_plain and SAFE_PLAIN_SCALAR.fullmatch(raw):
        value = raw
    else:
        raise PackageError(f"{label} must be a JSON string or safe plain YAML scalar")
    if not isinstance(value, str) or not value.strip():
        raise PackageError(f"{label} must be a non-empty string")
    return value.strip()


def _frontmatter(skill_file: Path) -> tuple[dict[str, str], str]:
    text = skill_file.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise PackageError("SKILL.md must begin with YAML frontmatter")
    marker = text.find("\n---\n", 4)
    if marker < 0:
        raise PackageError("SKILL.md frontmatter is not terminated")
    fields: dict[str, str] = {}
    for line in text[4:marker].splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line or line.startswith((" ", "\t")):
            raise PackageError(f"Unsupported SKILL.md frontmatter line: {line!r}")
        key, raw = line.split(":", 1)
        if key in fields:
            raise PackageError(f"Duplicate SKILL.md frontmatter field: {key}")
        fields[key] = _scalar(raw, f"SKILL.md {key}", allow_plain=True)
    return fields, text[marker + 5 :]


def _agent_metadata(path: Path) -> dict[str, str]:
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.lstrip().startswith("#")]
    if not lines or lines[0] != "interface:":
        raise PackageError("agents/openai.yaml must contain one top-level interface mapping")
    fields: dict[str, str] = {}
    for line in lines[1:]:
        match = AGENT_FIELD_PATTERN.fullmatch(line)
        if not match:
            raise PackageError(f"Unsupported agents/openai.yaml line: {line!r}")
        key, raw = match.groups()
        if key in fields:
            raise PackageError(f"Duplicate agents/openai.yaml field: {key}")
        fields[key] = _scalar(raw, f"agents/openai.yaml {key}", allow_plain=False)
    if set(fields) != REQUIRED_AGENT_FIELDS:
        raise PackageError(f"agents/openai.yaml fields must be exactly {sorted(REQUIRED_AGENT_FIELDS)}")
    return fields


def validate_package(package: Path) -> dict[str, str]:
    package = package.resolve()
    if not package.is_dir() or package.is_symlink():
        raise PackageError(f"Skill package is missing or unsafe: {package}")
    skill_file = package / "SKILL.md"
    agent_file = package / "agents" / "openai.yaml"
    if not skill_file.is_file() or skill_file.is_symlink():
        raise PackageError(f"Missing or unsafe SKILL.md: {skill_file}")
    if not agent_file.is_file() or agent_file.is_symlink():
        raise PackageError(f"Missing or unsafe agents/openai.yaml: {agent_file}")
    frontmatter, body = _frontmatter(skill_file)
    if set(frontmatter) != {"name", "description"}:
        raise PackageError("SKILL.md frontmatter must contain exactly name and description")
    name = frontmatter["name"]
    if not NAME_PATTERN.fullmatch(name) or len(name) > 64 or name != package.name:
        raise PackageError("Skill name must be kebab-case, at most 64 characters, and match its directory")
    if len(frontmatter["description"]) > 1024 or not body.strip():
        raise PackageError("Skill description is too long or the instruction body is empty")
    metadata = _agent_metadata(agent_file)
    if len(metadata["short_description"]) > 80:
        raise PackageError("Agent short_description exceeds 80 characters")
    if f"${name}" not in metadata["default_prompt"]:
        raise PackageError("Agent default_prompt must explicitly invoke the packaged skill")
    return {"name": name, "path": str(package)}


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: validate_skill_packages.py <skill-dir> [...]", file=sys.stderr)
        return 2
    results = []
    try:
        for value in argv:
            results.append(validate_package(Path(value)))
    except (OSError, PackageError) as error:
        print(f"skill package validation failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"ok": True, "packages": results}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
