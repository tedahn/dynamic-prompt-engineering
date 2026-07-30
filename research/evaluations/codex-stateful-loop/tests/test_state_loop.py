"""Behavioral and integrity tests for the governed state-loop harness."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


LAB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB_ROOT / "scripts"))

import state_loop  # noqa: E402


FIXED_TIME = "2026-07-29T12:00:00Z"


class StateLoopTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(prefix="state-loop-test-")
        self.instance = Path(self.temporary_directory.name) / "instance"
        self.initialized = state_loop.initialize_instance(self.instance)
        self.connection = state_loop.connect(self.instance)
        self.sequence = 0

    def tearDown(self) -> None:
        self.connection.close()
        self.temporary_directory.cleanup()

    def observe(
        self,
        *,
        connection=None,
        instance: Path | None = None,
        observation_id: str | None = None,
        split: str = "dev",
        episode_id: str = "EP-TEST",
    ) -> str:
        self.sequence += 1
        ids = state_loop.register_observations(
            connection or self.connection,
            instance or self.instance,
            [
                {
                    "observation_id": observation_id or f"OBS-{self.sequence:04d}",
                    "episode_id": episode_id,
                    "split": split,
                    "actor_type": "subject",
                    "actor_id": "subject-test",
                    "payload": {"finding": f"development evidence {self.sequence}"},
                }
            ],
        )
        return ids[0]

    def entry(self, entry_id: str, source_event_id: str, **overrides) -> dict:
        entry = {
            "entry_id": entry_id,
            "kind": "preference",
            "content": f"Use the verified preference for {entry_id}.",
            "scope": {"domains": ["coding"], "task_tags": ["python"]},
            "source_event_ids": [source_event_id],
            "evidence_state": "Grounded fact",
            "confidence": 0.9,
            "priority": 50,
            "sensitivity": "public",
            "allowed_surfaces": ["codex"],
            "authority_effect": "none",
            "owner": "test-owner",
            "valid_from": "2026-01-01T00:00:00Z",
            "expires_at": None,
            "refresh_trigger": None,
            "status": "active",
            "supersedes": [],
        }
        entry.update(overrides)
        return entry

    def proposal(
        self,
        proposal_id: str,
        base_snapshot_id: str,
        source_event_ids: list[str],
        operations: list[dict],
    ) -> dict:
        return {
            "schema_version": "1.0",
            "proposal_id": proposal_id,
            "base_snapshot_id": base_snapshot_id,
            "created_by": "optimizer-test",
            "created_at": FIXED_TIME,
            "source_event_ids": source_event_ids,
            "hypothesis": "Scoped context improves requirement preservation.",
            "changed_mechanism": "durable_context_entries",
            "predicted_benefit": "More accurate scoped recall.",
            "predicted_regressions": ["Context bloat"],
            "counterexamples": ["The current request supersedes stored context."],
            "operations": operations,
        }

    def add_candidate(
        self,
        *,
        connection=None,
        instance: Path | None = None,
        proposal_id: str = "PROP-ADD",
        entry_id: str = "CTX-ENTRY-001",
    ) -> dict:
        connection = connection or self.connection
        instance = instance or self.instance
        source = self.observe(connection=connection, instance=instance)
        proposal = self.proposal(
            proposal_id,
            "CTX-STATE-000",
            [source],
            [{"op": "add", "entry": self.entry(entry_id, source)}],
        )
        return state_loop.apply_proposal(connection, instance, proposal)

    @staticmethod
    def cell_rows(connection, epoch_id: str) -> list:
        return connection.execute(
            "SELECT * FROM cells WHERE epoch_id=? ORDER BY episode_id,trial,condition_id",
            (epoch_id,),
        ).fetchall()

    def evaluation_record(self, row, *, record_id: str, task_score: float = 75) -> dict:
        condition_id = row["condition_id"]
        return {
            "schema_version": "1.0",
            "record_id": record_id,
            "cell_id": row["cell_id"],
            "anonymous_id": row["anonymous_id"],
            "episode_id": row["episode_id"],
            "family": row["family"],
            "trial": row["trial"],
            "grader_id": "grader-test",
            "record_status": "provisional",
            "scores": {
                "task_score": task_score,
                "requirement_preservation": 90,
                "context_precision": 0.9 if condition_id == "C1_GATED_EVOLVING" else 0.8,
                "stale_or_irrelevant_rate": 0.01,
                "mutation_precision": 0.85,
                "mutation_recall": 0.8,
                "cost_units": 1.0,
                "latency_ms": 100,
            },
            "critical_gate": False,
            "gate_reasons": [],
            "pairwise": None,
            "evidence_refs": [row["packet_sha256"]],
            "graded_at": FIXED_TIME,
        }


class InitializationAndIntegrityTests(StateLoopTestCase):
    def test_initialization_creates_seed_pointer_and_auditable_event_chain(self) -> None:
        self.assertEqual(self.initialized["active_snapshot_id"], "CTX-STATE-000")
        self.assertEqual(state_loop.get_active_snapshot_id(self.connection), ("CTX-STATE-000", 1))
        self.assertEqual(self.connection.execute("PRAGMA journal_mode").fetchone()[0], "wal")

        audit = state_loop.audit_instance(self.connection, self.instance)
        self.assertEqual(audit["status"], "pass", audit["errors"])
        self.assertEqual(audit["event_count"], 1)
        self.assertTrue((self.instance / "exports" / "events.jsonl").is_file())

    def test_initialization_refuses_nonempty_instance(self) -> None:
        with self.assertRaisesRegex(state_loop.StateLoopError, "non-empty"):
            state_loop.initialize_instance(self.instance)

    def test_idempotent_event_replay_and_conflicting_reuse(self) -> None:
        kwargs = {
            "stream_id": "test:idempotency",
            "event_type": "test_event",
            "actor_type": "harness",
            "actor_id": "test-harness",
            "payload": {"value": 1},
            "idempotency_key": "test:idempotency:1",
        }
        first = state_loop.append_event(self.connection, **kwargs)
        replay = state_loop.append_event(self.connection, **kwargs)
        self.assertEqual(replay["event_id"], first["event_id"])
        count = self.connection.execute(
            "SELECT COUNT(*) FROM events WHERE stream_id='test:idempotency'"
        ).fetchone()[0]
        self.assertEqual(count, 1)

        conflicting = dict(kwargs)
        conflicting["payload"] = {"value": 2}
        with self.assertRaisesRegex(state_loop.ConflictError, "Conflicting reuse"):
            state_loop.append_event(self.connection, **conflicting)

    def test_stream_compare_and_swap_rejects_stale_writer(self) -> None:
        state_loop.append_event(
            self.connection,
            stream_id="test:cas",
            event_type="cas_event",
            actor_type="harness",
            actor_id="writer-a",
            payload={"writer": "a"},
            idempotency_key="test:cas:a",
            expected_stream_version=0,
        )
        with self.assertRaisesRegex(state_loop.ConflictError, "expected version 0, found 1"):
            state_loop.append_event(
                self.connection,
                stream_id="test:cas",
                event_type="cas_event",
                actor_type="harness",
                actor_id="writer-b",
                payload={"writer": "b"},
                idempotency_key="test:cas:b",
                expected_stream_version=0,
            )

    def test_audit_detects_artifact_tampering(self) -> None:
        row = self.connection.execute("SELECT relative_path FROM artifacts ORDER BY sha256 LIMIT 1").fetchone()
        (self.instance / row["relative_path"]).write_text("tampered", encoding="utf-8")
        audit = state_loop.audit_instance(self.connection, self.instance)
        self.assertEqual(audit["status"], "fail")
        self.assertTrue(any("artifact hash mismatch" in error for error in audit["errors"]))


class ProposalSafetyAndMutationTests(StateLoopTestCase):
    def test_holdout_observations_are_never_optimizer_visible(self) -> None:
        with self.assertRaisesRegex(state_loop.StateLoopError, "holdout"):
            self.observe(split="holdout")

        malicious = state_loop.append_event(
            self.connection,
            stream_id="episode:PRIVATE",
            event_type="test_holdout_event",
            actor_type="harness",
            actor_id="malicious-test",
            payload={"split": "holdout"},
            idempotency_key="test:private-holdout",
        )
        proposal = self.proposal(
            "PROP-HOLDOUT",
            "CTX-STATE-000",
            [malicious["event_id"]],
            [{"op": "add", "entry": self.entry("CTX-HOLDOUT", malicious["event_id"])}],
        )
        with self.assertRaisesRegex(state_loop.StateLoopError, "Only development events"):
            state_loop.apply_proposal(self.connection, self.instance, proposal)

    def test_proposal_add_supersede_and_retire_preserves_history(self) -> None:
        source_1 = self.observe()
        candidate_1 = state_loop.apply_proposal(
            self.connection,
            self.instance,
            self.proposal(
                "PROP-1",
                "CTX-STATE-000",
                [source_1],
                [{"op": "add", "entry": self.entry("CTX-1", source_1)}],
            ),
        )
        source_2 = self.observe()
        candidate_2 = state_loop.apply_proposal(
            self.connection,
            self.instance,
            self.proposal(
                "PROP-2",
                candidate_1["candidate_snapshot_id"],
                [source_2],
                [
                    {
                        "op": "supersede",
                        "target_entry_id": "CTX-1",
                        "entry": self.entry("CTX-2", source_2),
                    }
                ],
            ),
        )
        state_2 = state_loop.get_snapshot(
            self.connection, self.instance, candidate_2["candidate_snapshot_id"]
        )
        by_id = {entry["entry_id"]: entry for entry in state_2["entries"]}
        self.assertEqual(by_id["CTX-1"]["status"], "superseded")
        self.assertEqual(by_id["CTX-2"]["supersedes"], ["CTX-1"])

        source_3 = self.observe()
        candidate_3 = state_loop.apply_proposal(
            self.connection,
            self.instance,
            self.proposal(
                "PROP-3",
                candidate_2["candidate_snapshot_id"],
                [source_3],
                [{"op": "retire", "target_entry_id": "CTX-2"}],
            ),
        )
        state_3 = state_loop.get_snapshot(
            self.connection, self.instance, candidate_3["candidate_snapshot_id"]
        )
        by_id = {entry["entry_id"]: entry for entry in state_3["entries"]}
        self.assertEqual(by_id["CTX-1"]["status"], "superseded")
        self.assertEqual(by_id["CTX-2"]["status"], "retired")
        self.assertEqual(state_loop.get_active_snapshot_id(self.connection), ("CTX-STATE-000", 1))
        self.assertEqual(state_loop.audit_instance(self.connection, self.instance)["status"], "pass")

    def test_proposal_rejects_secrets_authority_expansion_and_restricted_content(self) -> None:
        source = self.observe()
        unsafe_changes = {
            "secret": {"content": "api_key=deadbeefcafebabe"},
            "authority": {"authority_effect": "write-files"},
            "restricted": {"sensitivity": "restricted"},
        }
        for label, changes in unsafe_changes.items():
            with self.subTest(label=label):
                proposal = self.proposal(
                    f"PROP-UNSAFE-{label.upper()}",
                    "CTX-STATE-000",
                    [source],
                    [
                        {
                            "op": "add",
                            "entry": self.entry(f"CTX-UNSAFE-{label.upper()}", source, **changes),
                        }
                    ],
                )
                with self.assertRaises(state_loop.StateLoopError):
                    state_loop.apply_proposal(self.connection, self.instance, proposal)

    def test_entry_provenance_must_be_declared_by_proposal(self) -> None:
        declared = self.observe()
        undeclared = self.observe()
        proposal = self.proposal(
            "PROP-BAD-PROVENANCE",
            "CTX-STATE-000",
            [declared],
            [{"op": "add", "entry": self.entry("CTX-PROVENANCE", undeclared)}],
        )
        with self.assertRaisesRegex(state_loop.StateLoopError, "provenance"):
            state_loop.apply_proposal(self.connection, self.instance, proposal)


class ContextSelectionTests(StateLoopTestCase):
    def test_retrieval_applies_scope_expiry_confidence_surface_and_budget(self) -> None:
        source = self.observe()
        entries = [
            self.entry("CTX-HIGH", source, content="High priority exact-match context.", priority=100),
            self.entry("CTX-EXPIRED", source, expires_at="2026-07-01T00:00:00Z"),
            self.entry("CTX-DOMAIN", source, scope={"domains": ["research"], "task_tags": ["python"]}),
            self.entry("CTX-TAG", source, scope={"domains": ["coding"], "task_tags": ["typescript"]}),
            self.entry("CTX-SURFACE", source, allowed_surfaces=["chatgpt"]),
            self.entry("CTX-LOW", source, confidence=0.49),
            self.entry("CTX-RETIRED", source, status="retired"),
        ]
        for index in range(14):
            entries.append(
                self.entry(
                    f"CTX-BUDGET-{index:02d}",
                    source,
                    content=f"Budget candidate {index}: " + (chr(65 + index) * 520),
                    priority=80 - index,
                )
            )
        candidate = state_loop.apply_proposal(
            self.connection,
            self.instance,
            self.proposal(
                "PROP-CONTEXT",
                "CTX-STATE-000",
                [source],
                [{"op": "add", "entry": entry} for entry in entries],
            ),
        )
        task = {
            "task_id": "TASK-CONTEXT",
            "domain": "coding",
            "tags": ["python"],
            "surface": "codex",
            "now": FIXED_TIME,
        }
        pack, _ = state_loop.compile_context(
            self.connection,
            self.instance,
            candidate["candidate_snapshot_id"],
            task,
            condition_id="B3_RETRIEVAL_ONLY",
            log_event=False,
        )
        included = pack["trace"]["included_entry_ids"]
        excluded = {item["entry_id"]: item["reason"] for item in pack["trace"]["excluded"]}
        self.assertIn("CTX-HIGH", included)
        self.assertEqual(excluded["CTX-EXPIRED"], "expired")
        self.assertEqual(excluded["CTX-DOMAIN"], "domain-mismatch")
        self.assertEqual(excluded["CTX-TAG"], "tag-mismatch")
        self.assertEqual(excluded["CTX-SURFACE"], "surface-mismatch")
        self.assertEqual(excluded["CTX-LOW"], "below-confidence-floor")
        self.assertEqual(excluded["CTX-RETIRED"], "status:retired")
        self.assertLessEqual(pack["trace"]["entry_count"], pack["trace"]["max_entries"])
        self.assertLessEqual(pack["trace"]["content_chars"], pack["trace"]["max_chars"])
        self.assertTrue(
            any(reason in {"entry-budget", "character-budget"} for reason in excluded.values())
        )

        stateless, _ = state_loop.compile_context(
            self.connection,
            self.instance,
            candidate["candidate_snapshot_id"],
            {**task, "task_id": "TASK-STATELESS"},
            condition_id="B0_STATELESS_RAW",
            log_event=False,
        )
        self.assertEqual(stateless["entries"], [])
        self.assertTrue(
            all(item["reason"] == "condition-no-context" for item in stateless["trace"]["excluded"])
        )


class PlanningAndEvaluationTests(StateLoopTestCase):
    def test_smoke_and_pilot_plan_counts_and_full_holdout_block(self) -> None:
        candidate = self.add_candidate()
        smoke = state_loop.create_plan(
            self.connection,
            self.instance,
            stage="smoke",
            candidate_snapshot_id=candidate["candidate_snapshot_id"],
            epoch_id="EPOCH-SMOKE-COUNT",
        )
        pilot = state_loop.create_plan(
            self.connection,
            self.instance,
            stage="pilot",
            candidate_snapshot_id=candidate["candidate_snapshot_id"],
            epoch_id="EPOCH-PILOT-COUNT",
        )
        self.assertEqual(smoke["cell_count"], 9)
        self.assertEqual(pilot["cell_count"], 144)
        self.assertEqual(len(self.cell_rows(self.connection, "EPOCH-SMOKE-COUNT")), 9)
        self.assertEqual(len(self.cell_rows(self.connection, "EPOCH-PILOT-COUNT")), 144)
        with self.assertRaisesRegex(state_loop.StateLoopError, "fresh evaluator-owned sealed holdout"):
            state_loop.create_plan(
                self.connection,
                self.instance,
                stage="full",
                candidate_snapshot_id=candidate["candidate_snapshot_id"],
            )

    def test_plan_cell_and_anonymous_ids_are_reproducible_for_fixed_epoch(self) -> None:
        candidate = self.add_candidate(proposal_id="PROP-DETERMINISM-A")
        epoch_id = "EPOCH-DETERMINISTIC"
        state_loop.create_plan(
            self.connection,
            self.instance,
            stage="smoke",
            candidate_snapshot_id=candidate["candidate_snapshot_id"],
            epoch_id=epoch_id,
        )
        first = [
            (row["episode_id"], row["condition_id"], row["trial"], row["cell_id"], row["anonymous_id"])
            for row in self.cell_rows(self.connection, epoch_id)
        ]

        instance_2 = Path(self.temporary_directory.name) / "instance-2"
        state_loop.initialize_instance(instance_2)
        connection_2 = state_loop.connect(instance_2)
        try:
            candidate_2 = self.add_candidate(
                connection=connection_2,
                instance=instance_2,
                proposal_id="PROP-DETERMINISM-B",
                entry_id="CTX-ENTRY-002",
            )
            state_loop.create_plan(
                connection_2,
                instance_2,
                stage="smoke",
                candidate_snapshot_id=candidate_2["candidate_snapshot_id"],
                epoch_id=epoch_id,
            )
            second = [
                (row["episode_id"], row["condition_id"], row["trial"], row["cell_id"], row["anonymous_id"])
                for row in self.cell_rows(connection_2, epoch_id)
            ]
        finally:
            connection_2.close()
        self.assertEqual(first, second)

        config = state_loop.load_json(state_loop.CONFIG_PATH)
        row = self.cell_rows(self.connection, epoch_id)[0]
        expected_hash = hashlib.sha256(
            f"{epoch_id}:{row['episode_id']}:{row['condition_id']}:{row['trial']}:{config['seeds']['execution']}".encode()
        ).hexdigest()
        self.assertEqual(row["cell_id"], f"CELL-{expected_hash[:16].upper()}")

    def test_evaluation_ingestion_enforces_frozen_cell_identity_and_score_bounds(self) -> None:
        candidate = self.add_candidate()
        epoch_id = "EPOCH-EVAL-VALIDATION"
        state_loop.create_plan(
            self.connection,
            self.instance,
            stage="smoke",
            candidate_snapshot_id=candidate["candidate_snapshot_id"],
            epoch_id=epoch_id,
        )
        row = self.cell_rows(self.connection, epoch_id)[0]
        mismatched = self.evaluation_record(row, record_id="EVAL-MISMATCH")
        mismatched["anonymous_id"] = "ANON-WRONG"
        with self.assertRaisesRegex(state_loop.StateLoopError, "anonymous_id does not match"):
            state_loop.ingest_evaluations(self.connection, self.instance, epoch_id, [mismatched])

        out_of_bounds = self.evaluation_record(row, record_id="EVAL-BOUNDS")
        out_of_bounds["scores"]["task_score"] = 101
        with self.assertRaisesRegex(state_loop.StateLoopError, "outside bounds"):
            state_loop.ingest_evaluations(self.connection, self.instance, epoch_id, [out_of_bounds])

    def test_complete_smoke_evaluation_remains_development_only(self) -> None:
        candidate = self.add_candidate()
        epoch_id = "EPOCH-EVAL-SMOKE"
        state_loop.create_plan(
            self.connection,
            self.instance,
            stage="smoke",
            candidate_snapshot_id=candidate["candidate_snapshot_id"],
            epoch_id=epoch_id,
        )
        rows = self.cell_rows(self.connection, epoch_id)
        records = []
        for index, row in enumerate(rows):
            task_score = 85 if row["condition_id"] == "C1_GATED_EVOLVING" else 75
            records.append(
                self.evaluation_record(row, record_id=f"EVAL-{index:03d}", task_score=task_score)
            )
        self.assertEqual(
            state_loop.ingest_evaluations(self.connection, self.instance, epoch_id, records),
            9,
        )
        with self.assertRaises(state_loop.ConflictError):
            state_loop.ingest_evaluations(self.connection, self.instance, epoch_id, [records[0]])

        summary = state_loop.evaluate_epoch(self.connection, self.instance, epoch_id)
        self.assertEqual(summary["record_count"], 9)
        self.assertEqual(summary["status"], "development_only")
        self.assertFalse(summary["promotion_gates"]["stage_is_full"])
        self.assertIn("fresh blinded holdout", summary["claim_boundary"])
        self.assertEqual(state_loop.audit_instance(self.connection, self.instance)["status"], "pass")

    def test_evaluation_refuses_incomplete_epoch(self) -> None:
        candidate = self.add_candidate()
        epoch_id = "EPOCH-EVAL-INCOMPLETE"
        state_loop.create_plan(
            self.connection,
            self.instance,
            stage="smoke",
            candidate_snapshot_id=candidate["candidate_snapshot_id"],
            epoch_id=epoch_id,
        )
        first = self.cell_rows(self.connection, epoch_id)[0]
        state_loop.ingest_evaluations(
            self.connection,
            self.instance,
            epoch_id,
            [self.evaluation_record(first, record_id="EVAL-ONLY-ONE")],
        )
        with self.assertRaisesRegex(state_loop.StateLoopError, "cells without evaluation records"):
            state_loop.evaluate_epoch(self.connection, self.instance, epoch_id)


class PromotionAndRollbackTests(StateLoopTestCase):
    @staticmethod
    def approval_window(*, expired: bool = False) -> tuple[str, str]:
        now = datetime.now(timezone.utc)
        if expired:
            approved_at = now - timedelta(hours=2)
            expires_at = now - timedelta(hours=1)
        else:
            approved_at = now - timedelta(minutes=1)
            expires_at = now + timedelta(hours=1)
        return approved_at.isoformat(), expires_at.isoformat()

    def promotion_approval(
        self,
        *,
        epoch_id: str,
        candidate_snapshot_id: str,
        summary_sha256: str,
        holdout_manifest_sha256: str,
        canary_evidence_sha256: str,
        rollback_evidence_sha256: str,
        approved_by: str = "Test Human",
        expired: bool = False,
        expected_active_snapshot_id: str = "CTX-STATE-000",
        expected_active_version: int = 1,
        **overrides,
    ) -> dict:
        approved_at, expires_at = self.approval_window(expired=expired)
        approval = {
            "schema_version": "1.0",
            "approval_id": f"APPROVAL-{epoch_id}",
            "decision": "promote",
            "human_approved": True,
            "approved_by": approved_by,
            "approved_at": approved_at,
            "expires_at": expires_at,
            "epoch_id": epoch_id,
            "summary_sha256": summary_sha256,
            "candidate_snapshot_id": candidate_snapshot_id,
            "expected_active_snapshot_id": expected_active_snapshot_id,
            "expected_active_version": expected_active_version,
            "holdout_manifest_sha256": holdout_manifest_sha256,
            "canary_evidence_sha256": canary_evidence_sha256,
            "rollback_evidence_sha256": rollback_evidence_sha256,
            "fresh_holdout_attested": True,
            "grader_independence_attested": True,
            "canary_completed": True,
            "rollback_tested": True,
        }
        approval.update(overrides)
        return approval

    def fabricate_full_eligible_epoch(
        self,
        *,
        epoch_id: str = "EPOCH-FULL-ELIGIBLE",
        holdout_overrides: dict | None = None,
    ) -> tuple[dict, dict]:
        candidate = self.add_candidate(proposal_id=f"PROP-{epoch_id}")
        candidate_id = candidate["candidate_snapshot_id"]
        state_loop.create_plan(
            self.connection,
            self.instance,
            stage="smoke",
            candidate_snapshot_id=candidate_id,
            epoch_id=epoch_id,
        )
        manifest_ref = state_loop.put_json_artifact(
            self.connection,
            self.instance,
            {
                "schema_version": "1.0",
                "split": "holdout",
                "fresh": True,
                "sealed_before_run": True,
                "optimizer_visible": False,
                "spent_after_reveal": True,
                "episode_count": 24,
            },
        )
        canary_ref = state_loop.put_json_artifact(
            self.connection,
            self.instance,
            {"schema_version": "1.0", "canary": "pass", "critical_failures": 0},
        )
        rollback_ref = state_loop.put_json_artifact(
            self.connection,
            self.instance,
            {"schema_version": "1.0", "rollback_drill": "pass", "target": "CTX-STATE-000"},
        )
        holdout = {
            "fresh": True,
            "sealed_before_run": True,
            "optimizer_visible": False,
            "spent_after_reveal": True,
            "grader_independent": True,
            "manifest_sha256": manifest_ref.sha256,
        }
        holdout.update(holdout_overrides or {})
        summary = {
            "schema_version": "1.0",
            "epoch_id": epoch_id,
            "stage": "full",
            "status": "eligible_for_human_review",
            "evidence_state": "human-final",
            "promotion_gates": {
                "stage_is_full": True,
                "human_final": True,
                "no_critical_gates": True,
                "task_delta_lcb": True,
                "pairwise_lcb": True,
                "family_floor": True,
                "requirement_preservation": True,
                "context_precision": True,
                "stale_rate": True,
                "cost": True,
            },
            "holdout": holdout,
        }
        summary_ref = state_loop.put_json_artifact(
            self.connection, self.instance, summary
        )
        self.connection.execute(
            "UPDATE epochs SET stage='full',status='eligible_for_human_review',summary_sha256=? "
            "WHERE epoch_id=?",
            (summary_ref.sha256, epoch_id),
        )
        evidence = {
            "summary_sha256": summary_ref.sha256,
            "holdout_manifest_sha256": manifest_ref.sha256,
            "canary_evidence_sha256": canary_ref.sha256,
            "rollback_evidence_sha256": rollback_ref.sha256,
        }
        return candidate, evidence

    def test_approval_schemas_encode_named_human_and_recovery_gates(self) -> None:
        promotion_schema = state_loop.load_json(
            LAB_ROOT / "schemas" / "promotion-approval.schema.json"
        )
        rollback_schema = state_loop.load_json(
            LAB_ROOT / "schemas" / "rollback-approval.schema.json"
        )
        self.assertFalse(promotion_schema["additionalProperties"])
        self.assertEqual(promotion_schema["properties"]["decision"]["const"], "promote")
        self.assertEqual(promotion_schema["properties"]["human_approved"]["const"], True)
        self.assertTrue(
            {
                "holdout_manifest_sha256",
                "canary_evidence_sha256",
                "rollback_evidence_sha256",
                "fresh_holdout_attested",
                "grader_independence_attested",
                "canary_completed",
                "rollback_tested",
            }.issubset(promotion_schema["required"])
        )
        self.assertFalse(rollback_schema["additionalProperties"])
        self.assertEqual(rollback_schema["properties"]["decision"]["const"], "rollback")
        self.assertTrue(
            {"rollback_snapshot_id", "reason", "expected_active_version"}.issubset(
                rollback_schema["required"]
            )
        )

    def test_promotion_rejects_development_stages(self) -> None:
        candidate = self.add_candidate(proposal_id="PROP-DEVELOPMENT-PROMOTION")
        candidate_id = candidate["candidate_snapshot_id"]
        zeros = "0" * 64
        for stage in ("smoke", "pilot"):
            with self.subTest(stage=stage):
                epoch_id = f"EPOCH-{stage.upper()}-NOT-PROMOTABLE"
                state_loop.create_plan(
                    self.connection,
                    self.instance,
                    stage=stage,
                    candidate_snapshot_id=candidate_id,
                    epoch_id=epoch_id,
                )
                approval = self.promotion_approval(
                    epoch_id=epoch_id,
                    candidate_snapshot_id=candidate_id,
                    summary_sha256=zeros,
                    holdout_manifest_sha256=zeros,
                    canary_evidence_sha256=zeros,
                    rollback_evidence_sha256=zeros,
                )
                with self.assertRaisesRegex(
                    state_loop.StateLoopError, "eligible full holdout"
                ):
                    state_loop.promote_candidate(
                        self.connection, self.instance, epoch_id, approval
                    )

    def test_promotion_rejects_agent_approver_and_expired_approval(self) -> None:
        zeros = "0" * 64
        common = {
            "epoch_id": "EPOCH-APPROVAL-BOUNDARY",
            "candidate_snapshot_id": "CTX-CANDIDATE",
            "summary_sha256": zeros,
            "holdout_manifest_sha256": zeros,
            "canary_evidence_sha256": zeros,
            "rollback_evidence_sha256": zeros,
        }
        agent_approval = self.promotion_approval(**common, approved_by="codex")
        with self.assertRaisesRegex(state_loop.StateLoopError, "human, not an agent"):
            state_loop.promote_candidate(
                self.connection,
                self.instance,
                common["epoch_id"],
                agent_approval,
            )

        expired_approval = self.promotion_approval(**common, expired=True)
        with self.assertRaisesRegex(state_loop.StateLoopError, "not currently valid"):
            state_loop.promote_candidate(
                self.connection,
                self.instance,
                common["epoch_id"],
                expired_approval,
            )

    def test_promotion_rejects_stale_active_pointer(self) -> None:
        epoch_id = "EPOCH-FULL-STALE-POINTER"
        candidate, evidence = self.fabricate_full_eligible_epoch(epoch_id=epoch_id)
        approval = self.promotion_approval(
            epoch_id=epoch_id,
            candidate_snapshot_id=candidate["candidate_snapshot_id"],
            expected_active_version=2,
            **evidence,
        )
        with self.assertRaisesRegex(state_loop.ConflictError, "Active context changed"):
            state_loop.promote_candidate(self.connection, self.instance, epoch_id, approval)

    def test_promotion_requires_holdout_attestations_in_approval_and_summary(self) -> None:
        epoch_id = "EPOCH-FULL-HOLDOUT-APPROVAL"
        candidate, evidence = self.fabricate_full_eligible_epoch(epoch_id=epoch_id)
        approval = self.promotion_approval(
            epoch_id=epoch_id,
            candidate_snapshot_id=candidate["candidate_snapshot_id"],
            fresh_holdout_attested=False,
            **evidence,
        )
        with self.assertRaisesRegex(state_loop.StateLoopError, "not attested"):
            state_loop.promote_candidate(self.connection, self.instance, epoch_id, approval)

        other_instance = Path(self.temporary_directory.name) / "inconsistent-holdout"
        state_loop.initialize_instance(other_instance)
        other_connection = state_loop.connect(other_instance)
        old_connection, old_instance = self.connection, self.instance
        self.connection, self.instance = other_connection, other_instance
        try:
            inconsistent_epoch = "EPOCH-FULL-HOLDOUT-SUMMARY"
            candidate, evidence = self.fabricate_full_eligible_epoch(
                epoch_id=inconsistent_epoch,
                holdout_overrides={"optimizer_visible": True},
            )
            approval = self.promotion_approval(
                epoch_id=inconsistent_epoch,
                candidate_snapshot_id=candidate["candidate_snapshot_id"],
                **evidence,
            )
            with self.assertRaisesRegex(
                state_loop.StateLoopError, "Fresh sealed holdout attestations"
            ):
                state_loop.promote_candidate(
                    self.connection, self.instance, inconsistent_epoch, approval
                )
        finally:
            self.connection, self.instance = old_connection, old_instance
            other_connection.close()

    def test_successful_human_promotion_and_rollback_to_ancestor_are_auditable(self) -> None:
        epoch_id = "EPOCH-FULL-SUCCESS"
        candidate, evidence = self.fabricate_full_eligible_epoch(epoch_id=epoch_id)
        candidate_id = candidate["candidate_snapshot_id"]
        approval = self.promotion_approval(
            epoch_id=epoch_id,
            candidate_snapshot_id=candidate_id,
            **evidence,
        )
        promoted = state_loop.promote_candidate(
            self.connection, self.instance, epoch_id, approval
        )
        accepted_id = promoted["accepted_snapshot_id"]
        self.assertEqual(promoted["status"], "promoted")
        self.assertEqual(state_loop.get_active_snapshot_id(self.connection), (accepted_id, 2))
        self.assertEqual(
            self.connection.execute(
                "SELECT status FROM snapshots WHERE snapshot_id=?", (candidate_id,)
            ).fetchone()[0],
            "promoted",
        )
        self.assertEqual(
            self.connection.execute(
                "SELECT status FROM epochs WHERE epoch_id=?", (epoch_id,)
            ).fetchone()[0],
            "promoted",
        )
        self.assertEqual(state_loop.audit_instance(self.connection, self.instance)["status"], "pass")

        approved_at, expires_at = self.approval_window()
        rollback_approval = {
            "schema_version": "1.0",
            "approval_id": "APPROVAL-ROLLBACK-SUCCESS",
            "decision": "rollback",
            "human_approved": True,
            "approved_by": "Test Human",
            "approved_at": approved_at,
            "expires_at": expires_at,
            "expected_active_snapshot_id": accepted_id,
            "expected_active_version": 2,
            "rollback_snapshot_id": "CTX-STATE-000",
            "reason": "Canary regression observed after promotion.",
        }
        rolled_back = state_loop.rollback_context(
            self.connection, self.instance, rollback_approval
        )
        self.assertEqual(rolled_back["status"], "rolled_back")
        self.assertEqual(state_loop.get_active_snapshot_id(self.connection), ("CTX-STATE-000", 3))
        self.assertEqual(
            self.connection.execute(
                "SELECT status FROM snapshots WHERE snapshot_id=?", (accepted_id,)
            ).fetchone()[0],
            "rolled_back",
        )
        self.assertEqual(state_loop.audit_instance(self.connection, self.instance)["status"], "pass")


if __name__ == "__main__":
    unittest.main()
