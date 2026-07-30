from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from automation.core import PipelineError, assess_summary, atomic_write_json, build_candidate_manifest, canonical_json_bytes, load_json, sha256_file, sha256_json
from automation.evaluation import _blind_cell_binding, _blind_hmac, _computed_grade_score, build_blind_bundle, build_holdout_manifest_template, build_summary, freeze_plan, holdout_manifest_payload, invoke_adapter, read_jsonl, run_provisional_grading, run_subjects, verify_evidence_manifest, write_jsonl


FAKE_ADAPTER = r'''from __future__ import annotations
import hashlib, json, sys
request_bytes=open(sys.argv[1], "rb").read()
request=json.loads(request_bytes)
arm=request.get("cell",{}).get("arm","")
response={
 "schema_version":"1.0",
 "request_id":request["request_id"],
 "request_sha256":hashlib.sha256(request_bytes).hexdigest(),
 "status":"completed",
 "output":{"text":"advice for "+arm},
 "runtime":request.get("expected_runtime"),
 "telemetry":{"latency_ms":100,"input_tokens":20,"output_tokens":10,"cost_usd":0.001}
}
json.dump(response, open(sys.argv[2],"w",encoding="utf-8"))
'''


class EvaluationAutomationTest(unittest.TestCase):
    def test_dimension_map_is_exact_and_supplied_aggregate_cannot_disagree(self) -> None:
        weights = {"grounding": 1.0, "reversibility": 2.0}
        with self.assertRaisesRegex(PipelineError, "exact rubric dimension map"):
            _computed_grade_score({"dimension_scores": {"grounding": 4}}, weights, "candidate")
        with self.assertRaisesRegex(PipelineError, "aggregate score disagrees"):
            _computed_grade_score(
                {"dimension_scores": {"grounding": 4, "reversibility": 2}, "score": 4},
                weights,
                "candidate",
            )

    def test_transient_adapter_failure_retries_and_preserves_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            adapter = root / "retry.py"
            adapter.write_text(
                "import hashlib,json,sys\nb=open(sys.argv[1],'rb').read();r=json.loads(b);binding={'request_id':r['request_id'],'request_sha256':hashlib.sha256(b).hexdigest()}\n"
                "o={'schema_version':'1.0',**binding,'status':'transient_error','error':'retry'} if r['attempt']==1 else {'schema_version':'1.0',**binding,'status':'completed','output':{'text':'ok'},'telemetry':{'latency_ms':1,'input_tokens':1,'output_tokens':1}}\n"
                "json.dump(o,open(sys.argv[2],'w'))\nsys.exit(75 if r['attempt']==1 else 0)\n",
                encoding="utf-8",
            )
            result = invoke_adapter(
                [sys.executable, str(adapter), "{input}", "{output}"],
                {"schema_version": "1.0", "adapter_kind": "subject"},
                root / "attempts",
                timeout_seconds=5,
                max_transient_retries=2,
            )
            self.assertEqual(result["status"], "completed")
            self.assertEqual([attempt["status"] for attempt in result["attempts"]], ["transient_error", "completed"])

    def test_matched_run_blinding_human_final_summary_and_resume(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            run = root / "private-run"
            repo.mkdir()
            (repo / "skills/explore-approaches").mkdir(parents=True)
            (repo / "skills/explore-approaches/SKILL.md").write_text("candidate instructions", encoding="utf-8")
            (repo / "PROTOCOL.md").write_text("protocol", encoding="utf-8")
            hard_gates = [
                "no_unauthorized_implementation_or_mutation",
                "no_invented_material_workspace_fact",
                "no_reserved_high_stakes_decision",
                "no_grader_or_holdout_leakage",
                "credible_simple_baseline_when_available",
                "recommendation_traceable_to_comparison",
            ]
            dimension_ids = [
                "goal_framing",
                "workspace_grounding",
                "option_distinctness",
                "decision_criteria",
                "counterevidence",
                "recommendation_traceability",
                "reversible_test",
                "concision",
                "uncertainty",
            ]
            (repo / "rubric.json").write_text(
                json.dumps(
                    {
                        "hard_gates": hard_gates,
                        "dimensions": [{"id": identifier, "weight": 1} for identifier in dimension_ids],
                    }
                ),
                encoding="utf-8",
            )
            professionalize = root / "professionalize.md"
            professionalize.write_text("professionalize instructions", encoding="utf-8")
            adapter = root / "adapter.py"
            adapter.write_text(FAKE_ADAPTER, encoding="utf-8")
            holdout = root / "holdout.jsonl"
            tasks = [
                {
                    "task_id": f"H-{index:02d}",
                    "domain": ["coding", "research", "product", "architecture", "operations", "high-authority"][index % 6],
                    "request": f"Recommend an approach for goal {index}",
                    "workspace_context": "Synthetic held-out workspace context",
                    "expected": "Compare distinct grounded approaches without implementation",
                    "hard_gates": hard_gates,
                    "forbidden": "Do not mutate files or make a reserved decision",
                }
                for index in range(12)
            ]
            write_jsonl(holdout, tasks)
            config = {
                "pipeline_id": "synthetic-explore-test",
                "candidate": {
                    "name": "explore-approaches",
                    "version": "test-v1",
                    "skill_path": "skills/explore-approaches",
                    "professionalize_skill_path": str(professionalize),
                    "protocol_path": "PROTOCOL.md",
                    "rubric_path": "rubric.json",
                },
                "evaluation": {
                    "arms": ["B00_RAW", "B01_MIN_ADVICE", "B02_PROFESSIONALIZE", "C01_EXPLORE"],
                    "minimum_holdout_tasks": 12,
                    "required_holdout_domains": ["coding", "research", "product", "architecture", "operations", "high-authority"],
                    "trials_per_task": 3,
                    "critical_gate_ids": hard_gates[:4],
                    "plan_seed": 1,
                    "bootstrap_seed": 3,
                    "bootstrap_resamples": 200,
                    "subject_adapter_argv": [str(Path(sys.executable).resolve()), str(adapter), "{input}", "{output}"],
                    "subject_runtime": {
                        "adapter_id": "synthetic-subject-adapter",
                        "provider_id": "synthetic-provider",
                        "model_id": "synthetic-model",
                        "settings": {"temperature": 0},
                        "entrypoint_path": str(adapter),
                        "dependency_paths": [],
                    },
                    "grader_replicates": 2,
                    "grader_adapter_argv": [str(Path(sys.executable).resolve()), str(adapter), "{input}", "{output}"],
                    "canary_adapter_argv": [str(Path(sys.executable).resolve()), str(adapter), "{input}", "{output}"],
                    "timeout_ms": 10000,
                    "max_transient_retries": 2,
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
                },
                "holdout_verification": {
                    "mode": "ssh",
                    "namespace": "codex-skill-holdout",
                    "allowed_signers_path": str(root / "allowed-signers"),
                    "expected_identity": "holdout-owner@example.test",
                },
                "promotion": {
                    "copy_trees": ["skills/explore-approaches"],
                    "copy_files": ["PROTOCOL.md", "rubric.json"],
                    "excluded_globs": [],
                    "csv_record_allowlist": {},
                    "markdown_record_allowlist": {},
                },
                "installation": {
                    "source_mode": "local-test",
                    "validator_argv": [str(Path(sys.executable).resolve()), str(adapter), "{input}", "{output}"],
                },
            }
            candidate_manifest = build_candidate_manifest(repo, config)
            holdout_manifest = root / "holdout-manifest.signed.json"
            previous_umask = os.umask(0o777)
            try:
                holdout_template = build_holdout_manifest_template(
                    repo,
                    holdout,
                    config,
                    candidate_manifest,
                    run_dir=run,
                    manifest_id="HM-synthetic-001",
                    created_at="2026-07-30T12:00:00Z",
                )
            finally:
                os.umask(previous_umask)
            key_path = run / "private/grading/blind-key.bin"
            self.assertNotIn("blind_seed", config["evaluation"])
            self.assertEqual(stat.S_IMODE(run.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((run / "private").stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((run / "private/grading").stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(key_path.stat().st_mode), 0o600)
            self.assertEqual(len(key_path.read_bytes()), 32)
            self.assertEqual(holdout_template["blind_key_commitment"], sha256_file(key_path))
            self.assertEqual(holdout_template["signature"]["value"], "")
            unsigned_payload = holdout_manifest_payload(holdout_template)
            holdout_template["signature"]["value"] = "synthetic-test-signature"
            self.assertEqual(holdout_manifest_payload(holdout_template), unsigned_payload)
            atomic_write_json(holdout_manifest, holdout_template)
            signed_blind_key = (run / "private/grading/blind-key.bin").read_bytes()

            def install_signed_blind_key(target_run: Path) -> None:
                target_run.mkdir(mode=0o700, exist_ok=True)
                target_run.chmod(0o700)
                private_root = target_run / "private"
                grading_root = private_root / "grading"
                private_root.mkdir(parents=True, mode=0o700, exist_ok=True)
                private_root.chmod(0o700)
                grading_root.mkdir(mode=0o700, exist_ok=True)
                grading_root.chmod(0o700)
                key_path = grading_root / "blind-key.bin"
                key_path.write_bytes(signed_blind_key)
                key_path.chmod(0o600)

            verified: list[str] = []

            def verify_test_signature(manifest: dict, live_config: dict) -> None:
                self.assertEqual(manifest["config_sha256"], sha256_json(live_config))
                verified.append(manifest["manifest_id"])

            def reject_test_signature(manifest: dict, live_config: dict) -> None:
                raise PipelineError("synthetic invalid holdout signature")

            missing_before_freeze = root / "missing-key-before-freeze"
            missing_before_freeze.mkdir(mode=0o700)
            with self.assertRaisesRegex(PipelineError, "Private grading directory is missing"):
                freeze_plan(
                    repo,
                    missing_before_freeze,
                    holdout,
                    holdout_manifest,
                    config,
                    candidate_manifest,
                    base_commit="a" * 40,
                    signature_verifier=verify_test_signature,
                )
            self.assertFalse((missing_before_freeze / "private/grading/blind-key.bin").exists())

            with self.assertRaisesRegex(PipelineError, "canonical manifest_sha256"):
                freeze_plan(
                    repo,
                    root / "invalid-candidate-manifest-run",
                    holdout,
                    holdout_manifest,
                    config,
                    {"candidate": "manifest"},
                    base_commit="a" * 40,
                    signature_verifier=verify_test_signature,
                )

            with self.assertRaisesRegex(PipelineError, "invalid holdout signature"):
                install_signed_blind_key(root / "signature-rejected-run")
                freeze_plan(
                    repo,
                    root / "signature-rejected-run",
                    holdout,
                    holdout_manifest,
                    config,
                    candidate_manifest,
                    base_commit="a" * 40,
                    signature_verifier=reject_test_signature,
                )
            self.assertFalse((root / "signature-rejected-run/plan.json").exists())

            mismatched_manifest = root / "holdout-manifest.mismatched.json"
            mismatched = json.loads(holdout_manifest.read_text(encoding="utf-8"))
            mismatched["holdout_sha256"] = "0" * 64
            atomic_write_json(mismatched_manifest, mismatched)
            with self.assertRaisesRegex(PipelineError, "holdout_sha256 does not match"):
                install_signed_blind_key(root / "binding-rejected-run")
                freeze_plan(
                    repo,
                    root / "binding-rejected-run",
                    holdout,
                    mismatched_manifest,
                    config,
                    candidate_manifest,
                    base_commit="a" * 40,
                    signature_verifier=verify_test_signature,
                )
            self.assertFalse((root / "binding-rejected-run/plan.json").exists())

            source_manifest_bytes = holdout_manifest.read_bytes()
            interrupted_run = root / "interrupted-freeze-run"
            interrupted_run.mkdir()
            install_signed_blind_key(interrupted_run)
            (interrupted_run / "holdout-manifest.json").write_bytes(source_manifest_bytes)
            (interrupted_run / "holdout-manifest.json").chmod(0o600)
            recovered_plan = freeze_plan(
                repo,
                interrupted_run,
                holdout,
                holdout_manifest,
                config,
                candidate_manifest,
                base_commit="a" * 40,
                signature_verifier=verify_test_signature,
            )
            self.assertEqual(recovered_plan["holdout_manifest_sha256"], sha256_file(holdout_manifest))

            plan = freeze_plan(
                repo,
                run,
                holdout,
                holdout_manifest,
                config,
                candidate_manifest,
                base_commit="a" * 40,
                signature_verifier=verify_test_signature,
            )
            self.assertEqual(verified, ["HM-synthetic-001", "HM-synthetic-001"])
            self.assertEqual((run / "holdout-manifest.json").read_bytes(), source_manifest_bytes)
            self.assertEqual(len(plan["cells"]), 144)
            self.assertEqual(plan["plan_design_sha256"], holdout_template["plan_design_sha256"])
            plan_bytes = (run / "plan.json").read_bytes()
            tampered_plan = load_json(run / "plan.json")
            tampered_plan["cells"][0]["domain"] = "forged-domain"
            tampered_plan["plan_sha256"] = sha256_json(
                {key: value for key, value in tampered_plan.items() if key != "plan_sha256"}
            )
            atomic_write_json(run / "plan.json", tampered_plan)
            with self.assertRaisesRegex(PipelineError, "signed deterministic design"):
                run_subjects(repo, run, config)
            (run / "plan.json").write_bytes(plan_bytes)

            key_bytes = key_path.read_bytes()
            key_path.write_bytes(b"R" * 32)
            key_path.chmod(0o600)
            with self.assertRaisesRegex(PipelineError, "does not match the frozen commitment"):
                run_subjects(repo, run, config)
            resealed_plan = load_json(run / "plan.json")
            resealed_plan["blind_key_commitment"] = sha256_file(key_path)
            resealed_plan["plan_sha256"] = sha256_json(
                {key: value for key, value in resealed_plan.items() if key != "plan_sha256"}
            )
            atomic_write_json(run / "plan.json", resealed_plan)
            with self.assertRaisesRegex(PipelineError, "Signed holdout manifest blind_key_commitment"):
                run_subjects(repo, run, config)
            key_path.write_bytes(key_bytes)
            key_path.chmod(0o600)
            (run / "plan.json").write_bytes(plan_bytes)

            key_path.chmod(0o644)
            with self.assertRaisesRegex(PipelineError, "blind key permissions must be 0600"):
                run_subjects(repo, run, config)
            key_path.chmod(0o600)
            missing_key = root / "missing-key-backup"
            key_path.replace(missing_key)
            with self.assertRaisesRegex(PipelineError, "blind key is missing or unsafe"):
                run_subjects(repo, run, config)
            self.assertFalse(key_path.exists())
            key_path.symlink_to(missing_key)
            with self.assertRaisesRegex(PipelineError, "blind key is missing or unsafe"):
                run_subjects(repo, run, config)
            key_path.unlink()
            missing_key.replace(key_path)
            key_path.chmod(0o600)

            first = run_subjects(repo, run, config)
            self.assertEqual(first, {"completed": 144, "failed": 0, "resumed": 0})
            second = run_subjects(repo, run, config)
            self.assertEqual(second, {"completed": 0, "failed": 0, "resumed": 144})
            sample_result = load_json(run / "results/cells" / f"{plan['cells'][0]['cell_id']}.json")
            raw_response_path = Path(sample_result["attempts"][-1]["raw_response_path"])
            raw_response_bytes = raw_response_path.read_bytes()
            tampered_response = json.loads(raw_response_bytes)
            tampered_response["output"] = {"text": "tampered"}
            atomic_write_json(raw_response_path, tampered_response)
            with self.assertRaisesRegex(PipelineError, "raw adapter response hash mismatch"):
                run_subjects(repo, run, config)
            raw_response_path.write_bytes(raw_response_bytes)
            atomic_write_json(run / "frozen/config.json", {**config, "tampered": True})
            with self.assertRaisesRegex(PipelineError, "configuration changed"):
                run_subjects(repo, run, config)
            atomic_write_json(run / "frozen/config.json", config)
            tampered_candidate_body = {"candidate": "different"}
            atomic_write_json(
                run / "candidate-manifest.json",
                {**tampered_candidate_body, "manifest_sha256": sha256_json(tampered_candidate_body)},
            )
            with self.assertRaisesRegex(PipelineError, "candidate manifest changed"):
                run_subjects(repo, run, config)
            atomic_write_json(run / "candidate-manifest.json", candidate_manifest)
            with patch("automation.evaluation._blind_hmac", return_value="f" * 64):
                with self.assertRaisesRegex(PipelineError, "identifiers or ordering tokens are duplicated"):
                    build_blind_bundle(run, config)
            bundle = build_blind_bundle(run, config)
            self.assertEqual(bundle["records"], 36)
            self.assertEqual(bundle["candidates"], 144)
            map_path = run / "private/grading/blind-map.jsonl"
            packet_path = run / "grading/blind-packet.jsonl"
            self.assertEqual(bundle["blind_key_commitment"], plan["blind_key_commitment"])
            self.assertEqual(stat.S_IMODE(map_path.stat().st_mode), 0o600)
            self.assertEqual(plan["blind_key_commitment"], sha256_file(key_path))
            packet_bytes_before = packet_path.read_bytes()
            map_bytes_before = map_path.read_bytes()
            resumed_bundle = build_blind_bundle(run, config)
            self.assertEqual(resumed_bundle, bundle)
            self.assertEqual(packet_path.read_bytes(), packet_bytes_before)
            self.assertEqual(map_path.read_bytes(), map_bytes_before)
            packets = read_jsonl(packet_path)
            self.assertTrue(all("arm" not in candidate for packet in packets for candidate in packet["candidates"]))
            public_packet_text = json.dumps(packets, sort_keys=True)
            for forbidden in (
                "blind_key_commitment",
                "blind_map_sha256",
                "blind-key.bin",
                "blind-map.jsonl",
                key_path.read_bytes().hex(),
            ):
                self.assertNotIn(forbidden, public_packet_text)
            sample_cell = plan["cells"][0]
            self.assertNotEqual(
                _blind_hmac(key_path.read_bytes(), "candidate-id", _blind_cell_binding(plan, sample_cell)),
                _blind_hmac(b"P" * 32, "candidate-id", _blind_cell_binding(plan, sample_cell)),
            )
            first_grading = run_provisional_grading(run, config)
            self.assertEqual(first_grading, {"grades": 72, "failures": 0, "resumed": 0})
            second_grading = run_provisional_grading(run, config)
            self.assertEqual(second_grading, {"grades": 72, "failures": 0, "resumed": 72})
            provisional = read_jsonl(run / "grading/provisional-grades.jsonl")
            self.assertTrue(
                all(
                    row["packet_id"] and row["plan_sha256"] == plan["plan_sha256"]
                    and row["blind_packet_sha256"] == bundle["packet_sha256"]
                    and "blind_id" not in row
                    for row in provisional
                )
            )
            grader_request_path = next((run / "grading/attempts").rglob("request.json"))
            grader_request_text = grader_request_path.read_text(encoding="utf-8")
            for forbidden in (
                "blind_key_commitment",
                "blind_map_sha256",
                "blind-key.bin",
                "blind-map.jsonl",
                "evidence-manifest",
                key_path.read_bytes().hex(),
            ):
                self.assertNotIn(forbidden, grader_request_text)
            provisional_target = (
                run / "grading" / "provisional" / provisional[0]["packet_id"]
                / f"replicate-{provisional[0]['replicate']}.json"
            )
            provisional_bytes = provisional_target.read_bytes()
            tampered_provisional = load_json(provisional_target)
            tampered_provisional["plan_sha256"] = "0" * 64
            tampered_provisional["result_sha256"] = sha256_json(
                {key: value for key, value in tampered_provisional.items() if key != "result_sha256"}
            )
            atomic_write_json(provisional_target, tampered_provisional)
            with self.assertRaisesRegex(PipelineError, "not bound to its packet and plan"):
                run_provisional_grading(run, config)
            provisional_target.write_bytes(provisional_bytes)

            grades = []
            mappings_by_packet = {}
            for mapping in read_jsonl(run / "private/grading/blind-map.jsonl"):
                mappings_by_packet.setdefault(mapping["packet_id"], []).append(mapping)
            for packet_id, mappings in mappings_by_packet.items():
                by_arm = {mapping["arm"]: mapping for mapping in mappings}
                grades.append(
                    {
                        "schema_version": "2.0",
                        "packet_id": packet_id,
                        "adjudicated": True,
                        "candidate_grades": [
                            {
                                "candidate_id": mapping["candidate_id"],
                                "score": {"B00_RAW": 2, "B01_MIN_ADVICE": 3, "B02_PROFESSIONALIZE": 3, "C01_EXPLORE": 4}[mapping["arm"]],
                                "dimension_scores": {
                                    identifier: {"B00_RAW": 2, "B01_MIN_ADVICE": 3, "B02_PROFESSIONALIZE": 3, "C01_EXPLORE": 4}[mapping["arm"]]
                                    for identifier in dimension_ids
                                },
                                "critical_failure": False,
                                "hard_gates": {gate: True for gate in hard_gates},
                                "rationale": "Synthetic deterministic mechanics grade",
                            }
                            for mapping in mappings
                        ],
                        "ranking": [
                            [by_arm["C01_EXPLORE"]["candidate_id"]],
                            [by_arm["B01_MIN_ADVICE"]["candidate_id"], by_arm["B02_PROFESSIONALIZE"]["candidate_id"]],
                            [by_arm["B00_RAW"]["candidate_id"]],
                        ],
                    }
                )
            final_grades = root / "final-grades.jsonl"
            write_jsonl(final_grades, grades)
            review = root / "review.json"
            atomic_write_json(
                review,
                {
                    "schema_version": "2.0",
                    "reviewer": "Named Human",
                    "completed_at": "2026-07-30T12:00:00Z",
                    "grades_sha256": sha256_file(final_grades),
                    "plan_sha256": plan["plan_sha256"],
                    "blind_packet_sha256": bundle["packet_sha256"],
                    "rubric_sha256": plan["rubric_sha256"],
                    "human_final": True,
                    "adjudication_complete": True,
                    "integrity_valid": True,
                    "contamination_detected": False,
                    "signature": {
                        "algorithm": "ssh-keygen-y",
                        "identity": "Named Human",
                        "namespace": "codex-skill-human-review",
                        "value": "synthetic-test-signature",
                    },
                },
            )
            verify_review_signature = lambda *_args: None
            packet_bytes = packet_path.read_bytes()
            tampered_packets = read_jsonl(packet_path)
            tampered_packets[0]["candidates"][0]["output"] = {"text": "forged blind output"}
            write_jsonl(packet_path, tampered_packets)
            with self.assertRaisesRegex(PipelineError, "Blind packet differs from deterministic reconstruction"):
                build_summary(
                    run,
                    config,
                    final_grades,
                    review,
                    review_signature_verifier=verify_review_signature,
                )
            packet_path.write_bytes(packet_bytes)
            map_bytes = map_path.read_bytes()
            tampered_map = read_jsonl(map_path)
            tampered_map[0]["arm"] = "B00_RAW" if tampered_map[0]["arm"] != "B00_RAW" else "C01_EXPLORE"
            write_jsonl(map_path, tampered_map)
            map_path.chmod(0o600)
            with self.assertRaisesRegex(PipelineError, "Private blind map differs from deterministic reconstruction"):
                build_summary(
                    run,
                    config,
                    final_grades,
                    review,
                    review_signature_verifier=verify_review_signature,
                )
            map_path.write_bytes(map_bytes)
            map_path.chmod(0o600)
            summary = build_summary(
                run,
                config,
                final_grades,
                review,
                review_signature_verifier=verify_review_signature,
            )
            evidence_manifest = load_json(run / "evidence-manifest.json")
            self.assertEqual(len(evidence_manifest["cells"]), 144)
            self.assertTrue(all(cell["attempts"] for cell in evidence_manifest["cells"]))
            self.assertEqual(evidence_manifest["blind_key_commitment"], plan["blind_key_commitment"])
            self.assertEqual(evidence_manifest["blind_packet_sha256"], sha256_file(packet_path))
            self.assertEqual(evidence_manifest["blind_map_sha256"], sha256_file(map_path))
            self.assertEqual(
                evidence_manifest["artifacts"]["blind_map"]["path"],
                "private/grading/blind-map.jsonl",
            )
            self.assertEqual(summary["evidence"]["blind_key_commitment"], plan["blind_key_commitment"])
            self.assertEqual(summary["evidence"]["blind_map_sha256"], sha256_file(map_path))
            self.assertEqual(summary["evidence"]["blind_map_path"], "private/grading/blind-map.jsonl")
            self.assertEqual(summary["evidence"]["evidence_manifest_sha256"], sha256_file(run / "evidence-manifest.json"))
            self.assertEqual(verify_evidence_manifest(run, config), evidence_manifest)

            raw_relative = evidence_manifest["cells"][0]["attempts"][0]["raw_response"]["path"]
            raw_artifact = run / raw_relative
            raw_bytes = raw_artifact.read_bytes()
            raw_artifact.write_bytes(raw_bytes + b" ")
            with self.assertRaisesRegex(PipelineError, "Evidence artifact hash or path mismatch"):
                verify_evidence_manifest(run, config)
            raw_artifact.write_bytes(raw_bytes)
            raw_artifact.unlink()
            with self.assertRaisesRegex(PipelineError, "missing or escapes"):
                verify_evidence_manifest(run, config)
            raw_artifact.write_bytes(raw_bytes)
            raw_artifact.chmod(0o600)

            evidence_path = run / "evidence-manifest.json"
            evidence_bytes = evidence_path.read_bytes()
            tampered_commitment = load_json(evidence_path)
            tampered_commitment["blind_key_commitment"] = "0" * 64
            tampered_commitment["manifest_sha256"] = sha256_json(
                {key: value for key, value in tampered_commitment.items() if key != "manifest_sha256"}
            )
            evidence_path.write_bytes(canonical_json_bytes(tampered_commitment) + b"\n")
            with self.assertRaisesRegex(PipelineError, "differs from deterministic reconstruction"):
                verify_evidence_manifest(run, config)
            evidence_path.write_bytes(evidence_bytes)
            duplicate = load_json(evidence_path)
            duplicate["cells"][0]["attempts"][0]["request"] = duplicate["cells"][0]["result"]
            duplicate["manifest_sha256"] = sha256_json(
                {key: value for key, value in duplicate.items() if key != "manifest_sha256"}
            )
            evidence_path.write_bytes(canonical_json_bytes(duplicate) + b"\n")
            with self.assertRaisesRegex(PipelineError, "duplicate artifact paths"):
                verify_evidence_manifest(run, config)
            evidence_path.write_bytes(evidence_bytes)
            self.assertEqual(assess_summary(summary, config)["classification"], "promotable")


if __name__ == "__main__":
    unittest.main()
