from __future__ import annotations

import importlib.util
import json
import os
from collections import defaultdict
from pathlib import Path
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_pilot.py"
SPEC = importlib.util.spec_from_file_location("run_pilot", SCRIPT)
assert SPEC and SPEC.loader
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


class RunPilotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.inputs = RUNNER.load_pilot_inputs()

    def test_canonical_experiment_is_blocked_after_frozen_artifact_drift(self) -> None:
        self.assertEqual(self.inputs.experiment["status"], "blocked-artifact-drift")
        self.assertTrue(self.inputs.experiment["replacement_preflight_required"])
        self.assertIn(
            "Experiment is not pilot-authorized-frozen",
            RUNNER.validate_pilot_inputs(self.inputs),
        )

    def test_scored_plan_is_deterministic_latin_square_with_independent_blinding(self) -> None:
        plan_a, blind_a = RUNNER.generate_scored_plan(
            self.inputs, "run-test", plan_seed=101, blind_seed=202
        )
        plan_b, blind_b = RUNNER.generate_scored_plan(
            self.inputs, "run-test", plan_seed=101, blind_seed=202
        )
        plan_c, blind_c = RUNNER.generate_scored_plan(
            self.inputs, "run-test", plan_seed=101, blind_seed=303
        )

        self.assertEqual(plan_a, plan_b)
        self.assertEqual(blind_a, blind_b)
        self.assertEqual(len(plan_a), 45)
        self.assertEqual(len({row["cell_id"] for row in plan_a}), 45)
        self.assertEqual(len({row["blind_id"] for row in plan_a}), 45)

        grouped: dict[tuple[str, int], list[dict[str, object]]] = defaultdict(list)
        for row in plan_a:
            grouped[(str(row["fixture_id"]), int(row["trial"]))].append(row)
        self.assertEqual(len(grouped), 15)
        for rows in grouped.values():
            self.assertEqual(
                {row["workflow_id"] for row in rows}, set(RUNNER.WORKFLOW_IDS)
            )
            self.assertEqual(sorted(row["latin_position"] for row in rows), [0, 1, 2])
            self.assertEqual(sorted(row["blind_order"] for row in rows), [1, 2, 3])

        execution_fields = (
            "execution_index",
            "cell_id",
            "fixture_id",
            "workflow_id",
            "trial",
            "latin_position",
        )
        self.assertEqual(
            [[row[key] for key in execution_fields] for row in plan_a],
            [[row[key] for key in execution_fields] for row in plan_c],
        )
        self.assertNotEqual(blind_a, blind_c)

    def test_preflight_plan_has_three_discarded_cells_and_both_tool_policies(self) -> None:
        rows = RUNNER.generate_preflight_plan(self.inputs, "run-test")
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(row["phase"] == "preflight" for row in rows))
        self.assertTrue(all(row["discarded"] is True for row in rows))
        self.assertEqual({row["workflow_id"] for row in rows}, set(RUNNER.WORKFLOW_IDS))
        self.assertEqual({row["tool_policy"] for row in rows}, {"none", "workspace"})

    def test_experiment_preflight_registry_matches_generated_plan(self) -> None:
        rows = RUNNER.generate_preflight_plan(self.inputs, "CANONICAL-PREFLIGHT")
        preflight = self.inputs.experiment["preflight"]
        self.assertEqual(preflight["fixture_ids"], [row["fixture_id"] for row in rows])
        self.assertEqual(preflight["workflow_ids"], [row["workflow_id"] for row in rows])
        self.assertEqual(
            preflight["workflow_fixture_pairs"],
            [
                {"workflow_id": row["workflow_id"], "fixture_id": row["fixture_id"]}
                for row in rows
            ],
        )
        self.assertEqual(preflight["tool_policies"], [row["tool_policy"] for row in rows])

    def test_cell_environment_uses_a_fresh_runtime_home(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            auth_home = root / "auth-home"
            auth_home.mkdir()
            (auth_home / "auth.json").write_text("{}\n", encoding="utf-8")
            runtime_root = root / "runtime"
            runtime_root.mkdir()
            workspace = root / "workspace"
            tool_temp = workspace / ".pilot-runtime-tmp"
            tool_temp.mkdir(parents=True)
            environment = RUNNER.isolated_environment(
                auth_home,
                runtime_root,
                temporary_dir=tool_temp,
                tool_readable_roots=(workspace, tool_temp),
            )
            runtime_home = Path(environment["CODEX_HOME"])
            self.assertNotEqual(runtime_home, auth_home)
            self.assertTrue((runtime_home / "auth.json").is_symlink())
            self.assertFalse((runtime_home / "skills").exists())
            self.assertFalse((runtime_home / "config.toml").exists())
            self.assertFalse(runtime_home.is_relative_to(workspace))
            self.assertTrue(Path(environment["HOME"]).is_relative_to(tool_temp.resolve()))
            self.assertNotEqual(environment["HOME"], environment["CODEX_HOME"])

    def test_workspace_policy_cell_cannot_locate_or_read_auth_material(self) -> None:
        synthetic_auth = b'{"synthetic-auth-marker":"not-a-real-credential"}\n'
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            codex_home = root / "isolated-codex-home"
            codex_home.mkdir()
            (codex_home / "auth.json").write_bytes(synthetic_auth)
            cli = self._write_fake_codex(root / "codex")
            run_dir = root / "run"
            row = next(
                item
                for item in RUNNER.generate_preflight_plan(self.inputs, "auth-boundary-test")
                if item["tool_policy"] == "workspace"
            )

            result = RUNNER.execute_cell(
                run_dir=run_dir,
                inputs=self.inputs,
                row=row,
                cli_path=cli,
                codex_home=codex_home,
                max_retries=0,
                timeout_seconds=5,
                retry_backoff_seconds=(),
                cli_version="codex-cli test",
            )

            self.assertEqual(result["status"], "completed")
            reports = RUNNER.load_jsonl(root / "workspace-auth-checks.jsonl")
            self.assertEqual(len(reports), 1)
            self.assertEqual(
                reports[0],
                {
                    "auth_content_found": False,
                    "auth_name_found": False,
                    "codex_home_exposed": False,
                    "runtime_home_under_tool_root": False,
                    "source_auth_under_tool_root": False,
                },
            )
            self.assertNotIn(
                synthetic_auth,
                b"".join(
                    path.read_bytes()
                    for path in run_dir.rglob("*")
                    if path.is_file() and not path.is_symlink()
                ),
            )

    def test_auth_target_inside_tool_root_is_rejected_before_runtime_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            tool_temp = workspace / ".pilot-runtime-tmp"
            tool_temp.mkdir(parents=True)
            auth_target = workspace / "exposed-auth.json"
            auth_target.write_text('{"synthetic":"only"}\n', encoding="utf-8")
            auth_home = root / "auth-home"
            auth_home.mkdir()
            (auth_home / "auth.json").symlink_to(auth_target)
            runtime_root = root / "runtime"
            runtime_root.mkdir()

            with self.assertRaisesRegex(
                RUNNER.PilotError, "Authentication home overlaps a tool-readable root"
            ):
                RUNNER.isolated_environment(
                    auth_home,
                    runtime_root,
                    temporary_dir=tool_temp,
                    tool_readable_roots=(workspace, tool_temp),
                )

            self.assertFalse((runtime_root / "codex-home").exists())

    def test_tool_root_symlink_alias_to_auth_home_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            auth_home = root / "auth-home"
            auth_home.mkdir()
            (auth_home / "auth.json").write_text(
                '{"synthetic":"only"}\n', encoding="utf-8"
            )
            workspace = root / "workspace"
            tool_temp = workspace / ".pilot-runtime-tmp"
            tool_temp.mkdir(parents=True)
            (workspace / "auth-home-alias").symlink_to(
                auth_home, target_is_directory=True
            )
            runtime_root = root / "runtime"
            runtime_root.mkdir()

            with self.assertRaisesRegex(
                RUNNER.PilotError,
                "Tool-readable root contains an alias to authentication material",
            ):
                RUNNER.isolated_environment(
                    auth_home,
                    runtime_root,
                    temporary_dir=tool_temp,
                    tool_readable_roots=(workspace, tool_temp),
                )

            self.assertFalse((runtime_root / "codex-home").exists())

    def test_runtime_inspection_cleans_root_after_setup_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            auth_home = root / "auth-home"
            auth_home.mkdir()
            (auth_home / "auth.json").write_text("{}\n", encoding="utf-8")
            cli = self._write_fake_codex(root / "codex")
            inspection_root = root / "inspection-runtime"

            def create_inspection_root(*, prefix: str) -> str:
                self.assertEqual(prefix, "pilot-v2-runtime-inspect-")
                inspection_root.mkdir()
                return str(inspection_root)

            with mock.patch.object(
                RUNNER.tempfile, "mkdtemp", side_effect=create_inspection_root
            ), mock.patch.object(
                RUNNER,
                "isolated_environment",
                side_effect=RUNNER.PilotError("injected setup failure"),
            ):
                readiness = RUNNER.inspect_runtime(cli, auth_home)

            self.assertFalse(readiness["ok"])
            self.assertIn(
                "Runtime readiness check failed: PilotError", readiness["errors"]
            )
            self.assertFalse(inspection_root.exists())

    def test_runtime_inspection_cleans_root_after_child_process_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            auth_home = root / "auth-home"
            auth_home.mkdir()
            (auth_home / "auth.json").write_text("{}\n", encoding="utf-8")
            cli = self._write_fake_codex(root / "codex")
            inspection_root = root / "inspection-runtime"

            def create_inspection_root(*, prefix: str) -> str:
                self.assertEqual(prefix, "pilot-v2-runtime-inspect-")
                inspection_root.mkdir()
                return str(inspection_root)

            with mock.patch.object(
                RUNNER.tempfile, "mkdtemp", side_effect=create_inspection_root
            ), mock.patch.object(
                RUNNER.subprocess, "run", side_effect=OSError("injected child failure")
            ):
                readiness = RUNNER.inspect_runtime(cli, auth_home)

            self.assertFalse(readiness["ok"])
            self.assertIn(
                "Runtime readiness check failed: OSError", readiness["errors"]
            )
            self.assertFalse(inspection_root.exists())

    def test_cell_runtime_is_cleaned_after_child_process_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            auth_home = root / "auth-home"
            auth_home.mkdir()
            (auth_home / "auth.json").write_text("{}\n", encoding="utf-8")
            run_dir = root / "run"
            runtime_root = root / "cell-runtime"
            row = next(
                item
                for item in RUNNER.generate_preflight_plan(self.inputs, "cleanup-test")
                if item["tool_policy"] == "workspace"
            )

            def create_cell_runtime(*, prefix: str, dir: Path) -> str:
                self.assertEqual(prefix, "pilot-v2-cell-runtime-")
                self.assertEqual(Path(dir).resolve(), auth_home.parent.resolve())
                runtime_root.mkdir()
                return str(runtime_root)

            with mock.patch.object(
                RUNNER.tempfile, "mkdtemp", side_effect=create_cell_runtime
            ), mock.patch.object(
                RUNNER, "_invoke_cli", side_effect=OSError("injected child failure")
            ):
                with self.assertRaisesRegex(OSError, "injected child failure"):
                    RUNNER.execute_cell(
                        run_dir=run_dir,
                        inputs=self.inputs,
                        row=row,
                        cli_path=root / "codex",
                        codex_home=auth_home,
                        max_retries=0,
                        timeout_seconds=5,
                        retry_backoff_seconds=(),
                        cli_version="codex-cli test",
                    )

            self.assertFalse(runtime_root.exists())

    def test_codex_command_freezes_model_effort_features_and_policy(self) -> None:
        common = set(RUNNER.COMMON_FEATURE_DISABLES)
        shell = set(RUNNER.NONE_POLICY_FEATURE_DISABLES)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            none_command = RUNNER.build_codex_command(
                Path("/opt/codex"), root / "codex-home", "none", Path("/private/var/empty")
            )
            workspace_command = RUNNER.build_codex_command(
                Path("/opt/codex"), root / "codex-home", "workspace", root / "workspace"
            )

        def disabled(command: list[str]) -> set[str]:
            return {command[index + 1] for index, value in enumerate(command) if value == "--disable"}

        self.assertEqual(disabled(none_command), common | shell)
        self.assertEqual(disabled(workspace_command), common)
        self.assertIn("gpt-5.6-sol", none_command)
        self.assertIn('model_reasoning_effort="high"', none_command)
        self.assertIn(
            'shell_environment_policy.exclude=["CODEX_HOME"]', workspace_command
        )
        self.assertEqual(none_command[none_command.index("--sandbox") + 1], "read-only")
        self.assertEqual(
            workspace_command[workspace_command.index("--sandbox") + 1], "workspace-write"
        )
        self.assertEqual(none_command[-1], "-")

    def test_prompt_uses_condition_inputs_without_grader_leakage(self) -> None:
        fixture = self.inputs.fixtures[0]
        for workflow in self.inputs.workflows:
            prompt = RUNNER.build_prompt(self.inputs, fixture, workflow)
            self.assertIn(fixture["request"], prompt)
            self.assertIn(fixture["context"], prompt)
            self.assertNotIn(fixture["expected"], prompt)
            self.assertNotIn(fixture["forbidden"], prompt)
        pro = next(row for row in self.inputs.workflows if row["workflow_id"] == "B04_PRO_INLINE_1CALL")
        self.assertIn("# Professionalize Prompt", RUNNER.build_prompt(self.inputs, fixture, pro))

    def test_event_parser_captures_output_usage_thread_and_traces(self) -> None:
        raw = "\n".join(
            [
                json.dumps({"type": "thread.started", "thread_id": "thread-1"}),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {
                            "type": "command_execution",
                            "command": "python -V",
                            "exit_code": 0,
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "item.completed",
                        "item": {"type": "agent_message", "text": "finished answer"},
                    }
                ),
                json.dumps(
                    {
                        "type": "turn.completed",
                        "usage": {"input_tokens": 11, "output_tokens": 7},
                    }
                ),
            ]
        )
        parsed = RUNNER.parse_cli_events(raw)
        self.assertEqual(parsed["thread_id"], "thread-1")
        self.assertEqual(parsed["response"], "finished answer")
        self.assertEqual(parsed["usage"]["input_tokens"], 11)
        self.assertEqual(len(parsed["command_traces"]), 1)
        self.assertEqual(parsed["tool_traces"], [])

    def test_completed_output_is_never_reclassified_from_its_semantics(self) -> None:
        parsed = {
            "response": "rate limit, try again, timeout",
            "error_events": [],
            "event_types": {"turn.completed": 1},
            "thread_id": "thread-1",
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "non_json_line_count": 0,
        }
        result = RUNNER.classify_attempt(exit_code=0, stderr="", parsed=parsed, timed_out=False)
        self.assertEqual(result, ("completed", False, None))
        failed = RUNNER.classify_attempt(
            exit_code=1,
            stderr="HTTP 429: temporarily unavailable",
            parsed={"response": "", "error_events": []},
            timed_out=False,
        )
        self.assertEqual(failed[0], "transient_failed")
        self.assertTrue(failed[1])

    def test_workspace_snapshot_and_diff_are_content_addressed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "a.txt").write_text("before\n", encoding="utf-8")
            before = RUNNER.capture_workspace(root)
            (root / "a.txt").write_text("after\n", encoding="utf-8")
            (root / "b.txt").write_text("new\n", encoding="utf-8")
            after = RUNNER.capture_workspace(root)
            diff, changed = RUNNER.render_workspace_diff(before, after)
        self.assertNotEqual(before.public["tree_sha256"], after.public["tree_sha256"])
        self.assertEqual(changed, ["a.txt", "b.txt"])
        self.assertIn("-before", diff)
        self.assertIn("+after", diff)

    def test_cli_plan_preflight_run_and_resume_with_fake_codex(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            codex_home = root / "isolated-codex-home"
            codex_home.mkdir()
            (codex_home / "auth.json").write_text(
                '{"synthetic-auth-marker":"not-a-real-credential"}\n', encoding="utf-8"
            )
            cli = self._write_fake_codex(root / "codex")
            run_dir = root / "run"

            frozen_experiment = json.loads(json.dumps(self.inputs.experiment))
            frozen_experiment["status"] = "pilot-authorized-frozen"
            canonical_rows, _ = RUNNER.generate_scored_plan(
                self.inputs,
                "CANONICAL-RUN",
                plan_seed=RUNNER.DEFAULT_PLAN_SEED,
                blind_seed=RUNNER.DEFAULT_BLIND_SEED,
            )
            frozen_experiment["pilot"]["expected_plan_sha256"] = (
                RUNNER.canonical_scored_plan_sha256(canonical_rows)
            )
            frozen_experiment["frozen_artifacts"] = [
                {
                    "path": relative,
                    "sha256": RUNNER.sha256_file(RUNNER.PILOT_ROOT / relative),
                    "bytes": (RUNNER.PILOT_ROOT / relative).stat().st_size,
                }
                for relative in RUNNER.FROZEN_ARTIFACT_PATHS
            ]
            frozen_inputs = self.inputs._replace(experiment=frozen_experiment)
            original_loader = RUNNER.load_pilot_inputs
            RUNNER.load_pilot_inputs = lambda: frozen_inputs
            self.addCleanup(setattr, RUNNER, "load_pilot_inputs", original_loader)

            common = ["--cli-path", str(cli), "--codex-home", str(codex_home)]
            self.assertEqual(
                RUNNER.main(
                    ["plan", *common, "--run-dir", str(run_dir), "--run-id", "fake-run"]
                ),
                0,
            )
            self.assertEqual(
                RUNNER.main(["preflight", *common, "--run-dir", str(run_dir)]), 0
            )
            self.assertEqual(RUNNER.main(["run", *common, "--run-dir", str(run_dir)]), 0)

            plan = RUNNER.load_jsonl(run_dir / "plan-private.jsonl")
            self.assertEqual(len(plan), 45)
            metadata = [
                json.loads((run_dir / row["cell_dir"] / "metadata.json").read_text())
                for row in plan
            ]
            self.assertTrue(all(row["status"] == "completed" for row in metadata))
            self.assertTrue(all(row["requested_model"] == "gpt-5.6-sol" for row in metadata))
            calls_before = int((cli.parent / "exec-count.txt").read_text())
            self.assertEqual(calls_before, 48)

            self.assertEqual(RUNNER.main(["run", *common, "--run-dir", str(run_dir)]), 0)
            calls_after = int((cli.parent / "exec-count.txt").read_text())
            self.assertEqual(calls_after, calls_before)

    def _write_fake_codex(self, path: Path) -> Path:
        feature_names = sorted(
            set(RUNNER.COMMON_FEATURE_DISABLES) | set(RUNNER.NONE_POLICY_FEATURE_DISABLES)
        )
        script = f"""#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
home = Path(os.environ["CODEX_HOME"])
if args == ["--version"]:
    print("codex-cli test")
    raise SystemExit(0)
if args[:2] == ["login", "status"]:
    print("Logged in using ChatGPT")
    raise SystemExit(0)
if args[:2] == ["features", "list"]:
    for name in {feature_names!r}:
        print(f"{{name:<44}} stable             true")
    raise SystemExit(0)
if "exec" in args:
    workspace = Path(args[args.index("--cd") + 1]).resolve()
    sandbox = args[args.index("--sandbox") + 1]
    if sandbox == "workspace-write":
        configs = [args[index + 1] for index, value in enumerate(args) if value == "--config"]
        tool_env = dict(os.environ)
        if 'shell_environment_policy.exclude=["CODEX_HOME"]' in configs:
            tool_env.pop("CODEX_HOME", None)
        tool_roots = [
            workspace,
            Path(tool_env["HOME"]).resolve(),
            Path(tool_env["TMPDIR"]).resolve(),
        ]
        runtime_home = home.resolve()
        source_auth = (home / "auth.json").resolve()
        auth_bytes = source_auth.read_bytes()
        auth_name_found = False
        auth_content_found = False
        for root in tool_roots:
            for candidate in root.rglob("*"):
                if candidate.name == "auth.json":
                    auth_name_found = True
                if candidate.is_file() and not candidate.is_symlink():
                    try:
                        auth_content_found = auth_content_found or auth_bytes in candidate.read_bytes()
                    except OSError:
                        pass
        report = {{
            "auth_content_found": auth_content_found,
            "auth_name_found": auth_name_found,
            "codex_home_exposed": "CODEX_HOME" in tool_env,
            "runtime_home_under_tool_root": any(
                runtime_home == root or runtime_home.is_relative_to(root) for root in tool_roots
            ),
            "source_auth_under_tool_root": any(
                source_auth == root or source_auth.is_relative_to(root) for root in tool_roots
            ),
        }}
        report_path = Path(sys.argv[0]).resolve().parent / "workspace-auth-checks.jsonl"
        with report_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(report, sort_keys=True) + "\\n")
        if any(report.values()):
            raise SystemExit(19)
    counter = Path(sys.argv[0]).resolve().parent / "exec-count.txt"
    count = int(counter.read_text()) + 1 if counter.exists() else 1
    counter.write_text(str(count))
    sys.stdin.read()
    print(json.dumps({{"type": "thread.started", "thread_id": f"thread-{{count}}"}}))
    print(json.dumps({{"type": "item.completed", "item": {{"type": "agent_message", "text": f"answer {{count}}"}}}}))
    print(json.dumps({{"type": "turn.completed", "usage": {{"input_tokens": 3, "output_tokens": 2}}}}))
    raise SystemExit(0)
raise SystemExit(2)
"""
        path.write_text(script, encoding="utf-8")
        path.chmod(0o755)
        return path


if __name__ == "__main__":
    unittest.main()
