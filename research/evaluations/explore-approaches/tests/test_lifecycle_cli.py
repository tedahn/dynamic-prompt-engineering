from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock


EVALUATION_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = EVALUATION_ROOT / "scripts" / "automate_lifecycle.py"
SPEC = importlib.util.spec_from_file_location("automate_lifecycle", MODULE_PATH)
assert SPEC and SPEC.loader
CLI = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CLI)


class LifecycleCliTest(unittest.TestCase):
    def _awaiting_lifecycle(self, run_dir: Path):
        store, lifecycle = CLI._lifecycle(run_dir)
        for next_state in ("frozen", "holdout-ready", "running", "grading"):
            lifecycle.advance(
                next_state,
                f"TEST_{next_state}",
                {"sha256": next_state},
                actor="test",
                idempotency_key=f"test:{next_state}",
            )
        summary_path = run_dir / "evaluation-summary.json"
        if not summary_path.is_file():
            CLI.atomic_write_json(summary_path, {"synthetic": True})
        summary_sha256 = CLI.sha256_file(summary_path)
        lifecycle.advance(
            "promotable",
            "EVIDENCE_CLASSIFIED",
            {"sha256": summary_sha256, "classification": "promotable"},
            actor="test",
            idempotency_key="test:promotable",
        )
        lifecycle.advance(
            "awaiting-human-approval",
            "HUMAN_APPROVAL_REQUESTED",
            {"sha256": summary_sha256},
            actor="test",
            idempotency_key="test:awaiting-human-approval",
        )
        return store, lifecycle

    def test_frozen_config_is_used_instead_of_caller_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            configured = run_dir / "configured.json"
            CLI.atomic_write_json(configured, CLI.load_json(CLI.DEFAULT_CONFIG))
            frozen = CLI._config(configured)
            CLI.atomic_write_json(run_dir / "frozen" / "config.json", frozen)
            CLI.atomic_write_json(run_dir / "plan.json", {"config_sha256": CLI.sha256_json(frozen)})
            self.assertEqual(CLI._config(configured, run_dir), frozen)
            substituted = CLI.load_json(CLI.DEFAULT_CONFIG)
            substituted["candidate"]["name"] = "attacker"
            CLI.atomic_write_json(configured, substituted)
            with self.assertRaisesRegex(CLI.PipelineError, "configuration hash mismatch"):
                CLI._config(configured, run_dir)

    def test_approval_template_rejects_non_promotable_or_tampered_assessment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            summary = {"completed_at": "2026-07-30T12:00:00Z"}
            assessment = {"classification": "inconclusive", "promotable": False}
            CLI.atomic_write_json(run_dir / "plan.json", {"base_commit": "a" * 40})
            CLI.atomic_write_json(run_dir / "evaluation-summary.json", summary)
            CLI.atomic_write_json(run_dir / "assessment.json", assessment)
            with mock.patch.object(CLI, "assess_summary", return_value=assessment):
                with self.assertRaisesRegex(CLI.PipelineError, "inconclusive evidence"):
                    CLI._approval_template(run_dir, {})

            CLI.atomic_write_json(run_dir / "assessment.json", {"classification": "promotable", "promotable": True})
            with mock.patch.object(CLI, "assess_summary", return_value=assessment):
                with self.assertRaisesRegex(CLI.PipelineError, "Recorded assessment differs"):
                    CLI._approval_template(run_dir, {})

    def test_freeze_recovers_plan_before_lifecycle_events(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            CLI.atomic_write_json(run_dir / "plan.json", {"placeholder": True})
            plan = {
                "run_id": "EA-recovery",
                "candidate_manifest_sha256": "a" * 64,
                "holdout_manifest_sha256": "b" * 64,
                "holdout": {"sha256": "c" * 64},
            }
            manifest = {"manifest_sha256": "a" * 64}
            store, lifecycle = CLI._lifecycle(run_dir)
            try:
                with (
                    mock.patch.object(CLI, "_manifest", return_value=manifest),
                    mock.patch.object(CLI, "_verified_plan", return_value=(plan, {})),
                    mock.patch.object(CLI, "verify_frozen_holdout_signature") as signature_check,
                ):
                    self.assertEqual(CLI._freeze(run_dir, None, None, {}, lifecycle), plan)
                signature_check.assert_called_once_with(run_dir, {})
                self.assertEqual(lifecycle.current["state"], "holdout-ready")
            finally:
                store.close()

    def test_preseeded_plan_cannot_advance_without_reverified_custody_signature(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            CLI.atomic_write_json(run_dir / "plan.json", {"placeholder": True})
            manifest = {"manifest_sha256": "a" * 64}
            plan = {
                "run_id": "EA-forged",
                "candidate_manifest_sha256": manifest["manifest_sha256"],
                "holdout_manifest_sha256": "b" * 64,
                "holdout": {"sha256": "c" * 64},
            }
            store, lifecycle = CLI._lifecycle(run_dir)
            try:
                with (
                    mock.patch.object(CLI, "_manifest", return_value=manifest),
                    mock.patch.object(CLI, "_verified_plan", return_value=(plan, {})),
                    mock.patch.object(
                        CLI,
                        "verify_frozen_holdout_signature",
                        side_effect=CLI.PipelineError("forged custody signature"),
                    ),
                ):
                    with self.assertRaisesRegex(CLI.PipelineError, "forged custody signature"):
                        CLI._freeze(run_dir, None, None, {}, lifecycle)
                self.assertEqual(lifecycle.current["state"], "draft")
            finally:
                store.close()

    def test_pr_release_and_install_receipts_are_event_bound_and_resumable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            approval_path = run_dir / "approval.json"
            approval_path.write_text("{}\n", encoding="utf-8")
            approval = {
                "approval_id": "APPROVAL-test",
                "candidate": {"base_commit": "a" * 40},
            }
            manifest = {"manifest_sha256": "b" * 64}
            config = {
                "candidate": {"skill_path": "skills/explore-approaches"},
                "promotion": {"repository_url": "https://example.invalid/repo.git"},
                "installation": {"skills_root": str(run_dir / "root"), "skill_name": "explore-approaches"},
            }
            prepared = {
                "clone": str(run_dir / "clone"),
                "base_commit": "a" * 40,
                "head_commit": "c" * 40,
                "staged_paths": ["skills/explore-approaches/SKILL.md"],
            }
            opened = {"pr_url": "https://example.invalid/pr/1", "head_commit": "c" * 40, "opened_at": "2026-07-30T12:00:00Z"}
            merged = {
                "pr_url": opened["pr_url"],
                "head_commit": opened["head_commit"],
                "merge_commit": "d" * 40,
                "merged_at": "2026-07-30T12:30:00Z",
                "github_evidence": {"approved_reviewers": ["reviewer"], "successful_checks": ["validate"]},
            }
            receipt = {"record_sha256": "e" * 64, "merge_commit": merged["merge_commit"], "status": "installed"}

            store, lifecycle = self._awaiting_lifecycle(run_dir)
            try:
                with (
                    mock.patch.object(CLI, "_verify_promotion_inputs", return_value=approval),
                    mock.patch.object(CLI, "_manifest", return_value=manifest),
                    mock.patch.object(CLI, "prepare_clean_promotion", return_value=prepared),
                    mock.patch.object(CLI, "validate_prepared_promotion", return_value=prepared),
                    mock.patch.object(CLI, "push_and_open_pr", return_value=opened),
                ):
                    pr_record = CLI._promote(run_dir, approval_path, config, lifecycle, True)
                    self.assertEqual(lifecycle.current["state"], "pr-open")
                    self.assertEqual(pr_record["status"], "pr-open")
                    resumed = CLI._promote(run_dir, approval_path, config, lifecycle, True)
                    self.assertEqual(resumed["record_sha256"], pr_record["record_sha256"])

                with (
                    mock.patch.object(CLI, "_verify_promotion_inputs", return_value=approval),
                    mock.patch.object(CLI, "_manifest", return_value=manifest),
                    mock.patch.object(CLI, "merge_reviewed_pr", return_value=merged),
                    mock.patch.object(CLI, "checkout_immutable_merge", return_value=run_dir / "checkout"),
                    mock.patch.object(CLI, "verify_merge_reachable"),
                    mock.patch.object(CLI, "verify_merged_candidate", return_value={"SKILL.md": "f" * 64}),
                    mock.patch.object(CLI, "verify_installed_candidate", return_value={"SKILL.md": "f" * 64}),
                    mock.patch.object(CLI, "atomic_install", return_value=receipt),
                ):
                    installed = CLI._merge_and_install(run_dir, approval_path, config, lifecycle)
                    self.assertEqual(lifecycle.current["state"], "active")
                    self.assertEqual(installed, receipt)

                with (
                    mock.patch.object(CLI, "_verify_promotion_inputs", return_value=approval),
                    mock.patch.object(CLI, "_manifest", return_value=manifest),
                    mock.patch.object(CLI, "merge_reviewed_pr", return_value=merged),
                    mock.patch.object(CLI, "verify_installed_candidate", return_value={"SKILL.md": "f" * 64}),
                    mock.patch.object(CLI, "validate_installation_receipt", return_value=receipt),
                ):
                    self.assertEqual(CLI._merge_and_install(run_dir, None, config, lifecycle), receipt)
                (run_dir / "verified-approval.json").unlink()
                with self.assertRaisesRegex(CLI.PipelineError, "lacks the exact persisted signed approval"):
                    CLI._merge_and_install(run_dir, None, config, lifecycle)
            finally:
                store.close()

    def test_pre_event_prepared_receipt_cannot_cross_promotion_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            approval_path = run_dir / "approval.json"
            approval_path.write_text("{}\n", encoding="utf-8")
            approval = {"approval_id": "APPROVAL-test", "candidate": {"base_commit": "a" * 40}}
            manifest = {"manifest_sha256": "b" * 64}
            prepared = CLI.write_immutable_record(
                run_dir / "prepared-promotion.json",
                {"clone": str(run_dir / "forged"), "base_commit": "a" * 40, "head_commit": "c" * 40},
            )
            store, lifecycle = self._awaiting_lifecycle(run_dir)
            try:
                with (
                    mock.patch.object(CLI, "_verify_promotion_inputs", return_value=approval),
                    mock.patch.object(CLI, "_manifest", return_value=manifest),
                    mock.patch.object(
                        CLI,
                        "validate_prepared_promotion",
                        side_effect=CLI.PipelineError("forged prepared receipt"),
                    ),
                    mock.patch.object(CLI, "push_and_open_pr") as push,
                ):
                    with self.assertRaisesRegex(CLI.PipelineError, "forged prepared receipt"):
                        CLI._promote(run_dir, approval_path, {}, lifecycle, True)
                self.assertEqual(lifecycle.current["state"], "approved")
                push.assert_not_called()
                self.assertEqual(prepared["base_commit"], "a" * 40)
            finally:
                store.close()

    def test_pre_event_release_receipt_must_match_fresh_github_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            approval_path = run_dir / "approval.json"
            approval_path.write_text("{}\n", encoding="utf-8")
            approval = {"approval_id": "APPROVAL-test", "candidate": {"base_commit": "a" * 40}}
            manifest = {"manifest_sha256": "b" * 64}
            config = {
                "candidate": {"skill_path": "skills/explore-approaches"},
                "promotion": {"repository_url": "https://example.invalid/repo.git"},
                "installation": {"skills_root": str(run_dir / "root"), "skill_name": "explore-approaches"},
            }
            prepared = {"clone": str(run_dir / "clone"), "base_commit": "a" * 40, "head_commit": "c" * 40, "staged_paths": []}
            opened = {"pr_url": "https://example.invalid/pr/1", "head_commit": "c" * 40, "opened_at": "2026-07-30T12:00:00Z"}
            verified_merge = {"pr_url": opened["pr_url"], "head_commit": opened["head_commit"], "merge_commit": "d" * 40, "merged_at": "2026-07-30T12:30:00Z", "github_evidence": {"approved_reviewers": ["reviewer"], "successful_checks": ["validate"]}}
            forged_merge = {**verified_merge, "merge_commit": "e" * 40}
            store, lifecycle = self._awaiting_lifecycle(run_dir)
            try:
                with (
                    mock.patch.object(CLI, "_verify_promotion_inputs", return_value=approval),
                    mock.patch.object(CLI, "_manifest", return_value=manifest),
                    mock.patch.object(CLI, "prepare_clean_promotion", return_value=prepared),
                    mock.patch.object(CLI, "validate_prepared_promotion", return_value=prepared),
                    mock.patch.object(CLI, "push_and_open_pr", return_value=opened),
                ):
                    pr_record = CLI._promote(run_dir, approval_path, config, lifecycle, True)
                CLI.write_immutable_record(run_dir / "release-record.json", CLI.build_release_record(pr_record, forged_merge))
                with (
                    mock.patch.object(CLI, "_verify_promotion_inputs", return_value=approval),
                    mock.patch.object(CLI, "_manifest", return_value=manifest),
                    mock.patch.object(CLI, "merge_reviewed_pr", return_value=verified_merge),
                    mock.patch.object(CLI, "checkout_immutable_merge") as checkout,
                ):
                    with self.assertRaisesRegex(CLI.PipelineError, "differs from current verified GitHub"):
                        CLI._merge_and_install(run_dir, approval_path, config, lifecycle)
                self.assertEqual(lifecycle.current["state"], "pr-open")
                checkout.assert_not_called()
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
