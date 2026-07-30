from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "codex_adapter.py"
SPEC = importlib.util.spec_from_file_location("codex_adapter", SCRIPT_PATH)
assert SPEC and SPEC.loader
adapter = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = adapter
SPEC.loader.exec_module(adapter)


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


class CodexAdapterPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="codex-adapter-test-")
        self.root = Path(self.temporary.name)
        self.study = self.root / "study"
        self.config_path = self.study / "config" / "loop-v1.json"
        self.runtime_path = self.study / "runtime-profile.json"
        self.instance = self.root / "instance"
        self.codex_home = self.root / "codex-home"
        self.approval_path = self.root / "approval.json"
        self.no_tool_cwd = self.root / "no-tool"
        self.cli_path = self.root / "fake-codex"
        self.now = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)
        self.epoch_id = "EPOCH-SMOKE-TEST"
        self.plan_sha = ""
        self.runtime_sha = ""
        self.approval: dict[str, object] = {}
        self._build_fixture()

    def tearDown(self) -> None:
        if self.no_tool_cwd.exists():
            self.no_tool_cwd.chmod(0o755)
        self.temporary.cleanup()

    @property
    def call_log(self) -> Path:
        return Path(str(self.cli_path) + ".calls")

    def _write_artifact(self, connection: sqlite3.Connection, content: bytes) -> str:
        digest = hashlib.sha256(content).hexdigest()
        relative = Path("artifacts") / "sha256" / digest[:2] / digest
        destination = self.instance / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        connection.execute(
            "INSERT INTO artifacts(sha256, relative_path) VALUES(?, ?)",
            (digest, str(relative)),
        )
        return digest

    def _build_fixture(self) -> None:
        self.config_path.parent.mkdir(parents=True)
        self.instance.mkdir()
        self.codex_home.mkdir()
        (self.codex_home / "auth.json").write_text("{}\n")
        self.no_tool_cwd.mkdir()
        self.no_tool_cwd.chmod(0o555)

        feature_lines = "\n".join(
            f"{name} stable false"
            for name in (*adapter.COMMON_FEATURE_DISABLES, *adapter.NO_TOOL_FEATURE_DISABLES)
        )
        self.cli_path.write_text(
            "#!/bin/sh\n"
            "printf '%s\\n' \"$*\" >> \"$0.calls\"\n"
            "if [ \"$1\" = \"--version\" ]; then\n"
            "  printf '%s\\n' 'codex-cli test-1.0'\n"
            "elif [ \"$1\" = \"login\" ] && [ \"$2\" = \"status\" ]; then\n"
            "  printf '%s\\n' 'Logged in using ChatGPT'\n"
            "elif [ \"$1\" = \"features\" ] && [ \"$2\" = \"list\" ]; then\n"
            f"  printf '%s\\n' '{feature_lines}'\n"
            "else\n"
            "  exit 91\n"
            "fi\n"
        )
        self.cli_path.chmod(0o755)

        runtime = {
            "schema_version": "test",
            "execution_boundary": {"external_side_effects": "Forbidden"},
            "target_surface": {
                "cli_path": str(self.cli_path),
                "cli_sha256": adapter.sha256_file(self.cli_path),
                "cli_bytes": self.cli_path.stat().st_size,
                "cli_version": "codex-cli test-1.0",
                "model_alias": "gpt-test",
                "reasoning_effort": "high",
                "common_disabled_features": list(adapter.COMMON_FEATURE_DISABLES),
                "additional_no_tool_disabled_features": list(adapter.NO_TOOL_FEATURE_DISABLES),
                "fixed_cli_flags": [
                    "--ephemeral",
                    "--ignore-user-config",
                    "--ignore-rules",
                    "--skip-git-repo-check",
                    "--json",
                    "--ask-for-approval=never",
                ],
            },
        }
        self.runtime_path.write_bytes(canonical_bytes(runtime))
        self.runtime_sha = adapter.sha256_file(self.runtime_path)
        config = {
            "schema_version": "test",
            "target_surface": {
                "runtime_profile_path": "runtime-profile.json",
                "runtime_profile_sha256": self.runtime_sha,
            },
            "live_execution": {"authorized": True},
        }
        self.config_path.write_bytes(canonical_bytes(config))

        connection = sqlite3.connect(self.instance / "state.db")
        connection.executescript(
            "CREATE TABLE artifacts(sha256 TEXT PRIMARY KEY, relative_path TEXT NOT NULL);"
            "CREATE TABLE epochs(epoch_id TEXT PRIMARY KEY, stage TEXT NOT NULL, plan_sha256 TEXT NOT NULL, status TEXT NOT NULL);"
            "CREATE TABLE cells(cell_id TEXT PRIMARY KEY, epoch_id TEXT NOT NULL, packet_sha256 TEXT NOT NULL, status TEXT NOT NULL);"
        )
        rows = []
        for cell_id in ("CELL-001", "CELL-002"):
            packet_sha = self._write_artifact(
                connection,
                canonical_bytes({"schema_version": "1.0", "cell_id": cell_id, "prompt": "synthetic"}),
            )
            rows.append({"cell_id": cell_id, "packet_sha256": packet_sha})
            connection.execute(
                "INSERT INTO cells(cell_id, epoch_id, packet_sha256, status) VALUES(?, ?, ?, 'planned')",
                (cell_id, self.epoch_id, packet_sha),
            )
        plan = {
            "schema_version": "1.0",
            "epoch_id": self.epoch_id,
            "stage": "smoke",
            "cell_count": len(rows),
            "rows": rows,
        }
        self.plan_sha = self._write_artifact(connection, canonical_bytes(plan))
        connection.execute(
            "INSERT INTO epochs(epoch_id, stage, plan_sha256, status) VALUES(?, 'smoke', ?, 'planned')",
            (self.epoch_id, self.plan_sha),
        )
        connection.commit()
        connection.close()

        self.approval = {
            "schema_version": "1.0",
            "approval_id": "APPROVAL-TEST-001",
            "approver_type": "human",
            "approved_by": "Test Human",
            "approved_at": "2026-07-29T11:55:00Z",
            "expires_at": "2026-07-29T13:00:00Z",
            "epoch_id": self.epoch_id,
            "plan_sha256": self.plan_sha,
            "runtime_profile_sha256": self.runtime_sha,
            "maximum_cells": 1,
            "cell_ids": ["CELL-001"],
            "provider_processing_acknowledged": True,
            "allowed_stage": "smoke",
        }
        self._write_approval(self.approval)

    def _write_approval(self, value: dict[str, object], path: Path | None = None) -> Path:
        destination = path or self.approval_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(canonical_bytes(value))
        return destination

    def _preflight(self, **overrides: object) -> dict[str, object]:
        arguments: dict[str, object] = {
            "instance": self.instance,
            "epoch_id": self.epoch_id,
            "cli_path": self.cli_path,
            "codex_home": self.codex_home,
            "approval_path": self.approval_path,
            "config_path": self.config_path,
            "no_tool_cwd": self.no_tool_cwd,
            "now": self.now,
        }
        arguments.update(overrides)
        return adapter.preflight(**arguments)

    def test_successful_preflight_never_invokes_exec(self) -> None:
        report = self._preflight()
        self.assertEqual(report["status"], "ready-for-separately-reviewed-execution-adapter")
        self.assertFalse(report["execution_performed"])
        self.assertEqual(report["model_invocations"], 0)
        self.assertEqual(report["epoch"]["approved_cell_count"], 1)
        calls = self.call_log.read_text().splitlines()
        self.assertEqual(calls, ["--version", "login status", "features list"])
        self.assertFalse(any("exec" in call for call in calls))

    def test_repository_kill_switch_blocks_before_cli_checks(self) -> None:
        config = json.loads(self.config_path.read_text())
        config["live_execution"]["authorized"] = False
        self.config_path.write_bytes(canonical_bytes(config))
        with self.assertRaisesRegex(adapter.AdapterError, "kill switch"):
            self._preflight()
        self.assertFalse(self.call_log.exists())

    def test_plan_and_runtime_hashes_are_exact_approval_gates(self) -> None:
        for field, message in (
            ("plan_sha256", "plan_sha256"),
            ("runtime_profile_sha256", "runtime_profile_sha256"),
        ):
            with self.subTest(field=field):
                changed = copy.deepcopy(self.approval)
                changed[field] = "0" * 64
                self._write_approval(changed)
                with self.assertRaisesRegex(adapter.AdapterError, message):
                    self._preflight()
                self.assertFalse(self.call_log.exists())
        self._write_approval(self.approval)

    def test_expiry_provider_ack_and_human_identity_fail_closed(self) -> None:
        cases = (
            ({"expires_at": "2026-07-29T11:59:59Z"}, "expired"),
            ({"provider_processing_acknowledged": False}, "Provider processing"),
            ({"approved_by": "codex"}, "named human"),
            ({"approver_type": "agent"}, "named human"),
        )
        for changes, message in cases:
            with self.subTest(changes=changes):
                changed = copy.deepcopy(self.approval)
                changed.update(changes)
                self._write_approval(changed)
                with self.assertRaisesRegex(adapter.AdapterError, message):
                    self._preflight()
                self.assertFalse(self.call_log.exists())
        self._write_approval(self.approval)

    def test_cell_scope_is_exact_and_must_reference_the_frozen_plan(self) -> None:
        changed = copy.deepcopy(self.approval)
        changed["maximum_cells"] = 2
        self._write_approval(changed)
        with self.assertRaisesRegex(adapter.AdapterError, "exactly equal"):
            self._preflight()
        changed["maximum_cells"] = 1
        changed["cell_ids"] = ["CELL-UNKNOWN"]
        self._write_approval(changed)
        with self.assertRaisesRegex(adapter.AdapterError, "unknown cells"):
            self._preflight()
        self.assertFalse(self.call_log.exists())

    def test_approval_manifest_inside_study_package_is_rejected(self) -> None:
        local_approval = self._write_approval(self.approval, self.study / "approval.json")
        with self.assertRaisesRegex(adapter.AdapterError, "outside the research package"):
            self._preflight(approval_path=local_approval)
        self.assertFalse(self.call_log.exists())

    def test_command_template_preserves_pilot_isolation_controls(self) -> None:
        profile = json.loads(self.runtime_path.read_text())
        command = adapter.build_command_template(self.cli_path, self.no_tool_cwd, profile)
        self.assertLess(command.index("--ask-for-approval"), command.index("exec"))
        self.assertIn("--ephemeral", command)
        self.assertIn("--ignore-user-config", command)
        self.assertIn("--ignore-rules", command)
        self.assertIn("read-only", command)
        self.assertEqual(command[-1], "-")
        disabled = {command[index + 1] for index, value in enumerate(command[:-1]) if value == "--disable"}
        self.assertEqual(
            disabled,
            set(adapter.COMMON_FEATURE_DISABLES) | set(adapter.NO_TOOL_FEATURE_DISABLES),
        )


if __name__ == "__main__":
    unittest.main()
