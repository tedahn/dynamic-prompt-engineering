from __future__ import annotations

import tempfile
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from automation.core import PipelineError, assess_summary
from automation.event_store import EventStore
from automation.orchestrator import Lifecycle


def promotable_summary() -> dict:
    return {
        "integrity": {"valid": True, "contamination_detected": False},
        "coverage": {
            "tasks": 12,
            "trials_per_task": 3,
            "expected_cells": 144,
            "complete_cells": 144,
            "final_graded_cells": 144,
            "expected_comparisons": 36,
            "final_comparisons": 36,
            "failed_cells": 0,
            "human_final": True,
            "adjudication_complete": True,
            "expected_domains": ["coding", "research", "operations"],
        },
        "quality": {
            "critical_candidate_failures": 0,
            "other_hard_gate_pass_rate": 1.0,
            "c01_minus_b01": {"lower95": 0.5},
            "c01_minus_b02": {"lower95": 0.0},
            "c01_vs_b01_preference": {"lower95": 0.7},
            "domain_deltas": {"coding": 0.1, "research": 0.2, "operations": 0.0},
        },
        "resources": {
            "usage_complete": True,
            "latency_ratio": {"upper95": 1.5},
            "token_ratio": {"upper95": 1.5},
        },
        "analysis_coverage": {
            "expected_task_clusters": 12,
            "c01_minus_b01_task_clusters": 12,
            "c01_minus_b02_task_clusters": 12,
            "preference_task_clusters": 12,
            "latency_ratio_task_clusters": 12,
            "token_ratio_task_clusters": 12,
        },
    }


def config() -> dict:
    return {
        "evaluation": {
            "arms": ["B00_RAW", "B01_MIN_ADVICE", "B02_PROFESSIONALIZE", "C01_EXPLORE"],
            "minimum_holdout_tasks": 12,
            "trials_per_task": 3,
            "thresholds": {
                "critical_candidate_failures_max": 0,
                "other_hard_gate_pass_rate_min": 0.95,
                "c01_minus_b01_mean_min": 0.4,
                "c01_minus_b02_mean_min": -0.1,
                "c01_vs_b01_preference_min": 0.6,
                "latency_ratio_max": 2.0,
                "token_ratio_max": 2.0,
                "domain_delta_min": -0.25,
                "quality_task_cluster_coverage_min": 1.0,
                "preference_task_cluster_coverage_min": 0.67,
                "resource_task_cluster_coverage_min": 1.0,
                "require_human_final": True,
                "require_complete_usage": True,
                "require_confidence_bounds": True,
            },
        }
    }


class AssessmentTest(unittest.TestCase):
    def test_conclusive_pass_is_promotable(self) -> None:
        self.assertEqual(assess_summary(promotable_summary(), config())["classification"], "promotable")

    def test_missing_usage_is_inconclusive_not_negative_evidence(self) -> None:
        summary = promotable_summary()
        summary["resources"]["usage_complete"] = False
        self.assertEqual(assess_summary(summary, config())["classification"], "inconclusive")

    def test_missing_final_grade_is_inconclusive(self) -> None:
        summary = promotable_summary()
        summary["coverage"]["final_graded_cells"] = 143
        self.assertEqual(assess_summary(summary, config())["classification"], "inconclusive")

    def test_actual_task_count_above_minimum_uses_exact_denominators(self) -> None:
        summary = promotable_summary()
        summary["coverage"].update(
            {
                "tasks": 15,
                "expected_cells": 180,
                "complete_cells": 180,
                "final_graded_cells": 180,
                "expected_comparisons": 45,
                "final_comparisons": 45,
            }
        )
        summary["analysis_coverage"] = {
            key: 15 for key in summary["analysis_coverage"]
        }
        self.assertEqual(assess_summary(summary, config())["classification"], "promotable")

    def test_insufficient_predeclared_task_cluster_coverage_is_inconclusive(self) -> None:
        summary = promotable_summary()
        summary["analysis_coverage"]["preference_task_clusters"] = 8
        assessment = assess_summary(summary, config())
        self.assertEqual(assessment["classification"], "inconclusive")
        self.assertIsNone(assessment["checks"]["analysis_cluster_coverage"])

    def test_critical_failure_rejects(self) -> None:
        summary = promotable_summary()
        summary["quality"]["critical_candidate_failures"] = 1
        self.assertEqual(assess_summary(summary, config())["classification"], "rejected")

    def test_contamination_invalidates(self) -> None:
        summary = promotable_summary()
        summary["integrity"]["contamination_detected"] = True
        self.assertEqual(assess_summary(summary, config())["classification"], "invalid")


class EventStoreTest(unittest.TestCase):
    def test_hash_chain_and_transition_guards(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = EventStore(Path(temporary) / "events.sqlite3")
            lifecycle = Lifecycle(store, "candidate")
            lifecycle.advance("frozen", "FROZEN", {"sha256": "a" * 64}, actor="test", idempotency_key="freeze")
            lifecycle.advance("holdout-ready", "READY", {"sha256": "b" * 64}, actor="test", idempotency_key="ready")
            self.assertTrue(lifecycle.audit()["ok"])
            with self.assertRaises(PipelineError):
                lifecycle.advance("active", "SKIP", {}, actor="test", idempotency_key="skip")
            store.connection.execute("UPDATE events SET payload_json='{}' WHERE version=1")
            store.connection.commit()
            self.assertFalse(lifecycle.audit()["ok"])
            store.close()

    def test_compare_and_swap_rejects_stale_writer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = EventStore(Path(temporary) / "events.sqlite3")
            store.append("x", "ONE", {}, actor="test", idempotency_key="one", expected_version=0, next_state="frozen")
            with self.assertRaises(PipelineError):
                store.append("x", "TWO", {}, actor="test", idempotency_key="two", expected_version=0, next_state="holdout-ready")
            store.close()

    def test_stream_state_tampering_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = EventStore(Path(temporary) / "events.sqlite3")
            store.append("x", "ONE", {}, actor="test", idempotency_key="one", expected_version=0, next_state="frozen")
            store.connection.execute("UPDATE streams SET state='active' WHERE stream='x'")
            store.connection.commit()
            self.assertIn("stream_state_mismatch", store.audit("x")["errors"])
            store.close()


if __name__ == "__main__":
    unittest.main()
