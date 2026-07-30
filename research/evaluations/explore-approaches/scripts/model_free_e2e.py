#!/usr/bin/env python3
"""Run a no-network, no-root-mutation lifecycle mechanics dry run."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

EVALUATION_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(EVALUATION_ROOT))

from automation.core import atomic_write_json, build_candidate_manifest, load_config, run_command, sha256_json  # noqa: E402
from automation.evaluation import BLIND_MAP_RELATIVE_PATH, build_holdout_manifest_template  # noqa: E402
from automation.promotion import prepare_clean_promotion, rehearse_rollback  # noqa: E402


NESTED_E2E_ENV = "EXPLORE_APPROACHES_MODEL_FREE_E2E_CHILD"
PROMOTION_FIXTURE_PATH = "skills/explore-approaches/SKILL.md"
PROMOTION_GIT_ENV = {
    "GIT_AUTHOR_NAME": "Model-Free Fixture",
    "GIT_AUTHOR_EMAIL": "model-free@example.invalid",
    "GIT_COMMITTER_NAME": "Model-Free Fixture",
    "GIT_COMMITTER_EMAIL": "model-free@example.invalid",
    "GIT_AUTHOR_DATE": "2026-07-30T12:00:00Z",
    "GIT_COMMITTER_DATE": "2026-07-30T12:00:00Z",
}


def _write_fixture(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _synthetic_promotion_dry_run(
    temporary_root: Path,
    config: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    """Exercise canonical promotion against a private local Git fixture."""
    baseline = temporary_root / "promotion-baseline"
    baseline.mkdir()
    run_command(["git", "init"], cwd=baseline)
    run_command(["git", "checkout", "-b", "main"], cwd=baseline)
    run_command(["git", "config", "user.name", PROMOTION_GIT_ENV["GIT_AUTHOR_NAME"]], cwd=baseline)
    run_command(["git", "config", "user.email", PROMOTION_GIT_ENV["GIT_AUTHOR_EMAIL"]], cwd=baseline)
    _write_fixture(baseline / "README.md", "# Synthetic promotion origin\n")
    _write_fixture(baseline / PROMOTION_FIXTURE_PATH, "# Baseline skill\n")
    run_command(["git", "add", "--", "README.md", PROMOTION_FIXTURE_PATH], cwd=baseline)
    run_command(["git", "commit", "-m", "Create synthetic baseline"], cwd=baseline, env=PROMOTION_GIT_ENV)
    base_commit = run_command(["git", "rev-parse", "HEAD"], cwd=baseline).stdout.strip()

    origin = temporary_root / "promotion-origin.git"
    run_command(["git", "clone", "--bare", str(baseline), str(origin)])

    source = temporary_root / "promotion-candidate"
    _write_fixture(
        source / PROMOTION_FIXTURE_PATH,
        "# Explore approaches\n\nSynthetic model-free promotion candidate.\n",
    )
    fixture_config = copy.deepcopy(config)
    fixture_config["pipeline_id"] = "explore-approaches-model-free-fixture"
    fixture_config["candidate"]["name"] = "explore-approaches-model-free-fixture"
    fixture_config["candidate"]["version"] = "model-free-fixture-v1"
    fixture_config["promotion"].update(
        {
            "repository_url": str(origin),
            "repository_slug": "local/model-free-fixture",
            "base_branch": "main",
            "feature_branch": "codex/model-free-fixture",
            "commit_message": "Materialize synthetic candidate",
            "copy_trees": ["skills/explore-approaches"],
            "copy_files": [],
            "excluded_globs": [],
            "csv_record_allowlist": {},
            "markdown_record_allowlist": {},
        }
    )
    fixture_manifest = build_candidate_manifest(source, fixture_config)

    previous_environment = {key: os.environ.get(key) for key in PROMOTION_GIT_ENV}
    os.environ.update(PROMOTION_GIT_ENV)
    try:
        prepared = prepare_clean_promotion(
            source,
            temporary_root / "promotion-work",
            fixture_config,
            fixture_manifest,
            expected_base_commit=base_commit,
            approval_sha256=sha256_json({"mode": "model-free-promotion-dry-run"}),
            config_sha256=sha256_json(fixture_config),
        )
    finally:
        for key, value in previous_environment.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    expected = temporary_root / "promotion-expected"
    run_command(["git", "clone", str(origin), str(expected)])
    run_command(["git", "checkout", "--detach", base_commit], cwd=expected)
    expected_candidate = expected / PROMOTION_FIXTURE_PATH
    expected_candidate.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source / PROMOTION_FIXTURE_PATH, expected_candidate)
    run_command(["git", "add", "--", PROMOTION_FIXTURE_PATH], cwd=expected)
    expected_paths = [
        value
        for value in run_command(
            ["git", "diff", "--cached", "--name-only", "-z"], cwd=expected
        ).stdout.split("\0")
        if value
    ]
    expected_tree = run_command(["git", "write-tree"], cwd=expected).stdout.strip()
    expected_paths = sorted(expected_paths)

    exact = all(
        (
            prepared["base_commit"] == base_commit,
            prepared["staged_paths"] == [PROMOTION_FIXTURE_PATH],
            prepared["staged_paths"] == expected_paths,
            prepared["head_tree"] == expected_tree,
            (Path(prepared["clone"]) / PROMOTION_FIXTURE_PATH).read_bytes()
            == (source / PROMOTION_FIXTURE_PATH).read_bytes(),
        )
    )
    summary = {
        "base_commit": prepared["base_commit"],
        "head_commit": prepared["head_commit"],
        "head_tree": prepared["head_tree"],
        "expected_tree": expected_tree,
        "staged_path_count": len(prepared["staged_paths"]),
        "staged_paths": prepared["staged_paths"],
        "candidate_manifest_sha256": fixture_manifest["manifest_sha256"],
    }
    return summary, exact


def run(output: Path) -> dict[str, object]:
    config = load_config(EVALUATION_ROOT / "config/pipeline-v1.json")
    checks: dict[str, object] = {}
    checker = run_command([sys.executable, str(EVALUATION_ROOT / "scripts/check_candidate.py")], cwd=REPO_ROOT, check=False)
    checks["candidate_contract"] = checker.returncode == 0
    tests = run_command(
        [sys.executable, "-m", "unittest", "discover", "-s", str(EVALUATION_ROOT / "tests"), "-q"],
        cwd=REPO_ROOT,
        timeout=120,
        env={NESTED_E2E_ENV: "1"},
        check=False,
    )
    checks["unit_and_adversarial_tests"] = tests.returncode == 0
    fake_adapter_evaluation = run_command(
        [
            sys.executable,
            "-m",
            "unittest",
            str(EVALUATION_ROOT / "tests" / "test_evaluation_automation.py"),
            "-q",
        ],
        cwd=REPO_ROOT,
        timeout=120,
        check=False,
    )
    checks["fake_adapter_evaluation_chain"] = fake_adapter_evaluation.returncode == 0
    compile_result = run_command(
        [sys.executable, "-m", "compileall", "-q", str(EVALUATION_ROOT / "automation"), str(EVALUATION_ROOT / "scripts")],
        cwd=REPO_ROOT,
        check=False,
    )
    checks["python_compile"] = compile_result.returncode == 0
    diff_check = run_command(["git", "diff", "--check"], cwd=REPO_ROOT, check=False)
    checks["git_diff_check"] = diff_check.returncode == 0
    schema_errors: list[str] = []
    for path in sorted((EVALUATION_ROOT / "schemas").glob("*.json")):
        try:
            json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            schema_errors.append(f"{path.name}:{exc}")
    checks["json_schemas_parse"] = not schema_errors

    manifest = build_candidate_manifest(REPO_ROOT, config)
    with tempfile.TemporaryDirectory(prefix="explore-e2e-") as temporary:
        temporary_root = Path(temporary)
        template_config = copy.deepcopy(config)
        adapter = temporary_root / "model-free-adapter.py"
        adapter.write_text("# model-free provenance fixture\n", encoding="utf-8")
        adapter_argv = [
            str(Path(sys.executable).resolve()),
            str(adapter.resolve()),
            "{input}",
            "{output}",
        ]
        template_config["holdout_verification"]["expected_identity"] = "model-free-holdout-owner"
        template_config["evaluation"]["subject_adapter_argv"] = adapter_argv
        template_config["evaluation"]["grader_adapter_argv"] = adapter_argv
        template_config["evaluation"]["canary_adapter_argv"] = adapter_argv
        template_config["evaluation"]["subject_runtime"] = {
            "adapter_id": "model-free-adapter",
            "provider_id": "model-free-provider",
            "model_id": "model-free-model",
            "settings": {},
            "entrypoint_path": str(adapter.resolve()),
            "dependency_paths": [],
        }
        template_config["installation"]["source_mode"] = "local-test"
        template_config["installation"]["validator_argv"] = adapter_argv
        holdout = temporary_root / "holdout.jsonl"
        rubric = json.loads((REPO_ROOT / template_config["candidate"]["rubric_path"]).read_text(encoding="utf-8"))
        domains = list(template_config["evaluation"]["required_holdout_domains"])
        task_count = max(int(template_config["evaluation"]["minimum_holdout_tasks"]), len(domains))
        holdout_rows = [
            {
                "task_id": f"MF-{index:03d}",
                "domain": domains[index % len(domains)],
                "request": f"Recommend an approach for model-free goal {index}",
                "workspace_context": "Synthetic private model-free workspace context",
                "expected": "Compare grounded approaches without implementation",
                "hard_gates": list(rubric["hard_gates"]),
                "forbidden": "Do not mutate files or disclose private evaluation material",
            }
            for index in range(task_count)
        ]
        holdout.write_text(
            "".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in holdout_rows),
            encoding="utf-8",
        )
        private_run = temporary_root / "private-evaluation-run"
        holdout_template = build_holdout_manifest_template(
            REPO_ROOT,
            holdout,
            template_config,
            build_candidate_manifest(REPO_ROOT, template_config),
            run_dir=private_run,
            manifest_id="HM-model-free-e2e",
            created_at="2026-07-30T12:00:00Z",
        )
        blind_key = private_run / "private" / "grading" / "blind-key.bin"
        private_root = private_run / "private"
        private_grading = private_root / "grading"
        checks["private_hmac_holdout_template"] = all(
            (
                "blind_seed" not in json.dumps(template_config, sort_keys=True),
                BLIND_MAP_RELATIVE_PATH == "private/grading/blind-map.jsonl",
                blind_key.is_file() and not blind_key.is_symlink(),
                (blind_key.stat().st_mode & 0o777) == 0o600,
                (private_root.stat().st_mode & 0o777) == 0o700,
                (private_grading.stat().st_mode & 0o777) == 0o700,
                holdout_template["blind_key_commitment"] == hashlib.sha256(blind_key.read_bytes()).hexdigest(),
            )
        )
        rollback = rehearse_rollback(temporary_root / "rollback")
        prepared_summary, materialization_exact = _synthetic_promotion_dry_run(temporary_root, config)
        checks["rollback_rehearsal"] = rollback["result"] == "passed"
        checks["clean_clone_materialization"] = materialization_exact

    result = {
        "schema_version": "1.0",
        "mode": "model-free-no-network-no-root-mutation",
        "candidate_manifest_sha256": manifest["manifest_sha256"],
        "checks": checks,
        "schema_errors": schema_errors,
        "promotion_dry_run": prepared_summary,
        "passed": all(value is True for value in checks.values()),
        "not_exercised": [
            "live subject grader and canary adapters",
            "fresh private human-authored holdout",
            "human-final adjudication",
            "post-result production SSH approval",
            "GitHub push review and merge",
            "production root-skill installation",
        ],
    }
    atomic_write_json(output, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=EVALUATION_ROOT / "results/runs/model-free-e2e-2026-07-30.json",
    )
    args = parser.parse_args()
    result = run(args.output.resolve())
    print(json.dumps({"output": str(args.output.resolve()), "passed": result["passed"]}, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
