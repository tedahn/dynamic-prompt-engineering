from __future__ import annotations

import json
import statistics
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from automation.core import build_candidate_manifest, load_config
from automation.evaluation import _cluster_interval, invoke_adapter


class AdversarialAutomationTest(unittest.TestCase):
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

    def test_resource_bounds_bootstrap_the_declared_median(self) -> None:
        values = {"task-a": 1.0, "task-b": 1.0, "task-c": 100.0}
        interval = _cluster_interval(values, seed=7, samples=500, statistic=statistics.median)
        self.assertEqual(interval["estimate"], 1.0)
        self.assertNotEqual(interval["estimate"], statistics.fmean(values.values()))


if __name__ == "__main__":
    unittest.main()
