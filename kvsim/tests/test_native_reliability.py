"""Current delivery regressions; all assets are small bundled native fixtures."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from kvsim.native.contrast import contrast
from kvsim.native.compare import compare
from kvsim.native.bundle import build_bundle
from kvsim.native.prefix_evidence import make_evidence
from kvsim.native.result_validation import validate_capacity, validate_rates, load_jsonl, round_observation


FIXTURES = Path(__file__).parent / "fixtures/native"


class ReliabilityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def copy(self, name, dest="variant"):
        target = self.root / dest
        shutil.copytree(FIXTURES / name, target)
        return target

    def test_f1_deployment_rejects_source_and_fixed_rules(self):
        baseline = FIXTURES / "history/low"
        for field in ("source", "retention"):
            with self.subTest(field=field):
                variant = self.copy("history/high", field)
                path = variant / "manifest.json"
                manifest = json.loads(path.read_text())
                if field == "source":
                    manifest["native_source_identity"]["classes"]["Scheduler"]["sha256"] = "different"
                else:
                    manifest["effective_native_profile"]["retention_interval"] = 0
                    for profile in manifest.get("effective_native_profile_by_p", {}).values():
                        profile["retention_interval"] = 0
                path.write_text(json.dumps(manifest))
                with self.assertRaisesRegex(ValueError, "native source|cache rules"):
                    contrast(baseline, variant, self.root / "out", "deployment-conditional")

    def test_f1_supported_knobs_and_topology_still_work(self):
        baseline = FIXTURES / "two_p/1gib"
        for name, variable in (("seqs1", "p_max_num_seqs"), ("mbt512", "p_max_num_batched_tokens")):
            result = contrast(baseline, FIXTURES / name / "1gib", self.root / name,
                              "deployment-conditional")
            self.assertIn(variable, result["changed_conditions"])
            self.assertEqual(result["delta_processed_tokens"], 0)
        variant = self.copy("two_p/1gib")
        path = variant / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["scenario"]["topology"] = {"p": 2, "tp": 2, "attention": 4,
                                             "ffn": 2, "d": None, "dp": None, "ep": None}
        path.write_text(json.dumps(manifest))
        result = contrast(baseline, variant, self.root / "out", "deployment-conditional")
        self.assertIn("topology", result["changed_conditions"])

    def test_f4_rejects_inconsistent_or_nonfinite_rates(self):
        variant = self.copy("history/low")
        path = variant / "summary.json"
        original = json.loads(path.read_text())
        for level in ("global", "p0"):
            for rate in ("prefix_query_hit_rate", "actual_input_cache_fraction"):
                for value in (0.75, float("nan"), float("inf"), None):
                    with self.subTest(level=level, rate=rate, value=value):
                        data = json.loads(json.dumps(original))
                        target = data if level == "global" else data["per_p"][level]
                        target[rate] = value
                        path.write_text(json.dumps(data))
                        with self.assertRaisesRegex(ValueError, rate):
                            validate_capacity(variant)
        path.write_text(json.dumps(original))
        validate_capacity(variant)

    def test_f4_empty_and_partial_rates(self):
        empty = {"prefix_hits": 0, "prefix_queries": 0, "prefix_query_hit_rate": None,
                 "initial_adopted_cache_tokens": 0, "actual_input_tokens": 0,
                 "actual_input_cache_fraction": None}
        validate_rates(empty, "empty P", complete=True)
        partial = dict(empty, actual_input_tokens=10, prefix_queries=10, prefix_query_hit_rate=0)
        validate_rates(partial, "partial", complete=False)
        with self.assertRaisesRegex(ValueError, "NA"):
            validate_rates(dict(empty, prefix_query_hit_rate=0), "empty P", complete=True)

    def test_f2_wrong_baseline_is_rejected_and_correct_pair_works(self):
        baseline = self.copy("two_p", "baseline")
        wrong = self.copy("seqs1", "wrong")
        variant = FIXTURES / "client1/1gib"
        contrast(baseline / "1gib", variant, self.root / "contrast", "single-variable", "client_max_in_flight")
        for scan in (baseline, wrong):
            compare(scan)
        kwargs = {"contrast_path": self.root / "contrast/contrast.json", "contrast_variant_run": variant}
        with self.assertRaisesRegex(ValueError, "baseline run is not present"):
            build_bundle(wrong, self.root / "wrong.json", **kwargs)
        result = build_bundle(baseline, self.root / "correct.json", **kwargs)
        self.assertEqual(result["contrast"]["delta_processed_tokens"], 0)

    def test_g1_cached_contrast_rates_match_attached_run(self):
        scan = self.copy("history", "scan")
        compare(scan)
        contrast(scan / "low", scan / "high", self.root / "contrast", "capacity-only")
        path = self.root / "contrast/contrast.json"
        original = json.loads(path.read_text())
        good = build_bundle(scan, self.root / "good.json", contrast_path=path)
        self.assertEqual(good["contrast"]["baseline"]["summary"]["prefix_query_hit_rate"], 0)
        for side, domain in (("baseline", None), ("variant", "p0")):
            with self.subTest(side=side, domain=domain):
                cached = json.loads(json.dumps(original))
                summary = cached[side]["summary"]
                if domain is not None:
                    summary = summary["per_p"][domain]
                summary["prefix_query_hit_rate"] = 0.75
                path.write_text(json.dumps(cached))
                with self.assertRaisesRegex(ValueError, "prefix_query_hit_rate"):
                    build_bundle(scan, self.root / "bad.json", contrast_path=path)
        path.write_text(json.dumps(original))

    def test_f2_cached_contrast_cannot_bypass_current_mechanism_check(self):
        baseline = self.copy("two_p", "baseline")
        variant = self.copy("seqs1/1gib", "variant")
        compare(baseline)
        contrast(baseline / "1gib", variant, self.root / "contrast", "deployment-conditional")
        path = variant / "manifest.json"
        manifest = json.loads(path.read_text())
        manifest["effective_native_profile"]["retention_interval"] = 0
        for profile in manifest["effective_native_profile_by_p"].values():
            profile["retention_interval"] = 0
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "fixed native cache rules"):
            build_bundle(baseline, self.root / "bad.json",
                         contrast_path=self.root / "contrast/contrast.json", contrast_variant_run=variant)

    def test_f2_comparison_and_evidence_are_bound(self):
        scan = self.copy("history", "scan")
        compare(scan)
        make_evidence(scan, FIXTURES / "history-small-workload.json")
        build_bundle(scan, self.root / "good.json")
        path = scan / "first-difference-evidence.json"
        evidence = json.loads(path.read_text())
        evidence["runs"]["low"] = "another-run"
        path.write_text(json.dumps(evidence))
        with self.assertRaisesRegex(ValueError, "evidence.*binding differs"):
            build_bundle(scan, self.root / "bad.json")

        make_evidence(scan, FIXTURES / "history-small-workload.json")
        path = scan / "comparison.json"
        comparison = json.loads(path.read_text())
        comparison["runs"]["high"] = "another-run"
        path.write_text(json.dumps(comparison))
        with self.assertRaisesRegex(ValueError, "comparison.*binding differs"):
            make_evidence(scan, FIXTURES / "history-small-workload.json")
        with self.assertRaisesRegex(ValueError, "comparison.*binding differs"):
            build_bundle(scan, self.root / "bad.json")

    def test_f3_partial_last_round_preserves_work_and_other_comparisons(self):
        scan = self.root / "scan"
        scan.mkdir()
        (scan / "scan.json").write_text(json.dumps({"point_ids": ["a", "b", "c"]}))
        for point in ("a", "b", "c"):
            path = scan / point
            shutil.copytree(FIXTURES / "two_p/1gib", path)
            manifest = json.loads((path / "manifest.json").read_text())
            manifest["conditions"].pop("capacities_gib")
            manifest["run_id"] = f"partial-test-{point}"
            (path / "manifest.json").write_text(json.dumps(manifest))
            summary = json.loads((path / "summary.json").read_text())
            summary.update(point_id=point, run_id=manifest["run_id"])
            (path / "summary.json").write_text(json.dumps(summary))
        path = scan / "c"
        steps = load_jsonl(path / "steps.jsonl")[:1]
        (path / "steps.jsonl").write_text(json.dumps(steps[0]) + "\n")
        rows = load_jsonl(path / "requests.jsonl")
        for row in rows:
            for key in ("first_scheduled_step", "prefill_complete_step", "transfer_complete_step",
                        "p_reference_release_step", "client_complete_step"):
                row[key] = None
            row["cumulative_input_processing_tokens"] = 0
        rows[0].update(first_scheduled_step=1, cumulative_input_processing_tokens=768)
        (path / "requests.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
        summary.update(status="incomplete", failure_reason="p1 schedule failure", logical_steps=1,
                       requests_completed=0, requests_unfinished=4, actual_input_cache_fraction=None,
                       cumulative_input_processing_tokens=768, peak_active_blocks_global=None,
                       prefix_queries=1024, prefix_query_hit_rate=0)
        for domain, item in summary["per_p"].items():
            item.update(requests_completed=0, actual_input_cache_fraction=None,
                        cumulative_input_processing_tokens=768 if domain == "p0" else 0,
                        prefix_queries=1024 if domain == "p0" else 0,
                        prefix_query_hit_rate=0 if domain == "p0" else None,
                        peak_active_blocks=315 if domain == "p0" else 0,
                        peak_reusable_cached_blocks=0)
        (path / "summary.json").write_text(json.dumps(summary))
        result = compare(scan)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["comparable_complete_gib"], ("a", "b"))
        partial = result["summaries"]["c"]
        self.assertEqual(partial["cumulative_input_processing_tokens"], 768)
        self.assertIsNone(partial["peak_active_blocks_global"])
        self.assertEqual(partial["observation_boundary"]["partial_round"]["unobserved_p_domains"], ["p1"])
        with self.assertRaisesRegex(ValueError, "incomplete tail"):
            round_observation(steps, ["p0", "p1"], True)
        damaged = steps + load_jsonl(FIXTURES / "two_p/1gib/steps.jsonl")[2:4]
        with self.assertRaisesRegex(ValueError, "incomplete tail"):
            round_observation(damaged, ["p0", "p1"], False)

    def test_f3_missing_or_damaged_complete_steps_are_rejected(self):
        point = self.copy("two_p/1gib", "damaged")
        path = point / "steps.jsonl"
        original = path.read_text()
        path.write_text("")
        with self.assertRaisesRegex(ValueError, "lacks logical round records"):
            validate_capacity(point)
        rows = [json.loads(line) for line in original.splitlines()]
        del rows[1]["active_ref_blocks_after_schedule"]
        path.write_text("".join(json.dumps(row) + "\n" for row in rows))
        with self.assertRaisesRegex(ValueError, "missing block observations"):
            validate_capacity(point)
