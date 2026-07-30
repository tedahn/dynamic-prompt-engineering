from __future__ import annotations

import json
import os
import stat
import statistics
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from automation.core import PipelineError, atomic_write_json, build_candidate_manifest, load_config
from automation.evaluation import (
    _command_binding,
    _cluster_interval,
    _subject_runtime_identity,
    _verify_attempt_artifacts,
    invoke_adapter,
    lifecycle_executable_bindings,
    verify_lifecycle_executable_binding,
    verify_human_review_ssh_signature,
)


class AdversarialAutomationTest(unittest.TestCase):
    def _runtime_config(self, argv: list[str], entrypoint: Path, **runtime: object) -> dict:
        return {
            "evaluation": {
                "subject_adapter_argv": argv,
                "subject_runtime": {
                    "adapter_id": "provider-adapter",
                    "provider_id": "provider",
                    "model_id": "model",
                    "settings": {},
                    "entrypoint_path": str(entrypoint),
                    "dependency_paths": [],
                    **runtime,
                },
            }
        }

    def test_module_and_inline_runtime_forms_are_rejected(self) -> None:
        executable = Path(sys.executable).resolve()
        for argv in (
            [sys.executable, "-m", "provider_adapter", "{input}", "{output}"],
            [sys.executable, "-c", "print('unbound')", "{input}", "{output}"],
        ):
            with self.subTest(argv=argv):
                with self.assertRaisesRegex(PipelineError, "module or inline interpreter"):
                    _subject_runtime_identity(self._runtime_config(argv, executable))

    def test_declarative_image_digest_is_rejected(self) -> None:
        executable = Path(sys.executable).resolve()
        for digest in ("", "sha256:" + "a" * 64):
            config = self._runtime_config(
                [sys.executable, "{input}", "{output}"],
                executable,
                image_digest=digest,
            )
            with self.subTest(digest=digest):
                with self.assertRaisesRegex(PipelineError, "image_digest or ambiguous artifact_paths"):
                    _subject_runtime_identity(config)

    def test_unrelated_entrypoint_and_symlink_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = root / "adapter.py"
            unrelated = root / "unrelated.py"
            adapter.write_text("print('adapter')\n", encoding="utf-8")
            unrelated.write_text("print('unrelated')\n", encoding="utf-8")
            argv = [sys.executable, str(adapter), "{input}", "{output}"]
            with self.assertRaisesRegex(PipelineError, "resolved executable or a concrete absolute argv file"):
                _subject_runtime_identity(self._runtime_config(argv, unrelated))
            linked = root / "linked.py"
            linked.symlink_to(adapter)
            with self.assertRaisesRegex(PipelineError, "absolute regular non-symlink"):
                _subject_runtime_identity(self._runtime_config(argv, linked))

    def test_runtime_hashes_valid_direct_and_script_entrypoints_and_detects_mutation(self) -> None:
        executable = Path(sys.executable).resolve()
        direct = _subject_runtime_identity(
            self._runtime_config([sys.executable, "{input}", "{output}"], executable)
        )
        self.assertEqual(direct["entrypoint"]["path"], str(executable))
        with tempfile.TemporaryDirectory() as temporary:
            adapter = Path(temporary) / "adapter.py"
            adapter.write_text("print('v1')\n", encoding="utf-8")
            config = self._runtime_config(
                [sys.executable, str(adapter), "{input}", "{output}"], adapter
            )
            before = _subject_runtime_identity(config)
            adapter.write_text("print('v2')\n", encoding="utf-8")
            after = _subject_runtime_identity(config)
            self.assertNotEqual(before["sha256"], after["sha256"])
            dependencies = Path(temporary) / "dependencies"
            dependencies.mkdir()
            dependency = dependencies / "client.py"
            dependency.write_text("VERSION = 1\n", encoding="utf-8")
            dependency_config = self._runtime_config(
                [sys.executable, str(adapter), "{input}", "{output}"],
                adapter,
                dependency_paths=[str(dependencies)],
            )
            dependency_before = _subject_runtime_identity(dependency_config)
            dependency.write_text("VERSION = 2\n", encoding="utf-8")
            dependency_after = _subject_runtime_identity(dependency_config)
            self.assertNotEqual(dependency_before["sha256"], dependency_after["sha256"])

    def test_lifecycle_binding_hashes_absolute_entrypoint_and_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entrypoint = root / "validator.py"
            dependency_root = root / "dependencies"
            dependency_root.mkdir()
            dependency = dependency_root / "policy.py"
            entrypoint.write_text("print('v1')\n", encoding="utf-8")
            dependency.write_text("VERSION = 1\n", encoding="utf-8")
            argv = [str(Path(sys.executable).resolve()), str(entrypoint), "{skill}"]
            before = _command_binding(
                "validator",
                argv,
                entrypoint_path=str(entrypoint),
                dependency_paths=[str(dependency_root)],
                allowed_placeholders=("{skill}",),
            )
            self.assertEqual(before["entrypoint"]["path"], str(entrypoint.resolve()))
            self.assertEqual(before["dependencies"][0]["path"], str(dependency_root.resolve()))
            entrypoint.write_text("print('v2')\n", encoding="utf-8")
            after_entrypoint = _command_binding(
                "validator",
                argv,
                entrypoint_path=str(entrypoint),
                dependency_paths=[str(dependency_root)],
                allowed_placeholders=("{skill}",),
            )
            self.assertNotEqual(before["sha256"], after_entrypoint["sha256"])
            dependency.write_text("VERSION = 2\n", encoding="utf-8")
            after_dependency = _command_binding(
                "validator",
                argv,
                entrypoint_path=str(entrypoint),
                dependency_paths=[str(dependency_root)],
                allowed_placeholders=("{skill}",),
            )
            self.assertNotEqual(after_entrypoint["sha256"], after_dependency["sha256"])

    def test_lifecycle_binding_rejects_relative_missing_and_symlink_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            entrypoint = root / "validator.py"
            entrypoint.write_text("print('ok')\n", encoding="utf-8")
            executable = str(Path(sys.executable).resolve())
            with self.assertRaisesRegex(PipelineError, "absolute path"):
                _command_binding(
                    "validator",
                    ["python3", str(entrypoint), "{skill}"],
                    entrypoint_path=str(entrypoint),
                    dependency_paths=[],
                    allowed_placeholders=("{skill}",),
                )
            with self.assertRaisesRegex(PipelineError, "bare relative or unresolved"):
                _command_binding(
                    "validator",
                    [executable, "validator.py", "{skill}"],
                    entrypoint_path=str(entrypoint),
                    dependency_paths=[],
                    allowed_placeholders=("{skill}",),
                )
            with self.assertRaisesRegex(PipelineError, "missing|regular non-symlink"):
                _command_binding(
                    "validator",
                    [executable, str(root / "missing.py"), "{skill}"],
                    entrypoint_path=str(root / "missing.py"),
                    dependency_paths=[],
                    allowed_placeholders=("{skill}",),
                )
            linked_entrypoint = root / "linked.py"
            linked_entrypoint.symlink_to(entrypoint)
            with self.assertRaisesRegex(PipelineError, "regular non-symlink"):
                _command_binding(
                    "validator",
                    [executable, str(linked_entrypoint), "{skill}"],
                    entrypoint_path=str(linked_entrypoint),
                    dependency_paths=[],
                    allowed_placeholders=("{skill}",),
                )
            linked_executable = root / "linked-python"
            linked_executable.symlink_to(executable)
            with self.assertRaisesRegex(PipelineError, "regular non-symlink"):
                _command_binding(
                    "validator",
                    [str(linked_executable), str(entrypoint), "{skill}"],
                    entrypoint_path=str(entrypoint),
                    dependency_paths=[],
                    allowed_placeholders=("{skill}",),
                )
            linked_dependency = root / "linked-dependency.py"
            linked_dependency.symlink_to(entrypoint)
            with self.assertRaisesRegex(PipelineError, "missing or unsafe"):
                _command_binding(
                    "validator",
                    [executable, str(entrypoint), "{skill}"],
                    entrypoint_path=str(entrypoint),
                    dependency_paths=[str(linked_dependency)],
                    allowed_placeholders=("{skill}",),
                )
            with self.assertRaisesRegex(PipelineError, "missing or unsafe"):
                _command_binding(
                    "validator",
                    [executable, str(entrypoint), "{skill}"],
                    entrypoint_path=str(entrypoint),
                    dependency_paths=[str(root / "missing-dependency.py")],
                    allowed_placeholders=("{skill}",),
                )

    def test_lifecycle_recovery_rehashes_validator_and_canary_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            validator = root / "validator.py"
            canary = root / "canary.py"
            dependencies = root / "dependencies"
            dependencies.mkdir()
            dependency = dependencies / "policy.py"
            validator.write_text("print('validator-v1')\n", encoding="utf-8")
            canary.write_text("print('canary-v1')\n", encoding="utf-8")
            dependency.write_text("POLICY = 1\n", encoding="utf-8")
            executable = str(Path(sys.executable).resolve())
            config = {
                "evaluation": {
                    "canary_adapter_argv": [
                        executable,
                        str(canary),
                        "{input}",
                        "{output}",
                    ],
                    "canary_entrypoint_path": str(canary),
                    "canary_dependency_paths": [str(dependencies)],
                },
                "installation": {
                    "source_mode": "local-test",
                    "validator_argv": [executable, str(validator), "{skill}"],
                    "validator_entrypoint_path": str(validator),
                    "validator_dependency_paths": [str(dependencies)],
                },
            }
            frozen = lifecycle_executable_bindings(config)
            run_dir = root / "run"
            atomic_write_json(run_dir / "frozen/lifecycle-executables.json", frozen)
            atomic_write_json(
                run_dir / "plan.json",
                {"lifecycle_executables_sha256": frozen["sha256"]},
            )
            self.assertEqual(
                verify_lifecycle_executable_binding(run_dir, config, "validator"),
                frozen["commands"]["validator"],
            )
            validator.write_text("print('validator-v2')\n", encoding="utf-8")
            with self.assertRaisesRegex(PipelineError, "changed after freeze"):
                verify_lifecycle_executable_binding(run_dir, config, "validator")
            validator.write_text("print('validator-v1')\n", encoding="utf-8")
            dependency.write_text("POLICY = 2\n", encoding="utf-8")
            with self.assertRaisesRegex(PipelineError, "changed after freeze"):
                verify_lifecycle_executable_binding(run_dir, config, "canary")

    def test_lifecycle_binding_rejects_module_inline_eval_and_unresolved_tokens(self) -> None:
        executable = str(Path(sys.executable).resolve())
        for argv in (
            [executable, "-m", "validator", "{skill}"],
            [executable, "-mvalidator", "{skill}"],
            [executable, "-c", "print('pass')", "{skill}"],
            [executable, "-cprint('pass')", "{skill}"],
            [executable, "-eprint('pass')", "{skill}"],
            [executable, "-p1+1", "{skill}"],
            [executable, "--eval", "pass", "{skill}"],
            [executable, "--eval=pass", "{skill}"],
            [executable, "-encodedcommandAAAA", "{skill}"],
            [executable, "-encodedcommand:AAAA", "{skill}"],
        ):
            with self.subTest(argv=argv):
                with self.assertRaisesRegex(PipelineError, "module, inline, eval"):
                    _command_binding(
                        "validator",
                        argv,
                        entrypoint_path=executable,
                        dependency_paths=[],
                        allowed_placeholders=("{skill}",),
                    )
        with self.assertRaisesRegex(PipelineError, "bare relative or unresolved"):
            _command_binding(
                "validator",
                [executable, "unresolved-token", "{skill}"],
                entrypoint_path=executable,
                dependency_paths=[],
                allowed_placeholders=("{skill}",),
            )
        with self.assertRaisesRegex(PipelineError, "exact required placeholders"):
            _command_binding(
                "validator",
                [executable, "{skill}", "{skill}"],
                entrypoint_path=executable,
                dependency_paths=[],
                allowed_placeholders=("{skill}",),
            )

    def test_candidate_manifest_excludes_unrelated_dirty_workspace_artifacts(self) -> None:
        repo_root = Path(__file__).resolve().parents[4]
        config = load_config(Path(__file__).resolve().parents[1] / "config" / "pipeline-v1.json")
        manifest = build_candidate_manifest(repo_root, config)
        paths = {entry["path"] for entry in manifest["files"]}
        self.assertNotIn("README.md", paths)
        self.assertFalse(any("review-skill" in path or "T-020" in path or "context-composer" in path for path in paths))

    def test_unbound_adapter_response_cannot_reuse_stale_success(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = root / "unbound.py"
            adapter.write_text(
                "import json,sys\n"
                "json.dump({'schema_version':'1.0','status':'completed','output':{'passed':True},"
                "'telemetry':{'latency_ms':1,'input_tokens':1,'output_tokens':1}},open(sys.argv[2],'w'))\n",
                encoding="utf-8",
            )
            result = invoke_adapter(
                [sys.executable, str(adapter), "{input}", "{output}"],
                {"schema_version": "1.0", "adapter_kind": "canary"},
                root / "attempts",
                timeout_seconds=5,
                max_transient_retries=0,
            )
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["response"]["status"], "permanent_error")
            self.assertIn("fresh request", result["response"]["error"])

    def test_permissive_umask_and_adapter_output_are_normalized_then_checked_on_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = root / "permissive.py"
            adapter.write_text(
                "import hashlib,json,os,sys\n"
                "request=json.load(open(sys.argv[1],encoding='utf-8'))\n"
                "digest=hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest()\n"
                "json.dump({'schema_version':'1.0','request_id':request['request_id'],"
                "'request_sha256':digest,'status':'completed','output':{'passed':True}},"
                "open(sys.argv[2],'w',encoding='utf-8'))\n"
                "os.chmod(sys.argv[2],0o644)\n",
                encoding="utf-8",
            )
            previous_umask = os.umask(0)
            try:
                result = invoke_adapter(
                    [str(Path(sys.executable).resolve()), str(adapter), "{input}", "{output}"],
                    {"schema_version": "1.0", "adapter_kind": "canary"},
                    root / "attempts",
                    timeout_seconds=5,
                    max_transient_retries=0,
                )
            finally:
                os.umask(previous_umask)
            self.assertEqual(result["status"], "completed")
            for current, directories, files in os.walk(root / "attempts"):
                self.assertEqual(stat.S_IMODE(Path(current).stat().st_mode), 0o700)
                for name in directories:
                    self.assertEqual(stat.S_IMODE((Path(current) / name).stat().st_mode), 0o700)
                for name in files:
                    self.assertEqual(stat.S_IMODE((Path(current) / name).stat().st_mode), 0o600)
            raw_response = Path(result["attempts"][0]["raw_response_path"])
            raw_response.chmod(0o644)
            with self.assertRaisesRegex(PipelineError, "mode must be 0600"):
                _verify_attempt_artifacts(result["attempts"], root / "attempts")

    def test_human_review_reviewer_must_match_configured_signature_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            allowed_signers = Path(temporary) / "allowed-signers"
            allowed_signers.write_text("placeholder\n", encoding="utf-8")
            review = {
                "reviewer": "self-asserted-reviewer",
                "signature": {
                    "algorithm": "ssh-keygen-y",
                    "identity": "verified-reviewer",
                    "namespace": "codex-skill-human-review",
                    "value": "c2lnbmF0dXJl",
                },
            }
            config = {
                "human_review_verification": {
                    "allowed_signers_path": str(allowed_signers),
                    "expected_identity": "verified-reviewer",
                    "namespace": "codex-skill-human-review",
                }
            }
            with self.assertRaisesRegex(PipelineError, "attribution"):
                verify_human_review_ssh_signature(review, config)

    def test_resource_bounds_bootstrap_the_declared_median(self) -> None:
        values = {"task-a": 1.0, "task-b": 1.0, "task-c": 100.0}
        interval = _cluster_interval(values, seed=7, samples=500, statistic=statistics.median)
        self.assertEqual(interval["estimate"], 1.0)
        self.assertNotEqual(interval["estimate"], statistics.fmean(values.values()))


if __name__ == "__main__":
    unittest.main()
