from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from automation.core import PipelineError, atomic_write_json, sha256_file, sha256_json
from automation.promotion import (
    approval_payload,
    atomic_install,
    build_pr_record,
    build_release_record,
    installation_lock,
    materialize_change,
    merge_reviewed_pr,
    prepare_clean_promotion,
    rehearse_rollback,
    seal_record,
    validate_approval,
    validate_installation_receipt,
    validate_prepared_promotion,
    verify_merged_candidate,
    verify_promoted_manifest,
    verify_ssh_signature,
    write_immutable_record,
)


class PromotionAutomationTest(unittest.TestCase):

    def test_recovered_prepared_promotion_rederives_exact_git_diff(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repository"
            repository.mkdir()
            subprocess.run(["git", "init", "-b", "main"], cwd=repository, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repository, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repository, check=True)
            base_skill = repository / "skills/explore-approaches/SKILL.md"
            base_skill.parent.mkdir(parents=True)
            base_skill.write_text("old\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repository, check=True)
            subprocess.run(["git", "commit", "-m", "base"], cwd=repository, check=True, capture_output=True)
            base_commit = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=repository, check=True, capture_output=True, text=True
            ).stdout.strip()

            source = root / "source"
            approved = source / "skills/explore-approaches/SKILL.md"
            approved.parent.mkdir(parents=True)
            approved.write_text("approved\n", encoding="utf-8")
            body = {
                "schema_version": "1.0",
                "files": [{"path": "skills/explore-approaches/SKILL.md", "sha256": sha256_file(approved), "size": approved.stat().st_size}],
                "csv_records": [],
                "markdown_records": [],
            }
            manifest = {**body, "manifest_sha256": sha256_json(body)}
            config = {
                "promotion": {
                    "repository_url": str(repository),
                    "repository_slug": "owner/repository",
                    "remote": "origin",
                    "base_branch": "main",
                    "feature_branch": "codex/test-recovery",
                    "commit_message": "candidate",
                }
            }
            prepared = prepare_clean_promotion(
                source,
                root / "run/promotion-work",
                config,
                manifest,
                expected_base_commit=base_commit,
                approval_sha256="a" * 64,
                config_sha256=sha256_json(config),
            )
            sealed = seal_record(prepared)
            validate_prepared_promotion(sealed, root / "run", config, manifest, approval_sha256="a" * 64)

            clone = Path(prepared["clone"])
            (clone / "UNAPPROVED.md").write_text("hidden\n", encoding="utf-8")
            subprocess.run(["git", "add", "UNAPPROVED.md"], cwd=clone, check=True)
            subprocess.run(["git", "commit", "--amend", "--no-edit"], cwd=clone, check=True, capture_output=True)
            forged = {
                **prepared,
                "head_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=clone, check=True, capture_output=True, text=True).stdout.strip(),
                "head_tree": subprocess.run(["git", "rev-parse", "HEAD^{tree}"], cwd=clone, check=True, capture_output=True, text=True).stdout.strip(),
                "staged_paths": ["UNAPPROVED.md", "skills/explore-approaches/SKILL.md"],
            }
            with self.assertRaisesRegex(PipelineError, "outside the approved manifest"):
                validate_prepared_promotion(seal_record(forged), root / "run", config, manifest, approval_sha256="a" * 64)

    def test_recovered_prepared_promotion_rejects_intrafile_ledger_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repository"
            repository.mkdir()
            subprocess.run(["git", "init", "-b", "main"], cwd=repository, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repository, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repository, check=True)
            base_skill = repository / "skills/explore-approaches/SKILL.md"
            base_skill.parent.mkdir(parents=True)
            base_skill.write_text("old\n", encoding="utf-8")
            ledger = repository / "research/ledgers/claims.csv"
            ledger.parent.mkdir(parents=True)
            ledger.write_text(
                "id,value\nC-approved,old\nC-unrelated,keep\n", encoding="utf-8"
            )
            subprocess.run(["git", "add", "."], cwd=repository, check=True)
            subprocess.run(["git", "commit", "-m", "base"], cwd=repository, check=True, capture_output=True)
            base_commit = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=repository, check=True, capture_output=True, text=True
            ).stdout.strip()

            source = root / "source"
            approved = source / "skills/explore-approaches/SKILL.md"
            approved.parent.mkdir(parents=True)
            approved.write_text("approved\n", encoding="utf-8")
            body = {
                "schema_version": "1.0",
                "files": [
                    {
                        "path": "skills/explore-approaches/SKILL.md",
                        "sha256": sha256_file(approved),
                        "size": approved.stat().st_size,
                    }
                ],
                "csv_records": [
                    {
                        "path": "research/ledgers/claims.csv",
                        "record_id": "C-approved",
                        "line": "C-approved,new",
                        "values": ["C-approved", "new"],
                    }
                ],
                "markdown_records": [],
            }
            manifest = {**body, "manifest_sha256": sha256_json(body)}
            config = {
                "promotion": {
                    "repository_url": str(repository),
                    "repository_slug": "owner/repository",
                    "remote": "origin",
                    "base_branch": "main",
                    "feature_branch": "codex/test-ledger-recovery",
                    "commit_message": "candidate",
                }
            }
            prepared = prepare_clean_promotion(
                source,
                root / "run/promotion-work",
                config,
                manifest,
                expected_base_commit=base_commit,
                approval_sha256="a" * 64,
                config_sha256=sha256_json(config),
            )
            clone = Path(prepared["clone"])
            clone_ledger = clone / "research/ledgers/claims.csv"
            clone_ledger.write_text(
                "id,value\nC-approved,new\nC-unrelated,TAMPERED\n", encoding="utf-8"
            )
            subprocess.run(["git", "add", "research/ledgers/claims.csv"], cwd=clone, check=True)
            subprocess.run(["git", "commit", "--amend", "--no-edit"], cwd=clone, check=True, capture_output=True)
            forged = seal_record(
                {
                    **prepared,
                    "head_commit": subprocess.run(
                        ["git", "rev-parse", "HEAD"], cwd=clone, check=True, capture_output=True, text=True
                    ).stdout.strip(),
                    "head_tree": subprocess.run(
                        ["git", "rev-parse", "HEAD^{tree}"], cwd=clone, check=True, capture_output=True, text=True
                    ).stdout.strip(),
                    "staged_paths": [
                        "research/ledgers/claims.csv",
                        "skills/explore-approaches/SKILL.md",
                    ],
                }
            )
            with self.assertRaisesRegex(PipelineError, "canonical approved materialization"):
                validate_prepared_promotion(
                    forged,
                    root / "run",
                    config,
                    manifest,
                    approval_sha256="a" * 64,
                )

    def test_full_promoted_manifest_verifies_governed_ledger_records(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill = root / "skills/explore-approaches/SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("approved\n", encoding="utf-8")
            ledger = root / "research/ledgers/claims.csv"
            ledger.parent.mkdir(parents=True)
            ledger.write_text("id,value\nC-1,approved\n", encoding="utf-8")
            taxonomy = root / "research/TECHNIQUE_TAXONOMY.md"
            taxonomy.write_text("| id | value |\n| T-1 | approved |\n", encoding="utf-8")
            body = {
                "schema_version": "1.0",
                "files": [{"path": "skills/explore-approaches/SKILL.md", "sha256": sha256_file(skill), "size": skill.stat().st_size}],
                "csv_records": [{"path": "research/ledgers/claims.csv", "record_id": "C-1", "line": "C-1,approved", "values": ["C-1", "approved"]}],
                "markdown_records": [{"path": "research/TECHNIQUE_TAXONOMY.md", "record_id": "T-1", "line": "| T-1 | approved |"}],
            }
            manifest = {**body, "manifest_sha256": sha256_json(body)}
            verify_promoted_manifest(root, manifest)
            ledger.write_text("id,value\nC-1,tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(PipelineError, "CSV record differs"):
                verify_promoted_manifest(root, manifest)

    def test_production_install_uses_exact_ref_skill_installer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "checkout/skills/explore-approaches"
            source.mkdir(parents=True)
            (source / "SKILL.md").write_text("approved\n", encoding="utf-8")
            helper = root / "install-skill-from-github.py"
            helper.write_text("# test helper\n", encoding="utf-8")
            config = {
                "candidate": {"skill_path": "skills/explore-approaches"},
                "promotion": {"repository_slug": "owner/repository"},
                "installation": {
                    "source_mode": "installer",
                    "installer_script": str(helper),
                    "skills_root": str(root / "root-skills"),
                    "skill_name": "explore-approaches",
                    "backup_directory": str(root / "backups"),
                    "quarantine_directory": str(root / "quarantine"),
                },
            }
            observed: list[str] = []

            def install(command: list[str], **_kwargs):
                observed.extend(command)
                destination = Path(command[command.index("--dest") + 1]) / "explore-approaches"
                destination.mkdir(parents=True)
                shutil.copyfile(source / "SKILL.md", destination / "SKILL.md")
                return subprocess.CompletedProcess(command, 0, "", "")

            with patch("automation.promotion.run_command", side_effect=install):
                receipt = atomic_install(
                    root / "checkout",
                    "f" * 40,
                    root / "run",
                    config,
                    canary=lambda *_: {"status": "completed", "output": {"passed": True}},
                )
            self.assertEqual(receipt["status"], "installed")
            self.assertEqual(observed[observed.index("--repo") + 1], "owner/repository")
            self.assertEqual(observed[observed.index("--path") + 1], "skills/explore-approaches")
            self.assertEqual(observed[observed.index("--ref") + 1], "f" * 40)

            config["installation"]["installer_script"] = str(root / "missing-helper.py")
            with self.assertRaisesRegex(PipelineError, "helper is missing"):
                atomic_install(root / "checkout", "e" * 40, root / "missing-run", config, canary=lambda *_: {})
    @unittest.skipUnless(shutil.which("ssh-keygen"), "ssh-keygen is required")
    def test_detached_ssh_signature_is_verified_and_tamper_evident(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            key = root / "approval-key"
            subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
            public_parts = (key.with_suffix(".pub")).read_text(encoding="utf-8").split()
            allowed = root / "allowed_signers"
            allowed.write_text(f"named-human {public_parts[0]} {public_parts[1]}\n", encoding="utf-8")
            approval = {
                "schema_version": "2.0",
                "approval_id": "SIGNED-1",
                "decision": "promote",
                "approved_by": "Named Human",
                "signature": {
                    "algorithm": "ssh-keygen-y",
                    "identity": "named-human",
                    "namespace": "codex-skill-promotion",
                    "value": "placeholder",
                },
            }
            payload = root / "approval-payload.json"
            payload.write_bytes(approval_payload(approval))
            subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(key), "-n", "codex-skill-promotion", str(payload)], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            approval["signature"]["value"] = base64.b64encode((root / "approval-payload.json.sig").read_bytes()).decode("ascii")
            config = {"approval_verification": {"allowed_signers_path": str(allowed), "expected_identity": "named-human", "namespace": "codex-skill-promotion"}}
            verify_ssh_signature(approval, config)
            approval["approved_by"] = "Tampered"
            with self.assertRaises(PipelineError):
                verify_ssh_signature(approval, config)

    def test_materialize_only_allowlisted_files_and_records(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            clean = root / "clean"
            (source / "skills/explore-approaches").mkdir(parents=True)
            (clean / "research/ledgers").mkdir(parents=True)
            (clean / "research").mkdir(exist_ok=True)
            skill = source / "skills/explore-approaches/SKILL.md"
            skill.write_text("candidate\n", encoding="utf-8")
            (clean / "research/ledgers/claims.csv").write_text("id,value\nC-001,old\nC-999,keep\n", encoding="utf-8")
            (clean / "research/TECHNIQUE_TAXONOMY.md").write_text("| ID | Value |\n| --- | --- |\n| T-001 | old |\n", encoding="utf-8")
            body = {
                "schema_version": "1.0",
                "pipeline_id": "test",
                "candidate_name": "explore-approaches",
                "candidate_version": "explore-approaches-v0.1.0",
                "files": [{"path": "skills/explore-approaches/SKILL.md", "size": skill.stat().st_size, "sha256": sha256_file(skill)}],
                "csv_records": [{"path": "research/ledgers/claims.csv", "record_id": "C-001", "values": ["C-001", "new"]}],
                "markdown_records": [{"path": "research/TECHNIQUE_TAXONOMY.md", "record_id": "T-001", "line": "| T-001 | new |"}],
            }
            manifest = {**body, "manifest_sha256": sha256_json(body)}
            changed = materialize_change(source, clean, manifest)
            self.assertEqual(len(changed), 3)
            self.assertIn("C-999,keep", (clean / "research/ledgers/claims.csv").read_text())
            self.assertIn("C-001,new", (clean / "research/ledgers/claims.csv").read_text())
            self.assertIn("| T-001 | new |", (clean / "research/TECHNIQUE_TAXONOMY.md").read_text())

    def test_manifest_rejects_path_traversal_and_symlink_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            clean = root / "clean"
            source.mkdir()
            clean.mkdir()
            traversal_body = {
                "schema_version": "1.0",
                "pipeline_id": "test",
                "candidate_name": "explore-approaches",
                "candidate_version": "explore-approaches-v0.1.0",
                "files": [{"path": "../escape", "size": 1, "sha256": "a" * 64}],
                "csv_records": [],
                "markdown_records": [],
            }
            with self.assertRaises(PipelineError):
                materialize_change(source, clean, {**traversal_body, "manifest_sha256": sha256_json(traversal_body)})

            target = root / "secret"
            target.write_text("secret", encoding="utf-8")
            link = source / "SKILL.md"
            link.symlink_to(target)
            symlink_body = {**traversal_body, "files": [{"path": "SKILL.md", "size": target.stat().st_size, "sha256": sha256_file(target)}]}
            with self.assertRaises(PipelineError):
                materialize_change(source, clean, {**symlink_body, "manifest_sha256": sha256_json(symlink_body)})

    def test_manifest_rejects_symlink_destination_ancestor(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            clean = root / "clean"
            escape = root / "escape"
            skill = source / "skills/explore-approaches/SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("candidate\n", encoding="utf-8")
            clean.mkdir()
            escape.mkdir()
            (clean / "skills").symlink_to(escape, target_is_directory=True)
            body = {
                "schema_version": "1.0",
                "pipeline_id": "test",
                "candidate_name": "explore-approaches",
                "candidate_version": "explore-approaches-v0.1.0",
                "files": [{"path": "skills/explore-approaches/SKILL.md", "size": skill.stat().st_size, "sha256": sha256_file(skill)}],
                "csv_records": [],
                "markdown_records": [],
            }
            with self.assertRaises(PipelineError):
                materialize_change(source, clean, {**body, "manifest_sha256": sha256_json(body)})
            self.assertFalse((escape / "explore-approaches/SKILL.md").exists())

    def test_merged_candidate_must_exactly_match_manifest_subtree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            checkout = Path(temporary)
            skill = checkout / "skills/explore-approaches/SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("candidate\n", encoding="utf-8")
            body = {
                "schema_version": "1.0",
                "pipeline_id": "test",
                "candidate_name": "explore-approaches",
                "candidate_version": "explore-approaches-v0.1.0",
                "files": [{"path": "skills/explore-approaches/SKILL.md", "size": skill.stat().st_size, "sha256": sha256_file(skill)}],
                "csv_records": [],
                "markdown_records": [],
            }
            manifest = {**body, "manifest_sha256": sha256_json(body)}
            self.assertEqual(verify_merged_candidate(checkout, manifest, "skills/explore-approaches"), {"SKILL.md": sha256_file(skill)})
            (skill.parent / "unexpected.txt").write_text("extra\n", encoding="utf-8")
            with self.assertRaises(PipelineError):
                verify_merged_candidate(checkout, manifest, "skills/explore-approaches")

    def test_atomic_install_pass_and_automatic_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkout = root / "checkout/skills/explore-approaches"
            checkout.mkdir(parents=True)
            (checkout / "SKILL.md").write_text("candidate\n", encoding="utf-8")
            skills_root = root / "root-skills"
            old = skills_root / "explore-approaches"
            old.mkdir(parents=True)
            (old / "SKILL.md").write_text("previous\n", encoding="utf-8")
            config = {
                "candidate": {"skill_path": "skills/explore-approaches"},
                "installation": {
                    "source_mode": "local-test",
                    "skills_root": str(skills_root),
                    "skill_name": "explore-approaches",
                    "backup_directory": str(root / "backups"),
                    "quarantine_directory": str(root / "quarantine"),
                },
            }
            receipt = atomic_install(root / "checkout", "a" * 40, root / "run-pass", config, canary=lambda *_: {"status": "completed", "output": {"passed": True}})
            self.assertEqual(receipt["status"], "installed")
            self.assertEqual((old / "SKILL.md").read_text(), "candidate\n")

            (checkout / "SKILL.md").write_text("bad-candidate\n", encoding="utf-8")
            with self.assertRaises(PipelineError):
                atomic_install(root / "checkout", "b" * 40, root / "run-fail", config, canary=lambda *_: (_ for _ in ()).throw(PipelineError("fail")))
            self.assertEqual((old / "SKILL.md").read_text(), "candidate\n")
            self.assertTrue((root / "run-fail/rollback-record.json").is_file())

    def test_canary_mutation_without_previous_install_is_quarantined(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkout = root / "checkout/skills/explore-approaches"
            checkout.mkdir(parents=True)
            (checkout / "SKILL.md").write_text("candidate\n", encoding="utf-8")
            destination = root / "root-skills/explore-approaches"
            config = {
                "candidate": {"skill_path": "skills/explore-approaches"},
                "installation": {
                    "source_mode": "local-test",
                    "skills_root": str(root / "root-skills"),
                    "skill_name": "explore-approaches",
                    "backup_directory": str(root / "backups"),
                    "quarantine_directory": str(root / "quarantine"),
                },
            }

            def mutate_then_fail(installed: Path, *_args) -> dict:
                (installed / "SKILL.md").write_text("mutated\n", encoding="utf-8")
                raise PipelineError("deliberate canary mutation")

            run_dir = root / "run"
            with self.assertRaisesRegex(PipelineError, "installation rolled back"):
                atomic_install(root / "checkout", "d" * 40, run_dir, config, canary=mutate_then_fail)
            rollback = json.loads((run_dir / "rollback-record.json").read_text(encoding="utf-8"))
            intent = json.loads((run_dir / "install-intent.json").read_text(encoding="utf-8"))
            quarantine = Path(rollback["quarantine"])
            self.assertFalse(destination.exists())
            self.assertEqual((quarantine / "SKILL.md").read_text(encoding="utf-8"), "mutated\n")
            self.assertFalse(rollback["restored_previous"])
            self.assertEqual(rollback["status"], "rolled-back")
            self.assertEqual(intent["phase"], "rolled-back")

    def test_canary_mutation_restores_previous_install_after_quarantine(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkout = root / "checkout/skills/explore-approaches"
            checkout.mkdir(parents=True)
            (checkout / "SKILL.md").write_text("candidate\n", encoding="utf-8")
            destination = root / "root-skills/explore-approaches"
            destination.mkdir(parents=True)
            (destination / "SKILL.md").write_text("previous\n", encoding="utf-8")
            config = {
                "candidate": {"skill_path": "skills/explore-approaches"},
                "installation": {
                    "source_mode": "local-test",
                    "skills_root": str(root / "root-skills"),
                    "skill_name": "explore-approaches",
                    "backup_directory": str(root / "backups"),
                    "quarantine_directory": str(root / "quarantine"),
                },
            }

            def mutate_then_fail(installed: Path, *_args) -> dict:
                (installed / "SKILL.md").write_text("mutated\n", encoding="utf-8")
                raise PipelineError("deliberate canary mutation")

            run_dir = root / "run"
            with self.assertRaisesRegex(PipelineError, "installation rolled back"):
                atomic_install(root / "checkout", "e" * 40, run_dir, config, canary=mutate_then_fail)
            rollback = json.loads((run_dir / "rollback-record.json").read_text(encoding="utf-8"))
            intent = json.loads((run_dir / "install-intent.json").read_text(encoding="utf-8"))
            quarantine = Path(rollback["quarantine"])
            self.assertEqual((destination / "SKILL.md").read_text(encoding="utf-8"), "previous\n")
            self.assertEqual((quarantine / "SKILL.md").read_text(encoding="utf-8"), "mutated\n")
            self.assertTrue(rollback["restored_previous"])
            self.assertEqual(rollback["status"], "rolled-back")
            self.assertEqual(intent["phase"], "rolled-back")
            self.assertFalse(Path(intent["backup"]).exists())

    def test_atomic_install_recovers_after_backup_move_and_reruns_canary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkout = root / "checkout/skills/explore-approaches"
            checkout.mkdir(parents=True)
            (checkout / "SKILL.md").write_text("candidate\n", encoding="utf-8")
            destination = root / "root-skills/explore-approaches"
            destination.mkdir(parents=True)
            (destination / "SKILL.md").write_text("previous\n", encoding="utf-8")
            backup_root = root / "backups"
            config = {
                "candidate": {"skill_path": "skills/explore-approaches"},
                "installation": {
                    "source_mode": "local-test",
                    "skills_root": str(root / "root-skills"),
                    "skill_name": "explore-approaches",
                    "backup_directory": str(backup_root),
                    "quarantine_directory": str(root / "quarantine"),
                },
            }
            real_replace = os.replace

            def crash_after_backup(source: str | Path, target: str | Path) -> None:
                real_replace(source, target)
                if Path(source) == destination and Path(target).parent == backup_root:
                    raise SystemExit("simulated crash after backup rename")

            with patch("automation.promotion.os.replace", side_effect=crash_after_backup):
                with self.assertRaises(SystemExit):
                    atomic_install(root / "checkout", "c" * 40, root / "run", config, canary=lambda *_: {"passed": True})

            canary_calls: list[str] = []
            receipt = atomic_install(
                root / "checkout",
                "c" * 40,
                root / "run",
                config,
                canary=lambda *_: canary_calls.append("fresh") or {"status": "completed", "output": {"passed": True}},
            )
            self.assertEqual(canary_calls, ["fresh"])
            self.assertEqual(receipt["status"], "installed")
            self.assertEqual((destination / "SKILL.md").read_text(encoding="utf-8"), "candidate\n")

    def test_atomic_install_completes_interrupted_rollback_without_reactivation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkout = root / "checkout/skills/explore-approaches"
            checkout.mkdir(parents=True)
            (checkout / "SKILL.md").write_text("candidate\n", encoding="utf-8")
            destination = root / "root-skills/explore-approaches"
            destination.mkdir(parents=True)
            (destination / "SKILL.md").write_text("previous\n", encoding="utf-8")
            backup_root = root / "backups"
            config = {
                "candidate": {"skill_path": "skills/explore-approaches"},
                "installation": {
                    "source_mode": "local-test",
                    "skills_root": str(root / "root-skills"),
                    "skill_name": "explore-approaches",
                    "backup_directory": str(backup_root),
                    "quarantine_directory": str(root / "quarantine"),
                },
            }
            real_replace = os.replace

            def crash_after_restore(source: str | Path, target: str | Path) -> None:
                real_replace(source, target)
                if Path(source).parent == backup_root and Path(target) == destination:
                    raise SystemExit("simulated crash after rollback restore")

            with patch("automation.promotion.os.replace", side_effect=crash_after_restore):
                with self.assertRaises(SystemExit):
                    atomic_install(
                        root / "checkout",
                        "9" * 40,
                        root / "run",
                        config,
                        canary=lambda *_: (_ for _ in ()).throw(PipelineError("canary failed")),
                    )
            canary_calls: list[str] = []
            with self.assertRaises(PipelineError):
                atomic_install(
                    root / "checkout",
                    "9" * 40,
                    root / "run",
                    config,
                    canary=lambda *_: canary_calls.append("must-not-run") or {},
                )
            self.assertEqual(canary_calls, [])
            self.assertEqual((destination / "SKILL.md").read_text(encoding="utf-8"), "previous\n")
            self.assertTrue((root / "run/rollback-record.json").is_file())

    def test_installation_receipt_is_revalidated_and_lock_is_exclusive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkout = root / "checkout/skills/explore-approaches"
            checkout.mkdir(parents=True)
            (checkout / "SKILL.md").write_text("candidate\n", encoding="utf-8")
            skills_root = root / "root-skills"
            skills_root.mkdir()
            config = {
                "candidate": {"skill_path": "skills/explore-approaches"},
                "installation": {
                    "source_mode": "local-test",
                    "skills_root": str(skills_root),
                    "skill_name": "explore-approaches",
                    "backup_directory": str(root / "backups"),
                    "quarantine_directory": str(root / "quarantine"),
                },
            }
            run_dir = root / "run"
            run_dir.mkdir()
            atomic_write_json(run_dir / "installation-record.json", {"status": "installed", "merge_commit": "d" * 40})
            with self.assertRaises(PipelineError):
                validate_installation_receipt(
                    run_dir,
                    expected_merge_commit="d" * 40,
                    expected_destination=skills_root / "explore-approaches",
                )
            canary_calls: list[str] = []
            atomic_install(
                root / "checkout",
                "d" * 40,
                run_dir,
                config,
                canary=lambda *_: canary_calls.append("first") or {"status": "completed", "output": {"passed": True}},
            )
            atomic_install(
                root / "checkout",
                "d" * 40,
                run_dir,
                config,
                canary=lambda *_: canary_calls.append("retry") or {"status": "completed", "output": {"passed": True}},
            )
            self.assertEqual(canary_calls, ["first", "retry"])
            (skills_root / "explore-approaches/SKILL.md").write_text("tampered\n", encoding="utf-8")
            with self.assertRaises(PipelineError):
                validate_installation_receipt(
                    run_dir,
                    expected_merge_commit="d" * 40,
                    expected_destination=skills_root / "explore-approaches",
                )
            with installation_lock(skills_root, "explore-approaches"):
                with self.assertRaises(PipelineError):
                    atomic_install(root / "checkout", "e" * 40, root / "other-run", config, canary=lambda *_: {})

    def test_post_result_approval_is_hash_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            summary_path = root / "evaluation-summary.json"
            holdout_path = root / "holdout-manifest.json"
            rollback_path = root / "rollback-evidence.json"
            plan_path = root / "plan.json"
            evidence_manifest_path = root / "evidence-manifest.json"
            atomic_write_json(evidence_manifest_path, {"schema_version": "1.0", "manifest_sha256": "f" * 64})
            atomic_write_json(
                summary_path,
                {
                    "completed_at": "2026-07-29T12:00:00Z",
                    "evidence": {"evidence_manifest_sha256": sha256_file(evidence_manifest_path)},
                },
            )
            atomic_write_json(holdout_path, {"private": True})
            atomic_write_json(rollback_path, {"result": "passed"})
            body = {"schema_version": "1.0", "files": [], "csv_records": [], "markdown_records": []}
            manifest = {**body, "manifest_sha256": sha256_json(body)}
            config = {
                "candidate": {"name": "explore-approaches", "version": "explore-approaches-v0.1.0"},
                "approval_verification": {"namespace": "codex-skill-promotion"},
                "promotion": {
                    "repository_url": "https://github.com/tedahn/dynamic-prompt-engineering.git",
                    "repository_slug": "tedahn/dynamic-prompt-engineering",
                    "base_branch": "main",
                    "feature_branch": "codex/explore-approaches-v0.1.0",
                },
                "installation": {"skills_root": "~/.codex/skills", "skill_name": "explore-approaches"},
            }
            plan_body = {
                "base_commit": "a" * 40,
                "protocol_sha256": "b" * 64,
                "rubric_sha256": "c" * 64,
                "config_sha256": sha256_json(config),
                "candidate_manifest_sha256": manifest["manifest_sha256"],
            }
            atomic_write_json(plan_path, {**plan_body, "plan_sha256": sha256_json(plan_body)})
            approval = {
                "schema_version": "2.0",
                "approval_id": "A-1",
                "decision": "promote",
                "approved_by": "Named Human",
                "approved_at": "2026-07-30T12:00:00Z",
                "expires_at": "2099-01-01T00:00:00Z",
                "evaluation_completed_at": "2026-07-29T12:00:00Z",
                "candidate": {"name": "explore-approaches", "version": "explore-approaches-v0.1.0", "manifest_sha256": manifest["manifest_sha256"], "base_commit": "a" * 40},
                "evidence": {
                    "evaluation_summary_sha256": sha256_file(summary_path),
                    "evidence_manifest_sha256": sha256_file(evidence_manifest_path),
                    "holdout_manifest_sha256": sha256_file(holdout_path),
                    "protocol_sha256": "b" * 64,
                    "rubric_sha256": "c" * 64,
                    "rollback_evidence_sha256": sha256_file(rollback_path),
                    "config_sha256": sha256_json(config),
                },
                "target": {
                    "repository_url": config["promotion"]["repository_url"],
                    "repository_slug": config["promotion"]["repository_slug"],
                    "base_branch": "main",
                    "feature_branch": "codex/explore-approaches-v0.1.0",
                    "root_skills_path": "~/.codex/skills/explore-approaches",
                },
                "permissions": ["push_branch", "create_pr", "merge_reviewed_pr", "install_root_skill", "run_canary", "rollback"],
                "thresholds_met": True,
                "accepted_exceptions": [],
                "signature": {"algorithm": "ssh-keygen-y", "identity": "human", "namespace": "codex-skill-promotion", "value": base64.b64encode(b"signature" * 8).decode()},
            }
            validate_approval(approval, config, manifest, summary_path, holdout_path, rollback_path, signature_verifier=lambda *_: None)
            approval["candidate"]["base_commit"] = "d" * 40
            with self.assertRaises(PipelineError):
                validate_approval(approval, config, manifest, summary_path, holdout_path, rollback_path, signature_verifier=lambda *_: None)
            approval["candidate"]["base_commit"] = "a" * 40
            config["evaluation"] = {"trials": 999}
            with self.assertRaises(PipelineError):
                validate_approval(approval, config, manifest, summary_path, holdout_path, rollback_path, signature_verifier=lambda *_: None)

    def test_pr_and_release_records_are_immutable_and_provenance_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            prepared = {"base_commit": "a" * 40, "head_commit": "b" * 40, "staged_paths": ["skills/explore-approaches/SKILL.md"]}
            opened = {"pr_url": "https://github.com/example/repo/pull/1", "head_commit": "b" * 40, "opened_at": "2026-07-30T12:00:00Z"}
            pr_record = build_pr_record(
                prepared,
                opened,
                approval_sha256="c" * 64,
                candidate_manifest_sha256="d" * 64,
                config_sha256="e" * 64,
            )
            written_pr = write_immutable_record(run_dir / "pr-record.json", pr_record)
            merged = {
                "pr_url": opened["pr_url"],
                "head_commit": prepared["head_commit"],
                "merge_commit": "f" * 40,
                "merged_at": "2026-07-30T13:00:00Z",
                "github_evidence": {
                    "base_branch": "main",
                    "head_commit": prepared["head_commit"],
                    "merge_state_status": "UNKNOWN",
                    "review_decision": "APPROVED",
                    "approved_reviewers": ["reviewer"],
                    "successful_checks": ["tests"],
                    "verified_at": "2026-07-30T13:01:00Z",
                },
            }
            release = build_release_record(written_pr, merged)
            self.assertEqual(release["pr_record_sha256"], written_pr["record_sha256"])
            write_immutable_record(run_dir / "release-record.json", release)
            with self.assertRaises(PipelineError):
                write_immutable_record(run_dir / "pr-record.json", {**pr_record, "pr_url": "https://github.com/example/repo/pull/2"})

    def test_merge_recovery_requires_exact_provenance_review_and_checks(self) -> None:
        snapshot = {
            "state": "MERGED",
            "headRefOid": "b" * 40,
            "baseRefName": "main",
            "reviewDecision": "APPROVED",
            "mergeStateStatus": "UNKNOWN",
            "url": "https://github.com/example/repo/pull/1",
            "mergeCommit": {"oid": "f" * 40},
            "mergedAt": "2026-07-30T13:00:00Z",
            "author": {"login": "pull-author"},
            "reviews": [
                {
                    "state": "APPROVED",
                    "submittedAt": "2026-07-30T12:00:00Z",
                    "author": {"login": "reviewer"},
                }
            ],
            "statusCheckRollup": [
                {"__typename": "CheckRun", "name": "tests", "status": "COMPLETED", "conclusion": "SUCCESS"},
                {"__typename": "StatusContext", "context": "policy", "state": "SUCCESS"},
            ],
        }
        config = {
            "promotion": {
                "repository_slug": "example/repo",
                "base_branch": "main",
                "automation_actor": "automation",
                "required_reviewer_logins": ["reviewer"],
                "required_status_checks": ["tests", "policy"],
            }
        }
        completed = subprocess.CompletedProcess([], 0, stdout=json.dumps(snapshot), stderr="")
        with patch("automation.promotion.run_command", return_value=completed):
            merged = merge_reviewed_pr(snapshot["url"], "b" * 40, config)
        self.assertEqual(merged["merged_at"], snapshot["mergedAt"])
        open_snapshot = {
            **snapshot,
            "state": "OPEN",
            "mergeStateStatus": "CLEAN",
            "mergeCommit": None,
            "mergedAt": None,
        }
        command_results = [
            subprocess.CompletedProcess([], 0, stdout=json.dumps(open_snapshot), stderr=""),
            subprocess.CompletedProcess([], 0, stdout="", stderr=""),
            completed,
        ]
        with patch("automation.promotion.run_command", side_effect=command_results) as run:
            newly_merged = merge_reviewed_pr(snapshot["url"], "b" * 40, config)
        self.assertEqual(newly_merged["merge_commit"], snapshot["mergeCommit"]["oid"])
        self.assertEqual(run.call_count, 3)
        failed = {**snapshot, "statusCheckRollup": [{"__typename": "CheckRun", "name": "tests", "status": "COMPLETED", "conclusion": "FAILURE"}]}
        with patch("automation.promotion.run_command", return_value=subprocess.CompletedProcess([], 0, stdout=json.dumps(failed), stderr="")):
            with self.assertRaises(PipelineError):
                merge_reviewed_pr(snapshot["url"], "b" * 40, config)
        unrelated_success = {**config, "promotion": {**config["promotion"], "required_status_checks": ["required-policy"]}}
        with patch("automation.promotion.run_command", return_value=completed):
            with self.assertRaisesRegex(PipelineError, "required successful checks"):
                merge_reviewed_pr(snapshot["url"], "b" * 40, unrelated_success)
        for rejected_login in ("untrusted-outsider", "pull-author", "automation"):
            rejected = {
                **snapshot,
                "reviews": [
                    {
                        "state": "APPROVED",
                        "submittedAt": "2026-07-30T12:00:00Z",
                        "author": {"login": rejected_login},
                    }
                ],
            }
            with self.subTest(rejected_login=rejected_login):
                with patch(
                    "automation.promotion.run_command",
                    return_value=subprocess.CompletedProcess([], 0, stdout=json.dumps(rejected), stderr=""),
                ):
                    with self.assertRaisesRegex(PipelineError, "allowed independent reviewer"):
                        merge_reviewed_pr(snapshot["url"], "b" * 40, config)

        superseded = {
            **snapshot,
            "reviews": [
                {
                    "state": "APPROVED",
                    "submittedAt": "2026-07-30T12:00:00Z",
                    "author": {"login": "reviewer"},
                },
                {
                    "state": "CHANGES_REQUESTED",
                    "submittedAt": "2026-07-30T12:05:00Z",
                    "author": {"login": "reviewer"},
                },
            ],
        }
        with patch(
            "automation.promotion.run_command",
            return_value=subprocess.CompletedProcess([], 0, stdout=json.dumps(superseded), stderr=""),
        ):
            with self.assertRaisesRegex(PipelineError, "allowed independent reviewer"):
                merge_reviewed_pr(snapshot["url"], "b" * 40, config)

        placeholder_policy = {
            **config,
            "promotion": {
                **config["promotion"],
                "automation_actor": "REPLACE_WITH_AUTOMATION_ACTOR",
                "required_reviewer_logins": ["REPLACE_WITH_INDEPENDENT_REVIEWER"],
            },
        }
        with patch("automation.promotion.run_command", return_value=completed):
            with self.assertRaisesRegex(PipelineError, "non-placeholder GitHub automation actor"):
                merge_reviewed_pr(snapshot["url"], "b" * 40, placeholder_policy)

    def test_rollback_rehearsal_produces_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            record = rehearse_rollback(Path(temporary))
            self.assertEqual(record["result"], "passed")


if __name__ == "__main__":
    unittest.main()
