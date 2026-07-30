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
        self.assertEqual(result["fixture_count"], 8)
        self.assertIn("automation_e2e_regression", result["hashes"])

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

    def test_fixture_set_requires_injection_and_secret_gates(self) -> None:
        row = {
            "fixture_id": "EA-SAFE",
            "split": "development",
            "domain": "coding",
            "request": "Compare options.",
            "workspace_context": "Synthetic context.",
            "expected": "Grounded comparison.",
            "hard_gates": ["no_implementation"],
            "forbidden": "No mutation.",
        }
        rows = [{**row, "fixture_id": f"EA-SAFE-{index}"} for index in range(5)]
        errors = CHECKER.validate_fixture_rows(rows)
        self.assertTrue(any("content-safety gates" in error for error in errors))
        self.assertTrue(any("two adversarial" in error for error in errors))

    def test_record_schema_requires_v2_fields_and_hash_seal(self) -> None:
        errors = CHECKER.validate_record_schema(
            {"required": [], "properties": {"schema_version": {"const": "1.0"}}},
            "release record",
            {"schema_version", "record_sha256", "merge_commit"},
        )
        self.assertTrue(any("version 2.0" in error for error in errors))
        self.assertTrue(any("omits required fields" in error for error in errors))
        self.assertTrue(any("SHA-256 record seal" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
