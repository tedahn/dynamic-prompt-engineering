from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

EVALUATION_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(EVALUATION_ROOT))

from automation.core import run_command  # noqa: E402


NESTED_E2E_ENV = "EXPLORE_APPROACHES_MODEL_FREE_E2E_CHILD"
EXPECTED_CHECKS = {
    "candidate_contract",
    "clean_clone_materialization",
    "fake_adapter_evaluation_chain",
    "git_diff_check",
    "json_schemas_parse",
    "private_hmac_holdout_template",
    "python_compile",
    "rollback_rehearsal",
    "unit_and_adversarial_tests",
}


class ModelFreeE2ERegressionTest(unittest.TestCase):
    def _committed_snapshot(self, destination: Path) -> None:
        destination.mkdir()
        tracked = [
            value
            for value in run_command(["git", "ls-files", "-z"], cwd=REPO_ROOT).stdout.split("\0")
            if value
        ]
        for relative in tracked:
            source = REPO_ROOT / relative
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_symlink():
                target.symlink_to(os.readlink(source))
            else:
                shutil.copy2(source, target)
        run_command(["git", "init"], cwd=destination)
        run_command(["git", "checkout", "-b", "main"], cwd=destination)
        run_command(["git", "config", "user.name", "Model-Free Regression"], cwd=destination)
        run_command(["git", "config", "user.email", "model-free-regression@example.invalid"], cwd=destination)
        run_command(["git", "add", "--all"], cwd=destination)
        run_command(
            ["git", "commit", "-m", "Create clean E2E regression snapshot"],
            cwd=destination,
            env={
                "GIT_AUTHOR_DATE": "2026-07-30T12:00:00Z",
                "GIT_COMMITTER_DATE": "2026-07-30T12:00:00Z",
            },
        )

    def _run_e2e(self, checkout: Path, output: Path) -> dict[str, object]:
        script = checkout / "research/evaluations/explore-approaches/scripts/model_free_e2e.py"
        completed = run_command(
            [sys.executable, str(script), "--output", str(output)],
            cwd=checkout,
            timeout=240,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            0,
            msg=f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
        )
        result = json.loads(output.read_text(encoding="utf-8"))
        self.assertTrue(result["passed"])
        self.assertEqual(set(result["checks"]), EXPECTED_CHECKS)
        self.assertTrue(all(value is True for value in result["checks"].values()))
        promotion = result["promotion_dry_run"]
        self.assertEqual(promotion["staged_paths"], ["skills/explore-approaches/SKILL.md"])
        self.assertEqual(promotion["head_tree"], promotion["expected_tree"])
        return result

    def test_repeats_from_clean_commit_and_survives_unrelated_dirty_state(self) -> None:
        if os.environ.get(NESTED_E2E_ENV) == "1":
            self.skipTest("model-free E2E subprocess already exercises the remaining suite")
        with tempfile.TemporaryDirectory(prefix="model-free-e2e-regression-") as temporary:
            root = Path(temporary)
            checkout = root / "checkout"
            self._committed_snapshot(checkout)
            self.assertEqual(run_command(["git", "status", "--porcelain"], cwd=checkout).stdout, "")

            self._run_e2e(checkout, root / "clean-first.json")
            self.assertEqual(run_command(["git", "status", "--porcelain"], cwd=checkout).stdout, "")
            self._run_e2e(checkout, root / "clean-second.json")
            self.assertEqual(run_command(["git", "status", "--porcelain"], cwd=checkout).stdout, "")

            readme = checkout / "README.md"
            readme.write_text(readme.read_text(encoding="utf-8") + "\nModel-free dirty-worktree marker.\n", encoding="utf-8")
            dirty_before = run_command(["git", "status", "--porcelain"], cwd=checkout).stdout
            self.assertIn("README.md", dirty_before)
            self._run_e2e(checkout, root / "dirty.json")
            self.assertEqual(run_command(["git", "status", "--porcelain"], cwd=checkout).stdout, dirty_before)


if __name__ == "__main__":
    unittest.main()
