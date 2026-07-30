import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("context_eval", ROOT / "scripts" / "context_eval.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
SKILL_SPEC = importlib.util.spec_from_file_location(
    "compose_context", ROOT.parents[2] / "skills" / "context-composer" / "scripts" / "compose_context.py"
)
SKILL_MODULE = importlib.util.module_from_spec(SKILL_SPEC)
SKILL_SPEC.loader.exec_module(SKILL_MODULE)


class ContextEvalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = MODULE.load_json(MODULE.CONFIG_PATH)
        cls.fixtures = MODULE.load_fixtures()

    def test_fixture_suite_is_complete_and_valid(self):
        self.assertEqual(12, len(self.fixtures))
        self.assertEqual([], MODULE.validate(self.config, self.fixtures))
        self.assertEqual(12, len({fixture["family"] for fixture in self.fixtures}))

    def test_selector_never_receives_grader_fields(self):
        case = MODULE.safe_input(self.fixtures[0])
        self.assertNotIn("expected", case)
        self.assertNotIn("family", case)

    def test_evaluation_is_deterministic(self):
        first = MODULE.evaluate(self.config, self.fixtures)
        second = MODULE.evaluate(self.config, self.fixtures)
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))

    def test_committed_score_snapshot_matches_evaluator(self):
        actual = MODULE.evaluate(self.config, self.fixtures)["summary"]
        snapshot = MODULE.load_json(ROOT / "results" / "mechanical-summary-2026-07-29.json")
        for condition, expected in snapshot["conditions"].items():
            comparable = {key: value for key, value in actual[condition].items() if key != "fixtures"}
            self.assertEqual(expected, comparable)

    def test_composed_condition_passes_mechanical_gate(self):
        summary = MODULE.evaluate(self.config, self.fixtures)["summary"]
        candidate = summary["C1_COMPOSED"]
        lexical = summary["B2_KEYWORD_TOPK"]
        self.assertEqual(0, candidate["critical_failures"])
        self.assertEqual(0, candidate["budget_failures"])
        self.assertGreaterEqual(candidate["required_recall_macro"], lexical["required_recall_macro"])

    def test_routed_condition_clarifies_ambiguous_request(self):
        fixture = next(item for item in self.fixtures if item["fixture_id"] == "CC-010")
        result = MODULE.select("C2_ROUTED", MODULE.safe_input(fixture), self.config)
        self.assertEqual("clarify", result["route"])
        self.assertEqual([], result["selected"])

    def test_composed_condition_excludes_restricted_and_injected_items(self):
        for fixture_id in ("CC-006", "CC-007"):
            fixture = next(item for item in self.fixtures if item["fixture_id"] == fixture_id)
            result = MODULE.select("C1_COMPOSED", MODULE.safe_input(fixture), self.config)
            selected = {item["id"] for item in result["selected"]}
            self.assertFalse(selected & set(fixture["expected"]["forbidden_ids"]))

    def test_composed_condition_orders_prerequisites_before_dependents(self):
        fixture = next(item for item in self.fixtures if item["fixture_id"] == "CC-003")
        for condition in ("C1_COMPOSED", "C2_ROUTED"):
            result = MODULE.select(condition, MODULE.safe_input(fixture), self.config)
            selected = [item["id"] for item in result["selected"]]
            self.assertLess(selected.index("a"), selected.index("b"))

    def test_candidate_skill_adapter_matches_safety_and_dependency_controls(self):
        fixture = next(item for item in self.fixtures if item["fixture_id"] == "CC-003")
        payload = MODULE.safe_input(fixture)
        result = SKILL_MODULE.compose(payload)
        selected = [item["id"] for item in result["selected"]]
        self.assertEqual("composed", result["route"])
        self.assertLess(selected.index("a"), selected.index("b"))

        restricted = next(item for item in self.fixtures if item["fixture_id"] == "CC-006")
        restricted_result = SKILL_MODULE.compose(MODULE.safe_input(restricted))
        self.assertIn({"id": "b", "reason": "disallowed_scope"}, restricted_result["excluded"])

    def test_candidate_skill_adapter_clarifies_material_ambiguity(self):
        fixture = next(item for item in self.fixtures if item["fixture_id"] == "CC-010")
        result = SKILL_MODULE.compose(MODULE.safe_input(fixture))
        self.assertEqual("clarify", result["route"])
        self.assertEqual([], result["selected"])

    def test_candidate_skill_adapter_drops_dependents_of_filtered_evidence(self):
        payload = {
            "query": "What procedure applies?",
            "max_tokens": 20,
            "allowed_scopes": ["project"],
            "items": [
                {"id": "parent", "text": "Restricted governing rule.", "scope": "restricted", "status": "current", "authority": "canonical"},
                {"id": "child", "text": "Project procedure.", "scope": "project", "status": "current", "authority": "primary", "depends_on": ["parent"]},
            ],
        }
        result = SKILL_MODULE.compose(payload)
        self.assertEqual([], result["selected"])
        self.assertIn({"id": "parent", "reason": "disallowed_scope"}, result["excluded"])
        self.assertIn({"id": "child", "reason": "missing_dependency:parent"}, result["excluded"])


if __name__ == "__main__":
    unittest.main()
