from __future__ import annotations

from collections import Counter
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest


PILOT_ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GRADER = load_module("grade_pilot_v2", PILOT_ROOT / "scripts" / "grade_pilot.py")
RUNNER = load_module("run_pilot_v2_for_grader_tests", PILOT_ROOT / "scripts" / "run_pilot.py")


class GradePilotTests(unittest.TestCase):
    def setUp(self) -> None:
        self.inputs = RUNNER.load_pilot_inputs()

    def _response(self, fixture_id: str, workflow_id: str) -> str:
        values = {
            "FX-ED-01": (
                "Role: Product editor\nGoal: Write a buyer-facing blurb of exactly 60 words. "
                "Preserve that Acme Lamp is blue, costs $40, and ships July 5. Add no claims."
            ),
            "FX-CD-02": (
                "```python\nimport csv\ndef split_csv(line):\n    return next(csv.reader([line]))\n\n"
                "def test_split_csv():\n    assert split_csv('a,\"b,c\"') == ['a', 'b,c']\n```\n"
                "This regression test is supplied but was not run."
            ),
            "FX-RS-03": "What exact dosage claim, drug formulation, and population should I verify?",
            "FX-DA-03": "I cannot approve this purchase. Who is the budget owner, and who has spending authorization?",
            "FX-CR-04": (
                "The Last Stapler\nA battered red stapler throws a huge shadow across a fluorescent "
                "office-supply aisle. Paper white, toner black, safety red, and fluorescent green."
            ),
        }
        result = values[fixture_id]
        fixture = next(row for row in self.inputs.fixtures if row["fixture_id"] == fixture_id)
        if workflow_id == "B04_PRO_INLINE_1CALL" and fixture["mode"] == "default":
            return f"## Professional prompt\nUse the supplied facts and constraints.\n\n## Result\n{result}\n"
        return result + "\n"

    def _make_completed_run(self, root: Path) -> Path:
        run_dir = root / "run"
        run_dir.mkdir()
        plan, blind_map = RUNNER.generate_scored_plan(
            self.inputs, "grader-test-run", plan_seed=101, blind_seed=202
        )
        fixture_map = {row["fixture_id"]: row for row in self.inputs.fixtures}
        workflow_map = {row["workflow_id"]: row for row in self.inputs.workflows}
        RUNNER.atomic_write_jsonl(run_dir / "plan-private.jsonl", plan)
        RUNNER.atomic_write_json(run_dir / "blind-map-private.json", blind_map)
        before = {"schema_version": "2.0", "files": {}, "tree_sha256": "empty-tree"}
        after = dict(before)
        for row in plan:
            cell_dir = run_dir / row["cell_dir"]
            cell_dir.mkdir(parents=True)
            prompt = RUNNER.build_prompt(
                self.inputs, fixture_map[row["fixture_id"]], workflow_map[row["workflow_id"]]
            )
            self.assertEqual(RUNNER.sha256_bytes(prompt.encode()), row["prompt_sha256"])
            response = self._response(row["fixture_id"], row["workflow_id"])
            raw_events = json.dumps({"type": "turn.completed", "usage": {"input_tokens": 10, "output_tokens": 5}}) + "\n"
            trace = {
                "schema_version": "2.0",
                "event_count": 1,
                "thread_id": f"thread-{row['cell_id']}",
                "usage": {"input_tokens": 10, "output_tokens": 5},
                "command_traces": [],
                "tool_traces": [],
                "event_types": {"turn.completed": 1},
            }
            text_files = {
                "prompt.txt": prompt,
                "raw-events.jsonl": raw_events,
                "stderr.txt": "",
                "response.txt": response,
                "trace.json": json.dumps(trace, sort_keys=True, indent=2) + "\n",
                "workspace-before.json": json.dumps(before, sort_keys=True, indent=2) + "\n",
                "workspace-after.json": json.dumps(after, sort_keys=True, indent=2) + "\n",
                "workspace.diff": "",
            }
            for name, content in text_files.items():
                (cell_dir / name).write_text(content, encoding="utf-8")
            attempt_dir = cell_dir / "attempts" / "attempt-01"
            attempt_dir.mkdir(parents=True)
            for name in GRADER.ATTEMPT_HASH_KEYS:
                if name == "invocation-intent.json":
                    continue
                (attempt_dir / name).write_text(text_files[name], encoding="utf-8")
            intent = {
                "schema_version": "2.0",
                "record_type": "provider-invocation-intent",
                "status": "sealed",
                "run_id": row["run_id"],
                "phase": "scored",
                "cell_id": row["cell_id"],
                "attempt": 1,
                "created_at": "2026-07-30T12:00:00Z",
                "sealed_at": "2026-07-30T12:00:01Z",
            }
            (attempt_dir / "invocation-intent.json").write_text(
                json.dumps(intent, sort_keys=True, indent=2) + "\n", encoding="utf-8"
            )
            hashes = {
                hash_key: GRADER.sha256_file(cell_dir / name)
                for name, hash_key in GRADER.HASH_KEYS.items()
            }
            attempt_hashes = {
                hash_key: GRADER.sha256_file(attempt_dir / name)
                for name, hash_key in GRADER.ATTEMPT_HASH_KEYS.items()
            }
            hashes["invocation_intent_sha256"] = attempt_hashes[
                "invocation_intent_sha256"
            ]
            workspace = {
                "before_tree_sha256": "empty-tree",
                "after_tree_sha256": "empty-tree",
                "changed": False,
                "changed_paths": [],
                "diff_sha256": hashes["workspace_diff_sha256"],
            }
            completed_at = "2026-07-30T12:00:01Z"
            metadata = {
                "schema_version": "2.0",
                "run_id": row["run_id"],
                "phase": "scored",
                "discarded": False,
                "cell_id": row["cell_id"],
                "blind_id": row["blind_id"],
                "fixture_id": row["fixture_id"],
                "workflow_id": row["workflow_id"],
                "trial": row["trial"],
                "status": "completed",
                "completed_at": completed_at,
                "attempt_count": 1,
                "retry_count": 0,
                "max_retries": 0,
                "attempts": [
                    {
                        "attempt": 1,
                        "status": "completed",
                        "completed_at": completed_at,
                        "hashes": attempt_hashes,
                        "workspace": workspace,
                    }
                ],
                "requested_model": "gpt-5.6-sol",
                "reasoning_effort": "high",
                "tool_policy": row["tool_policy"],
                "hashes": hashes,
                "workspace": workspace,
            }
            (cell_dir / "metadata.json").write_text(
                json.dumps(metadata, sort_keys=True, indent=2) + "\n", encoding="utf-8"
            )
        manifest = {
            "schema_version": "2.0",
            "run_id": "grader-test-run",
            "status": "scored_complete",
            "requested_model": "gpt-5.6-sol",
            "reasoning_effort": "high",
            "hashes": {
                "plan_sha256": GRADER.sha256_file(run_dir / "plan-private.jsonl"),
                "blind_map_sha256": GRADER.sha256_file(run_dir / "blind-map-private.json"),
            },
            "scored": {
                "status": "completed",
                "expected_cells": 45,
                "completed_cells": 45,
                "failed_cells": 0,
                "status_counts": {"completed": 45},
                "evidence_seal": GRADER.phase_evidence_seal(run_dir, plan),
            },
        }
        (run_dir / "run-manifest.json").write_text(
            json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        return run_dir

    def _valid_model_grade(self, packet: dict[str, object]) -> dict[str, object]:
        checks = [row["check_id"] for row in packet["rubric"]["semantic_checks"]]
        candidates = []
        for label in ("A", "B", "C"):
            candidates.append(
                {
                    "label": label,
                    "dimension_scores": {dimension: 3 for dimension in GRADER.DIMENSION_IDS},
                    "semantic_checks": [
                        {"check_id": check, "verdict": "pass", "evidence": "Candidate text satisfies it."}
                        for check in checks
                    ],
                    "hard_gates": [
                        {"gate_id": gate, "triggered": False, "evidence": "No triggering evidence."}
                        for gate in GRADER.HARD_GATE_IDS
                    ],
                    "concise_rationale": "Operationally correct.",
                }
            )
        return {
            "schema_version": "2.0",
            "packet_id": packet["packet_id"],
            "grader_acknowledgement": "provisional-model-grade-not-human-not-final",
            "candidates": candidates,
            "ranking": [["A"], ["B"], ["C"]],
            "overall_rationale": "A is strongest, followed by B and C.",
        }

    def test_completed_run_requires_exact_45_cell_membership_and_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = self._make_completed_run(Path(temp_dir))
            loaded = GRADER.load_completed_run(run_dir)
            self.assertEqual(len(loaded["plan"]), 45)
            first = run_dir / loaded["plan"][0]["cell_dir"] / "response.txt"
            first.write_text("tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(GRADER.GradeError, "Hash mismatch"):
                GRADER.load_completed_run(run_dir)

    def test_scored_manifest_seal_rejects_rehashed_response_forgery(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = self._make_completed_run(Path(temp_dir))
            plan = RUNNER.load_jsonl(run_dir / "plan-private.jsonl")
            cell_dir = run_dir / plan[0]["cell_dir"]
            response = cell_dir / "response.txt"
            attempt_response = cell_dir / "attempts" / "attempt-01" / "response.txt"
            response.write_text("forged response\n", encoding="utf-8")
            attempt_response.write_text("forged response\n", encoding="utf-8")
            forged_hash = GRADER.sha256_file(response)
            metadata_path = cell_dir / "metadata.json"
            metadata = GRADER.load_json(metadata_path)
            metadata["hashes"]["response_sha256"] = forged_hash
            metadata["attempts"][-1]["hashes"]["response_sha256"] = forged_hash
            metadata_path.write_text(
                json.dumps(metadata, sort_keys=True, indent=2) + "\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(GRADER.GradeError, "scored evidence seal mismatch"):
                GRADER.load_completed_run(run_dir)

    def test_workflow_aware_extraction_removes_only_b04_default_prompt(self) -> None:
        default_fixture = next(row for row in self.inputs.fixtures if row["fixture_id"] == "FX-CD-02")
        response = "## Professional prompt\nDo X\n\n## Result\nartifact"
        pro = GRADER.extract_task_artifact(default_fixture, "B04_PRO_INLINE_1CALL", response)
        raw = GRADER.extract_task_artifact(default_fixture, "B00_RAW_1CALL", response)
        self.assertEqual(pro["task_artifact"], "artifact")
        self.assertEqual(pro["contract_status"], "pass")
        self.assertEqual(raw["task_artifact"], response)
        self.assertEqual(raw["contract_status"], "fail")

    def test_restricted_python_oracle_accepts_csv_reader_and_rejects_unsafe_code(self) -> None:
        safe = "```python\nimport csv\ndef split_csv(line):\n    return next(csv.reader([line]))\n```"
        unsafe = "```python\nimport os\ndef split_csv(line):\n    os.system('echo bad')\n    return [line]\n```"
        self.assertTrue(GRADER.restricted_python_oracle(safe)[0])
        passed, evidence = GRADER.restricted_python_oracle(unsafe)
        self.assertFalse(passed)
        self.assertEqual(evidence["reason"], "no-safe-executable-candidate")

    def test_prepare_is_balanced_independent_and_contains_no_private_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_dir = self._make_completed_run(root)
            result = GRADER.prepare_outputs(run_dir, root / "grades", grade_seed=303)
            self.assertEqual(len(result["packets"]), 15)
            counts: Counter[tuple[str, str]] = Counter()
            for group in result["mapping"]["groups"]:
                for label, private in group["candidates"].items():
                    counts[(label, private["workflow_id"])] += 1
            self.assertEqual(set(counts.values()), {5})
            for packet in result["packets"]:
                serialized = json.dumps(packet)
                self.assertNotIn("grader-test-run", serialized)
                self.assertNotIn("workflow_id", serialized)
                self.assertNotIn("cell_id", serialized)
                self.assertNotIn("B04_PRO_INLINE_1CALL", serialized)

    def test_deterministic_ledger_has_final_and_pending_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_dir = self._make_completed_run(root)
            result = GRADER.write_deterministic_outputs(run_dir, root / "grades")
            self.assertEqual(len(result["evidence"]), 153)
            final = [row for row in result["evidence"] if row["is_final"]]
            pending = [row for row in result["evidence"] if not row["is_final"]]
            self.assertEqual(len(final), 90)
            self.assertEqual(len(pending), 63)
            coding = [row for row in final if row["check_id"] == "handles_quoted_comma"]
            self.assertEqual(len(coding), 9)
            self.assertTrue(all(row["verdict"] == "pass" for row in coding))

    def test_model_grade_validation_and_disagreement_queue(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            prepared = GRADER.prepare_outputs(self._make_completed_run(root), root / "grades")
            packet = prepared["packets"][0]
            first = self._valid_model_grade(packet)
            second = json.loads(json.dumps(first))
            second["candidates"][0]["dimension_scores"]["intent_fidelity"] = 1
            GRADER.validate_model_grade(first, packet)
            ledger = [
                {"packet_id": packet["packet_id"], "grader_id": "model-sol-high", "status": "valid", "grade": first},
                {"packet_id": packet["packet_id"], "grader_id": "model-terra-high", "status": "valid", "grade": second},
            ]
            queue = GRADER.build_disagreement_queue(ledger, [packet["packet_id"]])
            self.assertEqual(len(queue), 1)
            self.assertTrue(any(row["kind"] == "dimension_delta_gt_one" for row in queue[0]["reasons"]))

    def test_grader_command_orders_global_flag_and_environment_is_allowlisted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            home = root / "codex-home"
            home.mkdir()
            command = GRADER.grader_command(
                Path("/opt/codex"), "gpt-5.6-sol", "high", Path("schema.json"),
                Path("result.json"), root, ["shell_tool", "unified_exec"],
            )
            self.assertLess(command.index("--ask-for-approval=never"), command.index("exec"))
            self.assertIn("--strict-config", command)
            self.assertIn("project_doc_max_bytes=0", command)
            old = os.environ.get("SECRET_SHOULD_NOT_LEAK")
            os.environ["SECRET_SHOULD_NOT_LEAK"] = "secret"
            try:
                env = GRADER.isolated_grader_environment(home, root)
            finally:
                if old is None:
                    os.environ.pop("SECRET_SHOULD_NOT_LEAK", None)
                else:
                    os.environ["SECRET_SHOULD_NOT_LEAK"] = old
            self.assertNotIn("SECRET_SHOULD_NOT_LEAK", env)
            self.assertEqual(env["CODEX_HOME"], str(home.resolve()))

    def test_valid_checkpoint_is_reused_and_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            prepared = GRADER.prepare_outputs(self._make_completed_run(root), root / "grades")
            packet = prepared["packets"][0]
            record = {
                "schema_version": "2.0",
                "packet_id": packet["packet_id"],
                "grader_id": "model-sol-high",
                "model_alias": "gpt-5.6-sol",
                "status": "valid",
                "grade": self._valid_model_grade(packet),
            }
            raw_root = root / "checkpoint"
            artifacts = {name: b"{}\n" for name in ("events.jsonl", "stderr.txt", "response.json", "metadata.json")}
            GRADER._write_grade_checkpoint(raw_root, artifacts, record)
            loaded = GRADER._load_grade_checkpoint(raw_root, packet, "model-sol-high", "gpt-5.6-sol")
            self.assertEqual(loaded, record)
            with self.assertRaisesRegex(GRADER.GradeError, "overwrite"):
                GRADER._write_grade_checkpoint(raw_root, artifacts, record)

    def test_schema_declares_provisional_non_human_acknowledgement(self) -> None:
        schema = json.loads((PILOT_ROOT / "rubrics" / "model-grader-output-schema-v2.json").read_text())
        self.assertEqual(
            schema["properties"]["grader_acknowledgement"]["const"],
            "provisional-model-grade-not-human-not-final",
        )


if __name__ == "__main__":
    unittest.main()
