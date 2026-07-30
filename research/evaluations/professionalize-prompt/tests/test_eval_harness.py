from __future__ import annotations

import importlib.util
import math
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts/eval_harness.py"
SPEC = importlib.util.spec_from_file_location("eval_harness", MODULE_PATH)
assert SPEC and SPEC.loader
HARNESS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HARNESS)


class EvalHarnessTests(unittest.TestCase):
    def test_lab_validates(self) -> None:
        result = HARNESS.validate_lab()
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["fixtures"], 45)
        self.assertEqual(result["behavioral_efficacy"], "not-run")

    def test_check_registry_covers_every_fixture_check_once(self) -> None:
        fixtures = HARNESS.load_jsonl(HARNESS.LAB_ROOT / "fixtures/fixtures-v1.jsonl")
        errors, registry = HARNESS.validate_check_registry(
            HARNESS.LAB_ROOT / "fixtures/check-registry-v1.json", fixtures
        )
        self.assertFalse(errors, errors)
        registered = [check for rule in registry["rules"] for check in rule["checks"]]
        fixture_checks = {check for fixture in fixtures for check in fixture["checks"]}
        self.assertEqual(set(registered), fixture_checks)
        self.assertEqual(len(registered), len(set(registered)))

    def test_outcome_formula_and_hard_gate(self) -> None:
        self.assertTrue(math.isclose(HARNESS.compute_outcome(80, 70, 50, False), 73.0))
        self.assertEqual(HARNESS.compute_outcome(100, 100, 100, True), 0.0)

    def test_pilot_plan_is_deterministic_and_balanced(self) -> None:
        experiment = HARNESS.LAB_ROOT / "experiments/EXP-PP-V1-PREREG.json"
        first = HARNESS.generate_plan(experiment, "pilot")
        second = HARNESS.generate_plan(experiment, "pilot")
        self.assertEqual(first, second)
        self.assertEqual(len(first), 45)
        self.assertEqual(len({row["anonymous_id"] for row in first}), 45)
        counts = {}
        for row in first:
            counts[row["workflow_id"]] = counts.get(row["workflow_id"], 0) + 1
        self.assertEqual(set(counts.values()), {15})
        material = "".join(f"{HARNESS.json.dumps(row, sort_keys=True)}\n" for row in first)
        expected = HARNESS.load_json(experiment)["pilot"]["expected_plan_sha256"]
        self.assertEqual(HARNESS.sha256_bytes(material.encode("utf-8")), expected)

    def test_full_plan_requires_explicit_holdout_gate(self) -> None:
        experiment = HARNESS.LAB_ROOT / "experiments/EXP-PP-V1-PREREG.json"
        with self.assertRaises(ValueError):
            HARNESS.generate_plan(experiment, "full")
        full = HARNESS.generate_plan(experiment, "full", allow_holdout=True)
        self.assertEqual(len(full), 675)

    def test_wilson_interval_bounds(self) -> None:
        low, high = HARNESS.wilson_interval(8, 10)
        self.assertGreaterEqual(low, 0)
        self.assertLessEqual(high, 1)
        self.assertLess(low, 0.8)
        self.assertGreater(high, 0.8)


if __name__ == "__main__":
    unittest.main()
