from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
MODULE_PATH = REPO_ROOT / "research/evaluations/explore-approaches/scripts/check_candidate.py"
SPEC = importlib.util.spec_from_file_location("check_candidate", MODULE_PATH)
assert SPEC and SPEC.loader
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


class CandidateContractTest(unittest.TestCase):
    def test_repository_candidate_contract(self) -> None:
        result = CHECKER.validate(REPO_ROOT)
        self.assertTrue(result["ok"], result["errors"])
        self.assertEqual(result["fixture_count"], 6)

    def test_duplicate_fixture_ids_fail(self) -> None:
        row = {
            "fixture_id": "EA-DUP",
            "split": "development",
            "domain": "coding",
            "request": "Compare options.",
            "workspace_context": "Synthetic context.",
            "expected": "Grounded comparison.",
            "hard_gates": ["no_implementation"],
            "forbidden": "No mutation.",
        }
        errors = CHECKER.validate_fixture_rows([row, row, row, row, row])
        self.assertTrue(any("duplicate fixture IDs" in error for error in errors))

    def test_missing_authority_contract_fails(self) -> None:
        errors = CHECKER.validate_skill_text("---\nname: explore-approaches\ndescription: test\n---\n")
        self.assertTrue(any("Do not implement" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
