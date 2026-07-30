from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[4] / "skills" / "review-skill-candidate" / "scripts" / "review_bundle.py"
SPEC = importlib.util.spec_from_file_location("review_bundle", SCRIPT)
assert SPEC and SPEC.loader
REVIEW = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REVIEW)


class ReviewBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self._git("init", "-b", "main")
        self._git("config", "user.email", "test@example.invalid")
        self._git("config", "user.name", "Test Reviewer")
        self._write("policy.md", "# Policy\n\nHuman decides merge.\n")
        self._write("app.py", "VALUE = 1\n")
        self._git("add", ".")
        self._git("commit", "-m", "base")
        self.base = self._git("rev-parse", "HEAD").strip()
        self._write("app.py", "VALUE = 2\nSAFE = True\n")
        self._write("skill.md", "# Candidate\n\nBehavioral efficacy is unknown.\n")
        self._git("add", ".")
        self._git("commit", "-m", "candidate")
        self.head = self._git("rev-parse", "HEAD").strip()
        self.bundle = self.root / "bundle"
        self._init_bundle()

    def _git(self, *args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=self.repo, text=True)

    def _write(self, relative: str, text: str) -> None:
        path = self.repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _init_bundle(self) -> None:
        result = REVIEW.main([
            "init", "--repo-root", str(self.repo), "--repository", "example/repo",
            "--base", self.base, "--head", self.head, "--pr-number", "1",
            "--decision-owner", "Example Human", "--requested-by", "test",
            "--output", str(self.bundle), "--review-id", "TEST-001",
            "--built-at", "2026-07-30T00:00:00Z", "--policy", "policy.md",
            "--validation", "unit test baseline passed",
        ])
        self.assertEqual(result, 0)

    def _manifest(self) -> dict:
        return json.loads((self.bundle / "manifest.json").read_text())

    def _submission(self, role: str, reviewer_id: str, findings: list[dict] | None = None) -> dict:
        manifest = self._manifest()
        return {
            "schema_version": "1.0",
            "review_id": manifest["review_id"],
            "target": manifest["target"],
            "reviewer": {
                "role": role, "reviewer_id": reviewer_id, "surface": "test",
                "model": None, "reviewed_at": "2026-07-30T00:01:00Z",
                "independent_context": True,
            },
            "scope": {
                "reviewed_files": ["app.py", "skill.md"], "not_reviewed": [],
                "concerns_checked": ["correctness", "authority"],
            },
            "verdict": "pass" if not findings else "changes_required",
            "findings": findings or [],
            "limitations": [],
        }

    def _finding(self) -> dict:
        return {
            "finding_id": "EM-001", "severity": "P1", "status": "open",
            "title": "Claim exceeds evidence", "claim": "The candidate claims an unmeasured result.",
            "impact": "The merge record would be misleading.",
            "evidence": [{"path": "skill.md", "line_start": 3, "line_end": 3}],
            "recommendation": "Narrow the claim.", "counterevidence": "No held-out result exists.",
            "confidence": "high",
        }

    def _packet_schemas(self) -> dict[str, dict]:
        errors: list[str] = []
        verified_files = REVIEW.validate_packet_index(self.bundle, errors)
        self.assertEqual(errors, [])
        self.assertIsNotNone(verified_files)
        return REVIEW.load_packet_schemas(verified_files)

    def _schema_errors(self, value: object) -> list[str]:
        role = "evidence-methodology"
        path = self.bundle / "submissions" / f"{role}.json"
        REVIEW.write_json(path, value)
        errors: list[str] = []
        submission, findings = REVIEW.validate_submission(
            self.repo, path, role, self._manifest(),
            self._packet_schemas()["review_submission"], errors,
        )
        self.assertIsNone(submission)
        self.assertEqual(findings, [])
        self.assertTrue(errors)
        return errors

    def _assert_schema_error(self, value: object, *fragments: str) -> None:
        message = "\n".join(self._schema_errors(value))
        self.assertIn("submission schema", message)
        for fragment in fragments:
            self.assertIn(fragment, message)

    def _write_reviews(self, shared_id: bool = False, finding: dict | None = None) -> None:
        for index, role in enumerate(REVIEW.REQUIRED_ROLES, 1):
            findings = [finding] if finding and role == "evidence-methodology" else []
            reviewer = "same" if shared_id else f"reviewer-{index}"
            REVIEW.write_json(self.bundle / "submissions" / f"{role}.json", self._submission(role, reviewer, findings))

    def _adjudication(
        self,
        dispositions: list[dict] | None = None,
        gate: str = "eligible_for_human_decision",
    ) -> dict:
        manifest = self._manifest()
        hashes = {
            role: REVIEW.sha256_file(self.bundle / "submissions" / f"{role}.json")
            for role in REVIEW.REQUIRED_ROLES
        }
        return {
            "schema_version": "1.0", "review_id": manifest["review_id"],
            "target": manifest["target"],
            "adjudicator": {
                "adjudicator_id": "adjudicator-1", "surface": "test", "model": None,
                "adjudicated_at": "2026-07-30T00:02:00Z", "independent_from_authors": True,
            },
            "submission_hashes": hashes, "finding_dispositions": dispositions or [],
            "conflicts": [], "merge_gate": gate, "rationale": "Evidence checked.",
            "limitations": [],
        }

    def _write_adjudication(
        self,
        dispositions: list[dict] | None = None,
        gate: str = "eligible_for_human_decision",
        value: dict | None = None,
    ) -> None:
        REVIEW.write_json(
            self.bundle / "adjudication" / "adjudication.json",
            value if value is not None else self._adjudication(dispositions, gate),
        )

    def _human_decision(self) -> dict:
        manifest = self._manifest()
        return {
            "schema_version": "1.0", "review_id": manifest["review_id"],
            "target": manifest["target"], "decision_owner": manifest["decision_owner"],
            "actor_type": "human", "decision": "approved",
            "decided_at": "2026-07-30T00:03:00Z", "rationale": "Exact target reviewed.",
            "conditions": [], "dissent": [],
            "reversal_evidence": ["Target or evidence changes."],
            "authorized_actions": ["Merge the exact reviewed target."],
            "forbidden_actions": ["Promote or install the skill."],
        }

    def _validate(self, write: bool = False) -> dict:
        return REVIEW.validate_bundle(argparse.Namespace(
            repo_root=str(self.repo), bundle=str(self.bundle), write_summary=write
        ))

    def test_init_freezes_target_and_creates_role_packets(self) -> None:
        manifest = self._manifest()
        self.assertEqual(manifest["target"]["base_sha"], self.base)
        self.assertEqual(manifest["target"]["head_sha"], self.head)
        self.assertEqual(manifest["required_roles"], list(REVIEW.REQUIRED_ROLES))
        for role in REVIEW.REQUIRED_ROLES:
            self.assertTrue((self.bundle / "assignments" / f"{role}.md").is_file())
        self.assertTrue((self.bundle / "packet-index.json").is_file())

    def test_init_refuses_to_overwrite_preserved_bundle(self) -> None:
        with self.assertRaises(REVIEW.ReviewError):
            REVIEW.init_bundle(argparse.Namespace(
                repo_root=str(self.repo), repository="example/repo", base=self.base,
                head=self.head, pr_number=1, decision_owner="Example Human",
                requested_by="test", output=str(self.bundle), review_id="TEST-002",
                built_at="2026-07-30T00:00:00Z", policy=[], artifact=[], validation=[],
            ))

    def test_submission_schema_rejects_missing_and_additional_properties(self) -> None:
        base = self._submission("evidence-methodology", "reviewer-1", [self._finding()])
        cases: list[tuple[str, dict, tuple[str, ...]]] = []

        value = json.loads(json.dumps(base))
        value.pop("limitations")
        cases.append(("missing root", value, ("$:", "missing required property 'limitations'")))

        value = json.loads(json.dumps(base))
        value["findings"][0]["evidence"][0].pop("line_end")
        cases.append((
            "missing nested evidence",
            value,
            ("$.findings[0].evidence[0]", "missing required property 'line_end'"),
        ))

        for label, container in (
            ("root", None),
            ("reviewer", "reviewer"),
            ("finding", "finding"),
            ("evidence", "evidence"),
        ):
            value = json.loads(json.dumps(base))
            if container is None:
                target = value
            elif container == "finding":
                target = value["findings"][0]
            elif container == "evidence":
                target = value["findings"][0]["evidence"][0]
            else:
                target = value[container]
            target["unexpected"] = "not allowed"
            cases.append((
                f"additional {label}",
                value,
                ("additional property 'unexpected' is not allowed",),
            ))

        for label, value, fragments in cases:
            with self.subTest(label=label):
                self._assert_schema_error(value, *fragments)

    def test_submission_schema_rejects_types_lengths_and_nested_contracts(self) -> None:
        base = self._submission("evidence-methodology", "reviewer-1", [self._finding()])
        cases: list[tuple[str, dict, tuple[str, ...]]] = []
        mutations = (
            ("findings object", ("findings",), {}, ("$.findings", "expected type array")),
            ("model number", ("reviewer", "model"), 7, ("$.reviewer.model", "string or null")),
            ("not reviewed item", ("scope", "not_reviewed"), [7], ("$.scope.not_reviewed[0]", "string")),
            ("empty title", ("findings", 0, "title"), "", ("$.findings[0].title", "length")),
            ("boolean line", ("findings", 0, "evidence", 0, "line_start"), True, ("line_start", "integer")),
            ("empty evidence", ("findings", 0, "evidence"), [], ("$.findings[0].evidence", "at least 1")),
            ("null limitation", ("limitations",), [None], ("$.limitations[0]", "string")),
        )
        for label, path, replacement, fragments in mutations:
            value = json.loads(json.dumps(base))
            target: object = value
            for key in path[:-1]:
                target = target[key]  # type: ignore[index]
            target[path[-1]] = replacement  # type: ignore[index]
            cases.append((label, value, fragments))
        for label, value, fragments in cases:
            with self.subTest(label=label):
                self._assert_schema_error(value, *fragments)

    def test_submission_schema_rejects_patterns_and_minimums(self) -> None:
        base = self._submission("evidence-methodology", "reviewer-1", [self._finding()])
        mutations = (
            ("base sha", ("target", "base_sha"), "A" * 40, "$.target.base_sha"),
            ("diff sha", ("target", "diff_sha256"), "a" * 63, "$.target.diff_sha256"),
            ("finding id", ("findings", 0, "finding_id"), "em-1", "$.findings[0].finding_id"),
            ("line minimum", ("findings", 0, "evidence", 0, "line_start"), 0, "line_start"),
        )
        for label, path, replacement, expected_path in mutations:
            value = json.loads(json.dumps(base))
            target: object = value
            for key in path[:-1]:
                target = target[key]  # type: ignore[index]
            target[path[-1]] = replacement  # type: ignore[index]
            with self.subTest(label=label):
                self._assert_schema_error(value, expected_path)

    def test_submission_schema_rejects_duplicate_unique_scope_items(self) -> None:
        base = self._submission("evidence-methodology", "reviewer-1")
        for field in ("reviewed_files", "concerns_checked"):
            value = json.loads(json.dumps(base))
            value["scope"][field].append(value["scope"][field][0])
            with self.subTest(field=field):
                self._assert_schema_error(value, f"$.scope.{field}", "are not unique")

    def test_schema_validator_rejects_unknown_vocabulary(self) -> None:
        with self.assertRaisesRegex(REVIEW.ReviewError, "Unsupported JSON Schema keyword"):
            REVIEW.validate_json_schema("value", {"type": "string", "maxLength": 3})

    def test_adjudication_schema_rejects_missing_nested_type_and_additional_property(self) -> None:
        self._write_reviews()
        base = self._adjudication()
        cases: list[tuple[str, dict, tuple[str, ...]]] = []

        value = json.loads(json.dumps(base))
        value.pop("limitations")
        cases.append(("missing", value, ("$:", "missing required property 'limitations'")))

        value = json.loads(json.dumps(base))
        value["adjudicator"]["model"] = 7
        cases.append(("nested type", value, ("$.adjudicator.model", "string or null")))

        value = json.loads(json.dumps(base))
        value["review_id"] = "wrong-review"
        value["adjudicator"]["unexpected"] = True
        cases.append((
            "additional property",
            value,
            ("$.adjudicator", "additional property 'unexpected' is not allowed"),
        ))

        for label, value, fragments in cases:
            with self.subTest(label=label):
                self._write_adjudication(value=value)
                result = self._validate()
                message = "\n".join(result["errors"])
                self.assertFalse(result["ok"])
                self.assertIn("adjudication schema", message)
                for fragment in fragments:
                    self.assertIn(fragment, message)
                self.assertNotIn("adjudication target or review_id mismatch", message)

    def test_human_decision_schema_rejects_missing_nested_type_and_additional_property(self) -> None:
        self._write_reviews()
        self._write_adjudication()
        base = self._human_decision()
        cases: list[tuple[str, dict, tuple[str, ...]]] = []

        value = json.loads(json.dumps(base))
        value.pop("dissent")
        cases.append(("missing", value, ("$:", "missing required property 'dissent'")))

        value = json.loads(json.dumps(base))
        value["conditions"] = [7]
        cases.append(("nested type", value, ("$.conditions[0]", "expected type string")))

        value = json.loads(json.dumps(base))
        value["review_id"] = "wrong-review"
        value["target"]["unexpected"] = True
        cases.append((
            "additional property",
            value,
            ("$.target", "additional property 'unexpected' is not allowed"),
        ))

        path = self.bundle / "human-decision" / "decision.json"
        for label, value, fragments in cases:
            with self.subTest(label=label):
                REVIEW.write_json(path, value)
                result = self._validate()
                message = "\n".join(result["errors"])
                self.assertFalse(result["ok"])
                self.assertIn("human decision schema", message)
                for fragment in fragments:
                    self.assertIn(fragment, message)
                self.assertNotIn("human decision target or review_id mismatch", message)

    def test_validation_uses_packet_frozen_schemas_when_local_assets_drift(self) -> None:
        self._write_reviews()
        self._write_adjudication()
        drift_root = self.root / "drifted-assets"
        (drift_root / "schemas").mkdir(parents=True)
        (drift_root / "schemas" / "review-submission.schema.json").write_text(
            '{"type":"null"}\n', encoding="utf-8"
        )
        with mock.patch.object(REVIEW, "ASSET_ROOT", drift_root):
            result = self._validate()
        self.assertTrue(result["ok"])
        self.assertEqual(result["completed_roles"], sorted(REVIEW.REQUIRED_ROLES))

    def test_tampered_packet_schema_blocks_before_artifact_validation(self) -> None:
        self._write_reviews()
        self._write_adjudication()
        schema_path = self.bundle / "schemas" / "review-submission.schema.json"
        schema_path.write_text("{}\n", encoding="utf-8")
        result = self._validate()
        message = "\n".join(result["errors"])
        self.assertFalse(result["ok"])
        self.assertIn("packet file hash mismatch: schemas/review-submission.schema.json", message)
        self.assertIn("verified packet schema unavailable", message)
        self.assertEqual(result["completed_roles"], [])

    def test_diff_fingerprint_is_stable_across_git_configuration(self) -> None:
        baseline = REVIEW.target_record(self.repo, self.base, self.head)
        order_file = self.root / "diff-order"
        order_file.write_text("skill.md\napp.py\n", encoding="utf-8")
        attributes_file = self.root / "global-attributes"
        attributes_file.write_text("*.py binary\n", encoding="utf-8")
        for key, value in (
            ("color.ui", "always"),
            ("core.attributesFile", str(attributes_file)),
            ("core.quotePath", "false"),
            ("diff.algorithm", "patience"),
            ("diff.indentHeuristic", "true"),
            ("diff.mnemonicPrefix", "true"),
            ("diff.noprefix", "true"),
            ("diff.orderFile", str(order_file)),
            ("diff.relative", "true"),
            ("diff.renames", "copies"),
            ("diff.submodule", "diff"),
            ("diff.suppressBlankEmpty", "true"),
        ):
            self._git("config", key, value)
        hostile_environment = {
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "diff.noprefix",
            "GIT_CONFIG_VALUE_0": "true",
            "GIT_DIFF_OPTS": "-U99",
            "GIT_EXTERNAL_DIFF": "/does/not/exist",
        }
        with mock.patch.dict(REVIEW.os.environ, hostile_environment, clear=False):
            configured = REVIEW.target_record(self.repo, self.base, self.head)
        self.assertEqual(configured, baseline)

    def test_blob_at_distinguishes_missing_paths_from_git_failures(self) -> None:
        self.assertEqual(REVIEW.blob_at(self.repo, self.head, "app.py"), b"VALUE = 2\nSAFE = True\n")
        self.assertIsNone(REVIEW.blob_at(self.repo, self.head, "missing.py"))
        with self.assertRaisesRegex(REVIEW.ReviewError, "git ls-tree probe failed"):
            REVIEW.blob_at(self.repo, "0" * 40, "app.py")

    def test_blob_at_sanitizes_unexpected_probe_failure(self) -> None:
        failure = subprocess.CompletedProcess(
            args=[], returncode=128, stdout=b"",
            stderr=(f"fatal: cannot inspect {self.repo}\n".encode() + b"\x00" + b"x" * 500),
        )
        with mock.patch.object(REVIEW.subprocess, "run", return_value=failure):
            with self.assertRaises(REVIEW.ReviewError) as raised:
                REVIEW.blob_at(self.repo, self.head, "app.py")
        message = str(raised.exception)
        self.assertIn("git ls-tree probe failed with exit 128", message)
        self.assertIn("<repo>", message)
        self.assertNotIn(str(self.repo), message)
        self.assertNotIn("\n", message)
        self.assertNotIn("\x00", message)
        self.assertLess(len(message), 400)

    def test_blob_at_raises_when_exact_blob_read_fails(self) -> None:
        object_id = b"a" * 40
        probe = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=b"100644 blob " + object_id + b"\tapp.py\x00", stderr=b"",
        )
        failure = subprocess.CompletedProcess(
            args=[], returncode=128, stdout=b"", stderr=b"fatal: object disappeared\n",
        )
        with mock.patch.object(REVIEW.subprocess, "run", side_effect=[probe, failure]):
            with self.assertRaisesRegex(REVIEW.ReviewError, "git cat-file blob read failed"):
                REVIEW.blob_at(self.repo, self.head, "app.py")

    def test_missing_reviews_fail_closed(self) -> None:
        result = self._validate()
        self.assertFalse(result["ok"])
        self.assertEqual(result["computed_merge_gate"], "blocked")
        self.assertEqual(len(result["completed_roles"]), 0)

    def test_clean_reviews_are_provisional_for_human(self) -> None:
        self._write_reviews()
        self._write_adjudication()
        result = self._validate(write=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["computed_merge_gate"], "eligible_for_human_decision")
        self.assertEqual(result["decision_status"], "provisional")
        self.assertEqual(result["behavioral_efficacy"], "unknown")
        self.assertFalse(result["installation_ready"])
        self.assertTrue((self.bundle / "validation-summary.json").is_file())

    def test_open_p1_requires_changes_without_invalidating_bundle(self) -> None:
        finding = {
            "finding_id": "EM-001", "severity": "P1", "status": "open",
            "title": "Claim exceeds evidence", "claim": "The candidate claims an unmeasured result.",
            "impact": "The merge record would be misleading.",
            "evidence": [{"path": "skill.md", "line_start": 3, "line_end": 3}],
            "recommendation": "Narrow the claim.", "counterevidence": "No held-out result exists.",
            "confidence": "high",
        }
        self._write_reviews(finding=finding)
        disposition = {
            "finding_ids": ["EM-001"], "disposition": "upheld", "final_severity": "P1",
            "final_status": "open", "rationale": "Direct text exceeds evidence.",
            "evidence_basis": ["skill.md:3"],
        }
        self._write_adjudication([disposition], "changes_required")
        result = self._validate()
        self.assertTrue(result["ok"])
        self.assertEqual(result["computed_merge_gate"], "changes_required")
        self.assertEqual(result["unresolved_blocking_findings"], 1)

    def test_duplicate_reviewer_identity_blocks_independence(self) -> None:
        self._write_reviews(shared_id=True)
        self._write_adjudication()
        result = self._validate()
        self.assertFalse(result["ok"])
        self.assertIn("reviewer identities are not unique", result["errors"])

    def test_stale_submission_hash_blocks_adjudication(self) -> None:
        self._write_reviews()
        self._write_adjudication()
        path = self.bundle / "submissions" / "evidence-methodology.json"
        value = json.loads(path.read_text())
        value["limitations"].append("changed after adjudication")
        REVIEW.write_json(path, value)
        result = self._validate()
        self.assertFalse(result["ok"])
        self.assertTrue(any("hash mismatch" in item for item in result["errors"]))

    def test_packet_drift_is_detected(self) -> None:
        self._write_reviews()
        self._write_adjudication()
        (self.bundle / "context-pack.md").write_text("changed\n", encoding="utf-8")
        result = self._validate()
        self.assertFalse(result["ok"])
        self.assertTrue(any("packet file hash mismatch" in item for item in result["errors"]))


if __name__ == "__main__":
    unittest.main()
