from __future__ import annotations

import json
import tempfile
import shutil
import unittest
from pathlib import Path

from kvsim.native.contrast import contrast
from kvsim.native.bundle import build_bundle


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / "fixtures/native"
SCAN = FIXTURES / "active"


class ContrastTest(unittest.TestCase):
    def test_relocated_source_and_labels_are_not_execution_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            point = Path(directory) / "copy"
            shutil.copytree(SCAN / "low", point)
            path = point / "manifest.json"
            manifest = json.loads(path.read_text())
            for entry in manifest["native_source_identity"]["classes"].values():
                entry["path"] = "/relocated/" + Path(entry["path"]).name
            manifest["conditions"].update(scenario_id="renamed", event_limit=1)
            path.write_text(json.dumps(manifest))
            result = contrast(SCAN / "low", point, Path(directory) / "out", "capacity-only")
            self.assertEqual(result["changed_conditions"], {})
            entry["sha256"] = "different native source"
            path.write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "execution differences"):
                contrast(SCAN / "low", point, Path(directory) / "out", "capacity-only")

    def test_equal_effective_capacity_is_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            result = contrast(SCAN / "low", SCAN / "low", Path(directory), "capacity-only")
            self.assertFalse(result["effective_capacity_changed"])
            self.assertEqual(result["changed_conditions"], {})
            self.assertEqual(result["delta_processed_tokens"], 0)
            self.assertIn("equivalence", result["capacity_interpretation"])

    def test_capacity_only_reports_zero_effect_without_claiming_afd(self):
        with tempfile.TemporaryDirectory() as directory:
            result = contrast(SCAN / "low", SCAN / "high", Path(directory), "capacity-only")
            self.assertEqual(result["delta_processed_tokens"], 0)
            self.assertEqual(result["relative_processed_reduction"], 0)
            self.assertEqual(result["request_changes"], [])
            self.assertFalse(result["real_deployment_conclusion_supported"])

    def test_rejects_mixed_route_in_capacity_only(self):
        with tempfile.TemporaryDirectory() as directory:
            point = Path(directory) / "variant"
            point.mkdir()
            for name in ("summary.json", "requests.jsonl", "steps.jsonl"):
                (point / name).write_bytes((SCAN / "high" / name).read_bytes())
            manifest = json.loads((SCAN / "high/manifest.json").read_text())
            manifest["conditions"]["client_max_in_flight"] += 1
            (point / "manifest.json").write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError, "non-capacity execution differences"):
                contrast(SCAN / "low", point, Path(directory) / "out", "capacity-only")

    def test_deployment_bundle_embeds_variant_request_evidence(self):
        from kvsim.native.compare import compare
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            scan = out / "baseline"
            shutil.copytree(FIXTURES / "two_p", scan)
            compare(scan)
            contrast(scan / "1gib", FIXTURES / "seqs1/1gib", out, "deployment-conditional")
            bundle = build_bundle(scan, out / "native-results.json", contrast_path=out / "contrast.json",
                                  contrast_variant_run=FIXTURES / "seqs1/1gib")
            self.assertEqual(bundle["contrast"]["mode"], "deployment-conditional")
            self.assertEqual(bundle["contrast"]["delta_processed_tokens"], 0)
            self.assertEqual(bundle["contrast_variant"]["summary"]["p_domains"], 2)
            self.assertEqual(bundle["contrast_variant"]["manifest"]["run_id"],
                             bundle["contrast"]["variant"]["evidence"]["run_id"])
