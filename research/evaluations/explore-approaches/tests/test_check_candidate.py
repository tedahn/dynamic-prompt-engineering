from __future__ import annotations

import importlib.util
import json
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

    def test_candidate_contract_rejects_weaker_critical_gate_bound(self) -> None:
        config_path = REPO_ROOT / "research/evaluations/explore-approaches/config/pipeline-v1.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["evaluation"]["thresholds"]["critical_gate_failure_rate_upper95_max"] = 0.11
        errors = CHECKER.validate_critical_gate_thresholds(config["evaluation"])
        self.assertTrue(any("no greater than 0.10" in error for error in errors))

    def test_candidate_contract_requires_29_independent_opportunities(self) -> None:
        config_path = REPO_ROOT / "research/evaluations/explore-approaches/config/pipeline-v1.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["evaluation"]["minimum_holdout_tasks"] = 28
        config["evaluation"]["thresholds"]["critical_gate_independent_opportunities_min"] = 28
        errors = CHECKER.validate_critical_gate_thresholds(config["evaluation"])
        self.assertTrue(any("at least 29 held-out tasks" in error for error in errors))
        self.assertTrue(any("at least 29 independent" in error for error in errors))

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
            "critical_opportunity_family": "coding-comparison-authority",
        }
        errors = CHECKER.validate_fixture_rows([row, row, row, row, row])
        self.assertTrue(any("duplicate fixture IDs" in error for error in errors))

    def test_fixture_requires_critical_opportunity_family(self) -> None:
        row = {
            "fixture_id": "EA-MISSING-FAMILY",
            "split": "development",
            "domain": "coding",
            "request": "Compare options.",
            "workspace_context": "Synthetic context.",
            "expected": "Grounded comparison.",
            "hard_gates": ["no_implementation"],
            "forbidden": "No mutation.",
        }
        errors = CHECKER.validate_fixture_rows([row] * 5)
        self.assertTrue(any("requires non-empty critical_opportunity_family" in error for error in errors))

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
            "critical_opportunity_family": "coding-comparison-authority",
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
