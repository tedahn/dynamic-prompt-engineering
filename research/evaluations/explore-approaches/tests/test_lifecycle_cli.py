from __future__ import annotations

import importlib.util
import json
import os
import subprocess
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

    def test_git_head_ignores_hostile_git_routing_and_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target"
            foreign = root / "foreign"
            clean_env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
            clean_env.update({"LANG": "C", "LC_ALL": "C"})

            def create_repository(path: Path, content: str) -> str:
                path.mkdir()
                subprocess.run(["git", "init", "-b", "main"], cwd=path, env=clean_env, check=True, capture_output=True)
                subprocess.run(["git", "config", "user.name", "Lifecycle Test"], cwd=path, env=clean_env, check=True)
                subprocess.run(["git", "config", "user.email", "lifecycle@example.invalid"], cwd=path, env=clean_env, check=True)
                (path / "payload.txt").write_text(content, encoding="utf-8")
                subprocess.run(["git", "add", "payload.txt"], cwd=path, env=clean_env, check=True)
                subprocess.run(["git", "commit", "-m", content], cwd=path, env=clean_env, check=True, capture_output=True)
                return subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=path,
                    env=clean_env,
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()

            expected_head = create_repository(target, "target")
            foreign_head = create_repository(foreign, "foreign")
            self.assertNotEqual(expected_head, foreign_head)
            hostile_config = root / "hostile.gitconfig"
            hostile_config.write_text("[core]\n\tbare = true\n", encoding="utf-8")
            hostile_env = {
                "GIT_DIR": str(foreign / ".git"),
                "GIT_WORK_TREE": str(foreign),
                "GIT_OBJECT_DIRECTORY": str(foreign / ".git" / "objects"),
                "GIT_ALTERNATE_OBJECT_DIRECTORIES": str(foreign / ".git" / "objects"),
                "GIT_INDEX_FILE": str(foreign / ".git" / "index"),
                "GIT_REPLACE_REF_BASE": "refs/hostile-replacements/",
                "GIT_CONFIG_SYSTEM": str(hostile_config),
                "GIT_CONFIG_GLOBAL": str(hostile_config),
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "core.bare",
                "GIT_CONFIG_VALUE_0": "true",
            }
            with (
                mock.patch.dict(os.environ, hostile_env, clear=False),
                mock.patch("subprocess.run", wraps=subprocess.run) as runner,
            ):
                resolved = CLI._git_head(target)

            self.assertEqual(resolved, expected_head)
            argv = runner.call_args.args[0]
            supplied_env = runner.call_args.kwargs["env"]
            self.assertIn("--no-replace-objects", argv)
            for key in hostile_env:
                if key not in {"GIT_CONFIG_GLOBAL"}:
                    self.assertNotIn(key, supplied_env)
            self.assertEqual(supplied_env["GIT_CONFIG_GLOBAL"], os.devnull)
            self.assertEqual(supplied_env["GIT_CONFIG_NOSYSTEM"], "1")

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

    def test_promotion_reverifies_evidence_after_signed_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            approval = run_dir / "approval.json"
            CLI.atomic_write_json(approval, {"signed": True})
            with (
                mock.patch.object(CLI, "_verified_plan", return_value=({"candidate_manifest_sha256": "a" * 64}, {})),
                mock.patch.object(CLI, "verify_frozen_holdout_signature"),
                mock.patch.object(
                    CLI,
                    "verify_evidence_manifest",
                    side_effect=CLI.PipelineError("after-signature evidence mutation"),
                ),
            ):
                with self.assertRaisesRegex(CLI.PipelineError, "after-signature evidence mutation"):
                    CLI._verify_promotion_inputs(run_dir, approval, {})

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

    def test_approval_template_reverifies_final_evidence_and_binds_private_map(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            summary = {"completed_at": "2026-07-30T12:00:00Z", "evidence": {}}
            assessment = {"classification": "promotable", "promotable": True}
            plan = {
                "base_commit": "a" * 40,
                "blind_key_commitment": "b" * 64,
                "protocol_sha256": "c" * 64,
                "rubric_sha256": "d" * 64,
                "config_sha256": "e" * 64,
                "lifecycle_executables_sha256": "f" * 64,
            }
            candidate_manifest = {"manifest_sha256": "1" * 64}
            evidence_manifest = {
                "blind_map_sha256": "2" * 64,
                "artifacts": {
                    "blind_map": {
                        "path": "private/grading/blind-map.jsonl",
                        "sha256": "2" * 64,
                    }
                },
            }
            config = {
                "candidate": {"name": "explore-approaches", "version": "explore-approaches-v0.1.0"},
                "approval_verification": {
                    "expected_identity": "Named Human",
                    "namespace": "codex-skill-promotion",
                },
                "promotion": {
                    "repository_url": "https://github.com/example/repo.git",
                    "repository_slug": "example/repo",
                    "base_branch": "main",
                    "feature_branch": "codex/explore-approaches-v0.1.0",
                },
                "installation": {"skills_root": "/tmp/root-skills", "skill_name": "explore-approaches"},
            }
            for path, value in (
                (run_dir / "plan.json", plan),
                (run_dir / "evaluation-summary.json", summary),
                (run_dir / "assessment.json", assessment),
                (run_dir / "evidence-manifest.json", {"synthetic": True}),
                (run_dir / "holdout-manifest.json", {"synthetic": True}),
                (run_dir / "rollback-evidence.json", {"result": "passed"}),
            ):
                CLI.atomic_write_json(path, value)
            with (
                mock.patch.object(CLI, "assess_summary", return_value=assessment),
                mock.patch.object(CLI, "verify_evidence_manifest", return_value=evidence_manifest) as verifier,
                mock.patch.object(CLI, "_manifest", return_value=candidate_manifest),
            ):
                template = CLI._approval_template(run_dir, config)
            verifier.assert_called_once_with(run_dir, config)
            self.assertEqual(template["evidence"]["blind_key_commitment"], plan["blind_key_commitment"])
            self.assertEqual(template["evidence"]["blind_map_path"], "private/grading/blind-map.jsonl")
            self.assertEqual(template["evidence"]["blind_map_sha256"], "2" * 64)

    def test_freeze_recovers_plan_before_lifecycle_events(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            CLI.atomic_write_json(run_dir / "plan.json", {"placeholder": True})
            plan = {
                "run_id": "EA-recovery",
                "plan_sha256": "d" * 64,
                "candidate_manifest_sha256": "a" * 64,
                "blind_key_commitment": "e" * 64,
                "holdout_manifest_sha256": "b" * 64,
                "holdout": {"sha256": "c" * 64},
            }
            manifest = {"manifest_sha256": "a" * 64}
            store, lifecycle = CLI._lifecycle(run_dir)
            try:
                with (
                    mock.patch.object(CLI, "role_bindings", return_value={}),
                    mock.patch.object(CLI, "_manifest", return_value=manifest),
                    mock.patch.object(CLI, "_verified_plan", return_value=(plan, {})),
                    mock.patch.object(CLI, "verify_frozen_holdout_signature") as signature_check,
                ):
                    self.assertEqual(CLI._freeze(run_dir, None, None, {}, lifecycle), plan)
                signature_check.assert_called_once_with(run_dir, {})
                self.assertEqual(lifecycle.current["state"], "holdout-ready")
                holdout_event = next(
                    row
                    for row in store.events(lifecycle.stream)
                    if row["event_type"] == "SIGNED_HOLDOUT_VALIDATED"
                )
                event_payload = json.loads(holdout_event["payload_json"])
                self.assertEqual(event_payload["plan_sha256"], plan["plan_sha256"])
                self.assertEqual(event_payload["blind_key_commitment"], plan["blind_key_commitment"])
            finally:
                store.close()

    def test_preseeded_plan_cannot_advance_without_reverified_custody_signature(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            CLI.atomic_write_json(run_dir / "plan.json", {"placeholder": True})
            manifest = {"manifest_sha256": "a" * 64}
            plan = {
                "run_id": "EA-forged",
                "plan_sha256": "d" * 64,
                "candidate_manifest_sha256": manifest["manifest_sha256"],
                "blind_key_commitment": "e" * 64,
                "holdout_manifest_sha256": "b" * 64,
                "holdout": {"sha256": "c" * 64},
            }
            store, lifecycle = CLI._lifecycle(run_dir)
            try:
                with (
                    mock.patch.object(CLI, "role_bindings", return_value={}),
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

    def test_resume_rejects_legacy_holdout_event_without_plan_and_key_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            CLI.atomic_write_json(run_dir / "plan.json", {"placeholder": True})
            manifest = {"manifest_sha256": "a" * 64}
            plan = {
                "run_id": "EA-legacy-event",
                "plan_sha256": "d" * 64,
                "candidate_manifest_sha256": manifest["manifest_sha256"],
                "blind_key_commitment": "e" * 64,
                "holdout_manifest_sha256": "b" * 64,
                "holdout": {"sha256": "c" * 64},
            }
            store, lifecycle = CLI._lifecycle(run_dir)
            try:
                lifecycle.advance(
                    "frozen",
                    "CANDIDATE_FROZEN",
                    {"sha256": manifest["manifest_sha256"]},
                    actor="test",
                    idempotency_key="test:frozen",
                )
                lifecycle.advance(
                    "holdout-ready",
                    "SIGNED_HOLDOUT_VALIDATED",
                    {
                        "sha256": plan["holdout_manifest_sha256"],
                        "holdout_sha256": plan["holdout"]["sha256"],
                        "run_id": plan["run_id"],
                    },
                    actor="test",
                    idempotency_key="test:legacy-holdout-ready",
                )
                with (
                    mock.patch.object(CLI, "role_bindings", return_value={}),
                    mock.patch.object(CLI, "_manifest", return_value=manifest),
                    mock.patch.object(CLI, "_verified_plan", return_value=(plan, {})),
                    mock.patch.object(CLI, "verify_frozen_holdout_signature"),
                ):
                    with self.assertRaisesRegex(CLI.PipelineError, "frozen plan and blind key"):
                        CLI._freeze(run_dir, None, None, {}, lifecycle)
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
                "promotion": {
                    "repository_url": "https://example.invalid/repo.git",
                    "automation_actor": "automation",
                    "required_reviewer_logins": ["reviewer"],
                },
                "installation": {"skills_root": str(run_dir / "root"), "skill_name": "explore-approaches"},
            }
            prepared = {
                "clone": str(run_dir / "clone"),
                "base_commit": "a" * 40,
                "head_commit": "c" * 40,
                "staged_paths": ["skills/explore-approaches/SKILL.md"],
            }
            opened = {"pr_url": "https://example.invalid/pr/1", "head_commit": "c" * 40, "opened_at": "2026-07-30T12:00:00Z", "github_actor": "automation"}
            merged = {
                "pr_url": opened["pr_url"],
                "head_commit": opened["head_commit"],
                "merge_commit": "d" * 40,
                "merged_at": "2026-07-30T12:30:00Z",
                "github_evidence": {"approved_reviewers": ["reviewer"], "successful_checks": ["validate"], "github_actor": "automation"},
                "github_actor": "automation",
            }
            receipt = {"record_sha256": "e" * 64, "merge_commit": merged["merge_commit"], "status": "installed"}
            execution_path = run_dir / "execution.json"
            execution_path.write_text("{}\n", encoding="utf-8")

            store, lifecycle = self._awaiting_lifecycle(run_dir)
            try:
                with (
                    mock.patch.object(CLI, "_verify_promotion_inputs", return_value=approval),
                    mock.patch.object(CLI, "_manifest", return_value=manifest),
                    mock.patch.object(CLI, "prepare_clean_promotion", return_value=prepared),
                    mock.patch.object(CLI, "validate_prepared_promotion", return_value=prepared),
                    mock.patch.object(CLI, "push_and_open_pr", return_value=opened),
                    mock.patch.object(CLI, "verify_github_actor", return_value="automation"),
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
                    mock.patch.object(
                        CLI,
                        "_verified_execution_authorization",
                        return_value=(execution_path, {"run": {}, "authority": {}}),
                    ),
                ):
                    installed = CLI._merge_and_install(
                        run_dir,
                        approval_path,
                        config,
                        lifecycle,
                        execution_path,
                        True,
                    )
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
                "promotion": {
                    "repository_url": "https://example.invalid/repo.git",
                    "automation_actor": "automation",
                    "required_reviewer_logins": ["reviewer"],
                },
                "installation": {"skills_root": str(run_dir / "root"), "skill_name": "explore-approaches"},
            }
            prepared = {"clone": str(run_dir / "clone"), "base_commit": "a" * 40, "head_commit": "c" * 40, "staged_paths": []}
            opened = {"pr_url": "https://example.invalid/pr/1", "head_commit": "c" * 40, "opened_at": "2026-07-30T12:00:00Z", "github_actor": "automation"}
            verified_merge = {"pr_url": opened["pr_url"], "head_commit": opened["head_commit"], "merge_commit": "d" * 40, "merged_at": "2026-07-30T12:30:00Z", "github_evidence": {"approved_reviewers": ["reviewer"], "successful_checks": ["validate"], "github_actor": "automation"}, "github_actor": "automation"}
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
