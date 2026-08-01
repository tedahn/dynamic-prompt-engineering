from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


EVALUATION_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = EVALUATION_ROOT / "scripts" / "validation_evidence.py"
SPEC = importlib.util.spec_from_file_location("validation_evidence", MODULE_PATH)
assert SPEC and SPEC.loader
VALIDATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATION)


class ValidationEvidenceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary.name) / "repo"
        self.repo.mkdir()
        self._git("init")
        self._git("config", "user.email", "test@example.com")
        self._git("config", "user.name", "Test User")
        (self.repo / "source.txt").write_text("original\n", encoding="utf-8")
        self._git("add", "source.txt")
        self._git("commit", "-m", "initial")
        self.output = self.repo / "evidence"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=self.repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout

    def _tool(self) -> dict:
        return {
            "name": "python",
            "argv": [sys.executable, "--version"],
            "cwd": ".",
        }

    def _command(self, code: str = "print('validated')") -> dict:
        return {
            "name": "unit-tests",
            "argv": [sys.executable, "-c", code],
            "cwd": ".",
            "tools": ["python"],
            "executable_tool": "python",
            "dependencies": [],
            "timeout_seconds": 10,
        }

    def _run(self, command: dict | None = None) -> dict:
        return VALIDATION.run_validation(
            repo_root=self.repo,
            output_dir=self.output,
            commands=[command or self._command()],
            tool_versions=[self._tool()],
        )

    def _read_json(self, name: str) -> dict:
        return json.loads((self.output / name).read_text(encoding="utf-8"))

    def test_run_records_content_projection_commands_versions_and_artifacts(self) -> None:
        result = self._run()

        self.assertEqual(result["status"], "passed")
        manifest = self._read_json("content-projection-manifest.json")
        recorded = self._read_json("validation-result.json")
        self.assertEqual(recorded, result)
        self.assertEqual(manifest["projection"]["entry_count"], 1)
        self.assertEqual(manifest["projection"]["entries"][0]["path"], "source.txt")
        self.assertTrue(manifest["projection"]["sha256"])
        self.assertEqual(recorded["tested_projection_sha256"], manifest["projection"]["sha256"])
        self.assertTrue(recorded["projection_unchanged_after_validation"])
        self.assertEqual(recorded["commands"][0]["argv"], self._command()["argv"])
        self.assertEqual(recorded["commands"][0]["exit_code"], 0)
        self.assertIn("Python", recorded["tool_versions"][0]["reported_version"])
        self.assertTrue(recorded["recorder"]["git_version"].startswith("git version "))
        self.assertEqual(len(recorded["artifact_manifest"]), 5)
        excluded = {row["path"] for row in manifest["exclusions"]}
        self.assertEqual(excluded, set(recorded["self_reference_policy"]["excluded_generated_paths"]))
        self.assertEqual(
            excluded,
            {row["path"] for row in recorded["artifact_manifest"]}
            | {recorded["self_reference_policy"]["result_path"]},
        )

        verification = VALIDATION.verify_evidence(
            self.repo,
            self.output / "content-projection-manifest.json",
            self.output / "validation-result.json",
        )
        self.assertTrue(verification["ok"], verification)
        self.assertEqual(verification["recorded_status"], "passed")

    def test_verify_detects_projected_source_drift(self) -> None:
        self._run()
        (self.repo / "source.txt").write_text("changed\n", encoding="utf-8")

        verification = VALIDATION.verify_evidence(
            self.repo,
            self.output / "content-projection-manifest.json",
            self.output / "validation-result.json",
        )

        self.assertFalse(verification["ok"])
        self.assertTrue(any("projection" in error for error in verification["errors"]))

    def test_verify_detects_artifact_tampering(self) -> None:
        self._run()
        stdout_path = self.output / "artifacts" / "commands" / "001-unit-tests.stdout.txt"
        stdout_path.write_text("tampered\n", encoding="utf-8")

        verification = VALIDATION.verify_evidence(
            self.repo,
            self.output / "content-projection-manifest.json",
            self.output / "validation-result.json",
        )

        self.assertFalse(verification["ok"])
        self.assertTrue(any("artifact" in error for error in verification["errors"]))

    def test_command_source_mutation_invalidates_the_run(self) -> None:
        command = self._command("from pathlib import Path; Path('source.txt').write_text('mutated\\n')")

        result = self._run(command)

        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["projection_unchanged_after_validation"])
        self.assertEqual(result["commands"][0]["exit_code"], 0)
        verification = VALIDATION.verify_evidence(
            self.repo,
            self.output / "content-projection-manifest.json",
            self.output / "validation-result.json",
        )
        self.assertFalse(verification["ok"])

    def test_projection_is_deterministic_and_represents_untracked_and_deleted_paths(self) -> None:
        (self.repo / "source.txt").unlink()
        (self.repo / "untracked.txt").write_text("new\n", encoding="utf-8")

        first = VALIDATION.build_projection(self.repo, [])
        second = VALIDATION.build_projection(self.repo, [])

        self.assertEqual(first, second)
        entries = {row["path"]: row for row in first["entries"]}
        self.assertEqual(entries["source.txt"]["kind"], "absent_tracked")
        self.assertEqual(entries["untracked.txt"]["kind"], "file")

    def test_relative_evidence_paths_resolve_from_repository_root(self) -> None:
        result = VALIDATION.run_validation(
            repo_root=self.repo,
            output_dir=Path("evidence"),
            commands=[self._command()],
            tool_versions=[self._tool()],
        )

        self.assertEqual(result["status"], "passed")
        verification = VALIDATION.verify_evidence(
            self.repo,
            Path("evidence/content-projection-manifest.json"),
            Path("evidence/validation-result.json"),
        )
        self.assertTrue(verification["ok"], verification)

    def test_timeout_is_recorded_as_integrity_valid_negative_evidence(self) -> None:
        command = self._command("import time; time.sleep(2)")
        command["timeout_seconds"] = 0.05

        result = self._run(command)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["commands"][0]["execution_status"], "timed_out")
        self.assertTrue(result["commands"][0]["timed_out"])
        verification = VALIDATION.verify_evidence(
            self.repo,
            self.output / "content-projection-manifest.json",
            self.output / "validation-result.json",
        )
        self.assertTrue(verification["ok"], verification)

    @unittest.skipUnless(os.name == "posix", "requires POSIX process groups")
    def test_successful_leader_with_surviving_fork_is_terminated_and_fails(self) -> None:
        command = self._command(
            "import os, time\n"
            "child = os.fork()\n"
            "if child == 0:\n"
            "    time.sleep(30)\n"
            "    os._exit(0)\n"
            "print(child, flush=True)\n"
        )

        result = self._run(command)

        record = result["commands"][0]
        self.assertEqual(result["status"], "failed")
        self.assertEqual(record["exit_code"], 0)
        self.assertEqual(record["execution_status"], "descendants_terminated")
        self.assertTrue(record["surviving_descendants_after_leader_exit"])
        self.assertTrue(record["cleanup_attempted"])
        self.assertTrue(record["process_group_empty_after_cleanup"])
        with self.assertRaises(ProcessLookupError):
            os.killpg(record["process_group_id"], 0)

    def test_bare_path_resolved_executable_is_rejected(self) -> None:
        command = self._command()
        command["argv"][0] = "python3"

        with self.assertRaisesRegex(VALIDATION.EvidenceError, "absolute path"):
            self._run(command)

    def test_existing_path_argument_must_be_declared(self) -> None:
        (self.repo / "script.py").write_text("print('ok')\n", encoding="utf-8")
        command = self._command()
        command["argv"] = [sys.executable, "script.py"]

        with self.assertRaisesRegex(VALIDATION.EvidenceError, "undeclared mutable dependency"):
            self._run(command)

    def test_projected_script_dependency_is_bound_to_projection(self) -> None:
        (self.repo / "script.py").write_text("print('ok')\n", encoding="utf-8")
        command = self._command()
        command["argv"] = [sys.executable, "script.py"]
        command["dependencies"] = [
            {"name": "script", "kind": "projected_file", "path": "script.py"}
        ]

        result = self._run(command)

        self.assertEqual(result["status"], "passed")
        dependency = result["commands"][0]["dependencies"][0]
        self.assertEqual(dependency["identity"]["projection_entry"]["path"], "script.py")
        self.assertTrue(result["commands"][0]["dependency_identities_match_bound"])

    def test_external_file_dependency_drift_is_detected(self) -> None:
        dependency_path = Path(self.temporary.name) / "external.py"
        dependency_path.write_text("VALUE = 1\n", encoding="utf-8")
        command = self._command()
        command["dependencies"] = [
            {
                "name": "external-module",
                "kind": "external_file",
                "path": str(dependency_path),
            }
        ]
        self._run(command)
        dependency_path.write_text("VALUE = 2\n", encoding="utf-8")

        verification = VALIDATION.verify_evidence(
            self.repo,
            self.output / "content-projection-manifest.json",
            self.output / "validation-result.json",
        )

        self.assertFalse(verification["ok"])
        self.assertTrue(any("dependency identity" in error for error in verification["errors"]))

    def test_child_receives_only_explicit_sanitized_environment(self) -> None:
        command = self._command("import json, os; print(json.dumps(dict(os.environ), sort_keys=True))")
        result = VALIDATION.run_validation(
            self.repo,
            self.output,
            [command],
            [self._tool()],
            environment={"CUSTOM_SETTING": "recorded"},
        )
        stdout = self.output / "artifacts" / "commands" / "001-unit-tests.stdout.txt"
        observed = json.loads(stdout.read_text(encoding="utf-8"))

        self.assertEqual(observed, result["environment"]["values"])
        self.assertNotIn("PATH", observed)
        self.assertNotIn("PYTHONPATH", observed)

    def test_path_resolution_environment_is_rejected(self) -> None:
        with self.assertRaisesRegex(VALIDATION.EvidenceError, "forbidden"):
            VALIDATION.run_validation(
                self.repo,
                self.output,
                [self._command()],
                [self._tool()],
                environment={"PYTHONPATH": "/mutable"},
            )

    def test_failed_command_is_preserved_as_integrity_valid_negative_evidence(self) -> None:
        result = self._run(self._command("raise SystemExit(7)"))

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["commands"][0]["exit_code"], 7)
        verification = VALIDATION.verify_evidence(
            self.repo,
            self.output / "content-projection-manifest.json",
            self.output / "validation-result.json",
        )
        self.assertTrue(verification["ok"], verification)
        self.assertEqual(verification["recorded_status"], "failed")

    def test_run_refuses_nonempty_output_directory(self) -> None:
        self.output.mkdir()
        (self.output / "existing.txt").write_text("do not overwrite\n", encoding="utf-8")

        with self.assertRaisesRegex(VALIDATION.EvidenceError, "not empty"):
            self._run()

    def test_command_must_name_every_recorded_tool_dependency(self) -> None:
        command = self._command()
        command["tools"] = ["missing"]

        with self.assertRaisesRegex(VALIDATION.EvidenceError, "unknown tool"):
            self._run(command)

    def test_manifest_hash_tampering_is_detected(self) -> None:
        self._run()
        manifest_path = self.output / "content-projection-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["git"]["head_sha"] = "0" * 40
        manifest_path.write_text(
            json.dumps(manifest, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )

        verification = VALIDATION.verify_evidence(
            self.repo,
            manifest_path,
            self.output / "validation-result.json",
        )

        self.assertFalse(verification["ok"])
        self.assertTrue(any("SHA-256 mismatch" in error for error in verification["errors"]))

    def test_artifact_index_descriptor_must_match_command_reference(self) -> None:
        self._run()
        result_path = self.output / "validation-result.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result["commands"][0]["stdout_artifact"]["kind"] = "incorrect-kind"
        VALIDATION.write_json(result_path, result)

        verification = VALIDATION.verify_evidence(
            self.repo,
            self.output / "content-projection-manifest.json",
            result_path,
        )

        self.assertFalse(verification["ok"])
        self.assertTrue(any("descriptor does not match" in error for error in verification["errors"]))

    def test_exclusion_set_cannot_be_widened_to_hide_source(self) -> None:
        self._run()
        manifest_path = self.output / "content-projection-manifest.json"
        result_path = self.output / "validation-result.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["exclusions"].append(
            {"path": "source.txt", "reason": "generated_validation_evidence"}
        )
        excluded = sorted(row["path"] for row in manifest["exclusions"])
        manifest["exclusions"] = sorted(manifest["exclusions"], key=lambda row: row["path"])
        manifest["projection"] = VALIDATION.build_projection(self.repo, excluded)
        VALIDATION.write_json(manifest_path, manifest)

        result = json.loads(result_path.read_text(encoding="utf-8"))
        descriptor = VALIDATION.artifact_descriptor(
            self.repo, manifest_path, "content_projection_manifest"
        )
        result["content_projection_manifest"] = descriptor
        result["tested_projection_sha256"] = manifest["projection"]["sha256"]
        result["self_reference_policy"]["excluded_generated_paths"] = excluded
        result["artifact_manifest"] = [
            descriptor if row["kind"] == "content_projection_manifest" else row
            for row in result["artifact_manifest"]
        ]
        VALIDATION.write_json(result_path, result)

        verification = VALIDATION.verify_evidence(self.repo, manifest_path, result_path)

        self.assertFalse(verification["ok"])
        self.assertTrue(any("exactly the generated evidence" in error for error in verification["errors"]))


if __name__ == "__main__":
    unittest.main()
