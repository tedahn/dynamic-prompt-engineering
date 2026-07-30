from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from automation.core import PipelineError, sha256_file
from automation.execution_authorization import (
    REQUIRED_STOP_CONDITIONS,
    reserve_provider_call,
    role_bindings,
    validate_execution_authorization,
    verify_billed_token_telemetry,
)
from automation.evaluation import invoke_adapter
from automation.promotion import (
    _stage_install_source,
    atomic_install,
    installation_lock,
    rollback_active_install,
    run_canary,
)


class ExecutionSafetyTest(unittest.TestCase):
    def _governance_config(self, root: Path) -> dict:
        roles = {
            "candidate_author": "candidate-author",
            "holdout_owner": "holdout-owner",
            "human_reviewer_adjudicator": "human-adjudicator",
            "provider_execution_approver": "execution-approver",
            "promotion_owner": "promotion-owner",
            "automation_actor": "automation-bot",
            "pr_reviewer": "independent-reviewer",
        }
        limits = {
            "max_subject_calls": 4,
            "max_grader_calls": 3,
            "max_canary_calls": 1,
            "max_total_calls": 8,
            "max_transient_retries": 2,
            "max_billed_tokens_per_call": 100,
            "max_total_billed_tokens": 800,
            "max_authorization_ttl_seconds": 7200,
        }
        return {
            "roles": roles,
            "holdout_verification": {"expected_identity": roles["holdout_owner"]},
            "human_review_verification": {
                "expected_identity": roles["human_reviewer_adjudicator"]
            },
            "execution_verification": {
                "expected_identity": roles["provider_execution_approver"],
                "namespace": "codex-skill-provider-execution",
                "allowed_signers_path": str(root / "allowed-signers"),
            },
            "approval_verification": {"expected_identity": roles["promotion_owner"]},
            "promotion": {
                "automation_actor": roles["automation_actor"],
                "required_reviewer_logins": [roles["pr_reviewer"]],
            },
            "evaluation": {"max_transient_retries": 2},
            "provider_execution_limits": limits,
        }

    def _authorization(self, config: dict) -> tuple[dict, dict]:
        now = datetime.now(timezone.utc)
        plan = {
            "run_id": "EA-test",
            "frozen_at": (now - timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
            "plan_sha256": "1" * 64,
            "config_sha256": "2" * 64,
            "candidate_manifest_sha256": "3" * 64,
            "subject_runtime_sha256": "4" * 64,
            "lifecycle_executables_sha256": "5" * 64,
        }
        authority = {
            key: config["provider_execution_limits"][key]
            for key in (
                "max_subject_calls",
                "max_grader_calls",
                "max_canary_calls",
                "max_total_calls",
                "max_transient_retries",
                "max_billed_tokens_per_call",
                "max_total_billed_tokens",
            )
        }
        authority["stop_conditions"] = sorted(REQUIRED_STOP_CONDITIONS)
        from automation.execution_authorization import roles_sha256

        authorization = {
            "schema_version": "1.0",
            "authorization_id": "EXEC-test",
            "decision": "execute-provider-calls",
            "authorized_by": config["roles"]["provider_execution_approver"],
            "authorized_at": now.isoformat().replace("+00:00", "Z"),
            "expires_at": (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            "run": {
                "run_id": plan["run_id"],
                "plan_sha256": plan["plan_sha256"],
                "config_sha256": plan["config_sha256"],
                "candidate_manifest_sha256": plan["candidate_manifest_sha256"],
                "subject_runtime_sha256": plan["subject_runtime_sha256"],
                "lifecycle_executables_sha256": plan["lifecycle_executables_sha256"],
                "roles_sha256": roles_sha256(config),
            },
            "authority": authority,
            "signature": {
                "algorithm": "ssh-keygen-y",
                "identity": config["roles"]["provider_execution_approver"],
                "namespace": "codex-skill-provider-execution",
                "value": "test",
            },
        }
        return authorization, plan

    def test_roles_are_frozen_and_all_governed_identities_are_unique(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = self._governance_config(Path(temporary))
            self.assertEqual(role_bindings(config, require_resolved=True), config["roles"])
            config["roles"]["promotion_owner"] = config["roles"]["candidate_author"]
            config["approval_verification"]["expected_identity"] = config["roles"]["promotion_owner"]
            with self.assertRaisesRegex(PipelineError, "unique identities"):
                role_bindings(config, require_resolved=True)
            config = self._governance_config(Path(temporary))
            config["roles"]["promotion_owner"] = "ｃａｎｄｉｄａｔｅ－ａｕｔｈｏｒ"
            config["approval_verification"]["expected_identity"] = config["roles"]["promotion_owner"]
            with self.assertRaisesRegex(PipelineError, "unique identities"):
                role_bindings(config, require_resolved=True)

    def test_provider_cli_is_inert_without_the_explicit_execute_flag(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cli = Path(__file__).resolve().parents[1] / "scripts/automate_lifecycle.py"
            completed = subprocess.run(
                [sys.executable, str(cli), "run", "--run-dir", temporary],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 2)
            self.assertIn("requires --execute", completed.stderr)

    def test_execution_authorization_binds_plan_runtime_expiry_and_budgets(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = self._governance_config(Path(temporary))
            authorization, plan = self._authorization(config)
            validate_execution_authorization(
                authorization,
                config,
                plan,
                signature_verifier=lambda *_: None,
            )
            authorization["run"]["subject_runtime_sha256"] = "f" * 64
            with self.assertRaisesRegex(PipelineError, "frozen plan, runtime"):
                validate_execution_authorization(
                    authorization,
                    config,
                    plan,
                    signature_verifier=lambda *_: None,
                )

    def test_execution_authorization_rejects_future_issuance_and_excess_remaining_ttl(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            config = self._governance_config(Path(temporary))
            authorization, plan = self._authorization(config)
            now = datetime.now(timezone.utc)
            authorization["authorized_at"] = (now + timedelta(minutes=6)).isoformat().replace("+00:00", "Z")
            authorization["expires_at"] = (now + timedelta(hours=1)).isoformat().replace("+00:00", "Z")
            with self.assertRaisesRegex(PipelineError, "issued too far in the future"):
                validate_execution_authorization(
                    authorization,
                    config,
                    plan,
                    signature_verifier=lambda *_: None,
                )

            authorization, plan = self._authorization(config)
            authorized_at = now + timedelta(minutes=4)
            authorization["authorized_at"] = authorized_at.isoformat().replace("+00:00", "Z")
            authorization["expires_at"] = (
                authorized_at + timedelta(seconds=config["provider_execution_limits"]["max_authorization_ttl_seconds"])
            ).isoformat().replace("+00:00", "Z")
            with self.assertRaisesRegex(PipelineError, "maximum lifetime"):
                validate_execution_authorization(
                    authorization,
                    config,
                    plan,
                    signature_verifier=lambda *_: None,
                )

    def test_provider_budget_is_reserved_before_calls_and_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            config = self._governance_config(run_dir)
            authorization, _ = self._authorization(config)
            authorization["authority"]["max_subject_calls"] = 1
            authorization["authority"]["max_total_calls"] = 1
            authorization["authority"]["max_total_billed_tokens"] = 100
            reserve_provider_call(
                run_dir,
                authorization,
                "a" * 64,
                adapter_kind="subject",
                plan_sha256=authorization["run"]["plan_sha256"],
                request_sha256="b" * 64,
            )
            with self.assertRaisesRegex(PipelineError, "call budget"):
                reserve_provider_call(
                    run_dir,
                    authorization,
                    "a" * 64,
                    adapter_kind="subject",
                    plan_sha256=authorization["run"]["plan_sha256"],
                    request_sha256="c" * 64,
                )
            verify_billed_token_telemetry(
                {"telemetry": {"input_tokens": 40, "output_tokens": 60}}, authorization
            )
            with self.assertRaisesRegex(PipelineError, "per-call"):
                verify_billed_token_telemetry(
                    {"telemetry": {"input_tokens": 60, "output_tokens": 60}}, authorization
                )

    def test_provider_budget_lock_rejects_hardlink_without_touching_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            config = self._governance_config(run_dir)
            authorization, _ = self._authorization(config)
            execution_dir = run_dir / "execution"
            execution_dir.mkdir(mode=0o700)
            victim = run_dir / "victim.txt"
            victim.write_text("preserve me\n", encoding="utf-8")
            os.link(victim, execution_dir / ".budget.lock")
            with self.assertRaisesRegex(PipelineError, "private regular file"):
                reserve_provider_call(
                    run_dir,
                    authorization,
                    "a" * 64,
                    adapter_kind="subject",
                    plan_sha256=authorization["run"]["plan_sha256"],
                    request_sha256="b" * 64,
                )
            self.assertEqual(victim.read_text(encoding="utf-8"), "preserve me\n")

    def test_authorized_adapter_call_binds_request_reservation_and_token_telemetry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = self._governance_config(root)
            authorization, _ = self._authorization(config)
            adapter = root / "adapter.py"
            adapter.write_text(
                "import hashlib,json,sys\n"
                "b=open(sys.argv[1],'rb').read();r=json.loads(b)\n"
                "o={'schema_version':'1.0','request_id':r['request_id'],"
                "'request_sha256':hashlib.sha256(b).hexdigest(),'status':'completed',"
                "'output':{'text':'ok'},'telemetry':{'input_tokens':1,'output_tokens':1}}\n"
                "json.dump(o,open(sys.argv[2],'w'))\n",
                encoding="utf-8",
            )
            authority_sha256 = "a" * 64
            request = {
                "schema_version": "1.0",
                "adapter_kind": "subject",
                "plan_sha256": authorization["run"]["plan_sha256"],
                "execution_authority": {
                    "authorization_sha256": authority_sha256,
                    "max_billed_tokens": authorization["authority"]["max_billed_tokens_per_call"],
                },
            }
            result = invoke_adapter(
                [sys.executable, str(adapter), "{input}", "{output}"],
                request,
                root / "attempts",
                timeout_seconds=5,
                max_transient_retries=0,
                execution_authorization=authorization,
                execution_authorization_sha256=authority_sha256,
                execution_run_dir=root,
            )
            self.assertEqual(result["status"], "completed")
            reservation_paths = list((root / "execution/call-reservations").glob("*.json"))
            self.assertEqual(len(reservation_paths), 1)
            request_path = Path(result["attempts"][0]["request_path"])
            self.assertIn(authority_sha256, request_path.read_text(encoding="utf-8"))

    def _install_config(self, root: Path) -> dict:
        config = self._governance_config(root)
        config.update(
            {
                "candidate": {"skill_path": "skills/explore-approaches"},
                "installation": {
                    "source_mode": "local-test",
                    "skills_root": str(root / "skills-root"),
                    "skill_name": "explore-approaches",
                    "backup_directory": str(root / "skills-root/backups"),
                    "quarantine_directory": str(root / "skills-root/quarantine"),
                    "validator_env_allowlist": ["PATH"],
                },
            }
        )
        return config

    def test_installation_lock_rejects_hardlink_without_touching_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skills_root = root / "skills"
            skills_root.mkdir(mode=0o700)
            victim = root / "victim.txt"
            victim.write_text("preserve me\n", encoding="utf-8")
            victim.chmod(0o640)
            os.link(victim, skills_root / ".candidate.install.lock")
            with self.assertRaisesRegex(PipelineError, "private regular file"):
                with installation_lock(skills_root, "candidate"):
                    self.fail("a hard-linked installation lock was accepted")
            self.assertEqual(victim.read_text(encoding="utf-8"), "preserve me\n")
            self.assertEqual(victim.stat().st_mode & 0o777, 0o640)

    def _completed_install(self, root: Path, config: dict, run_dir: Path) -> Path:
        destination = Path(config["installation"]["skills_root"]) / "explore-approaches"
        destination.mkdir(parents=True)
        (destination / "SKILL.md").write_text("previous\n", encoding="utf-8")
        checkout = root / "checkout"
        candidate = checkout / "skills/explore-approaches"
        candidate.mkdir(parents=True)
        (candidate / "SKILL.md").write_text("candidate\n", encoding="utf-8")
        atomic_install(
            checkout,
            "a" * 40,
            run_dir,
            config,
            canary=lambda *_: {"status": "completed", "output": {"passed": True}},
        )
        return destination

    def test_active_rollback_quarantines_candidate_restores_predecessor_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = self._install_config(root)
            run_dir = root / "run"
            destination = self._completed_install(root, config, run_dir)
            record = rollback_active_install(
                run_dir,
                config,
                operator="promotion-owner",
                reason="operator observed a post-activation regression",
                rollback_canary=lambda skill, hashes, *_: {
                    "status": "passed",
                    "file_hashes": hashes,
                    "observed": sha256_file(skill / "SKILL.md"),
                },
            )
            self.assertEqual((destination / "SKILL.md").read_text(encoding="utf-8"), "previous\n")
            self.assertEqual(record["status"], "rolled-back")
            self.assertEqual(Path(record["quarantine"]).joinpath("SKILL.md").read_text(), "candidate\n")
            resumed = rollback_active_install(
                run_dir,
                config,
                operator="promotion-owner",
                reason="operator observed a post-activation regression",
                rollback_canary=lambda *_: self.fail("completed rollback reran its canary"),
            )
            self.assertEqual(resumed["record_sha256"], record["record_sha256"])

    def test_active_rollback_recovers_after_crash_between_quarantine_and_restore(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = self._install_config(root)
            run_dir = root / "run"
            destination = self._completed_install(root, config, run_dir)

            def crash(stage: str) -> None:
                if stage == "candidate-quarantined":
                    raise RuntimeError("simulated process loss")

            with self.assertRaisesRegex(RuntimeError, "simulated process loss"):
                rollback_active_install(
                    run_dir,
                    config,
                    operator="promotion-owner",
                    reason="operator requested deterministic crash recovery",
                    rollback_canary=lambda *_: {"status": "passed"},
                    fault_injector=crash,
                )
            self.assertFalse(destination.exists())
            record = rollback_active_install(
                run_dir,
                config,
                operator="promotion-owner",
                reason="operator requested deterministic crash recovery",
                rollback_canary=lambda *_: {"status": "passed"},
            )
            self.assertEqual(record["status"], "rolled-back")
            self.assertEqual((destination / "SKILL.md").read_text(encoding="utf-8"), "previous\n")

    def test_active_rollback_recovers_after_crash_after_predecessor_restore(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = self._install_config(root)
            run_dir = root / "run"
            destination = self._completed_install(root, config, run_dir)

            def crash(stage: str) -> None:
                if stage == "previous-restored":
                    raise RuntimeError("simulated process loss after predecessor restore")

            with self.assertRaisesRegex(RuntimeError, "after predecessor restore"):
                rollback_active_install(
                    run_dir,
                    config,
                    operator="promotion-owner",
                    reason="operator requested post-restore crash recovery",
                    rollback_canary=lambda *_: {"status": "passed"},
                    fault_injector=crash,
                )
            self.assertEqual((destination / "SKILL.md").read_text(encoding="utf-8"), "previous\n")
            record = rollback_active_install(
                run_dir,
                config,
                operator="promotion-owner",
                reason="operator requested post-restore crash recovery",
                rollback_canary=lambda *_: {"status": "passed"},
            )
            self.assertEqual(record["status"], "rolled-back")
            self.assertEqual((destination / "SKILL.md").read_text(encoding="utf-8"), "previous\n")

    def test_validator_runs_with_an_explicit_environment_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = root / "skill"
            skill.mkdir()
            (skill / "SKILL.md").write_text(
                "---\nname: explore-approaches\ndescription: test\n---\n",
                encoding="utf-8",
            )
            config = {
                "installation": {"validator_env_allowlist": ["PATH"]},
                "evaluation": {"timeout_ms": 1000, "adapter_env_allowlist": ["PATH"]},
            }
            completed = subprocess.CompletedProcess(["validator"], 0, "", "")
            with (
                mock.patch(
                    "automation.promotion.verify_lifecycle_executable_binding",
                    side_effect=[{"argv": ["validator", "{skill}"]}, {"argv": ["canary"]}],
                ),
                mock.patch("automation.promotion.run_command", return_value=completed) as command,
                mock.patch(
                    "automation.promotion.invoke_adapter",
                    return_value={"status": "completed", "response": {"output": {"passed": True}}},
                ),
            ):
                run_canary(
                    skill,
                    root / "run",
                    config,
                    execution_authorization={
                        "run": {"plan_sha256": "a" * 64},
                        "authority": {"max_billed_tokens_per_call": 10},
                    },
                    execution_authorization_sha256="b" * 64,
                )
            self.assertFalse(command.call_args.kwargs["inherit_env"])
            self.assertEqual(set(command.call_args.kwargs["env"]), {"PATH"} if "PATH" in __import__("os").environ else set())

    def test_installer_runs_with_an_explicit_environment_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            (source / "SKILL.md").write_text("candidate\n", encoding="utf-8")
            skills_root = root / "skills-root"
            skills_root.mkdir()
            staging = skills_root / ".candidate-staging"
            installer_root = skills_root / ".candidate-installer"
            run_dir = root / "run"
            run_dir.mkdir()
            expected_hashes = {"SKILL.md": sha256_file(source / "SKILL.md")}
            config = {
                "candidate": {"skill_path": "skills/explore-approaches"},
                "promotion": {"repository_slug": "owner/repository"},
                "installation": {
                    "source_mode": "installer",
                    "skill_name": "explore-approaches",
                    "installer_env_allowlist": ["PATH"],
                },
            }

            def install(_command, **_kwargs):
                downloaded = installer_root / "explore-approaches"
                downloaded.mkdir(parents=True)
                (downloaded / "SKILL.md").write_text("candidate\n", encoding="utf-8")
                return subprocess.CompletedProcess(_command, 0, "", "")

            with (
                mock.patch(
                    "automation.promotion.verify_lifecycle_executable_binding",
                    return_value={"argv": ["python", "installer.py"]},
                ),
                mock.patch("automation.promotion.run_command", side_effect=install) as command,
            ):
                _stage_install_source(
                    source,
                    staging,
                    installer_root,
                    "a" * 40,
                    expected_hashes,
                    run_dir,
                    config,
                )
            self.assertFalse(command.call_args.kwargs["inherit_env"])
            self.assertEqual(set(command.call_args.kwargs["env"]), {"PATH"} if "PATH" in __import__("os").environ else set())
            self.assertEqual((staging / "SKILL.md").read_text(encoding="utf-8"), "candidate\n")


if __name__ == "__main__":
    unittest.main()
