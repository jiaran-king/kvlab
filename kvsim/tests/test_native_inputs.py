"""Reject workload semantics that the fixed native H20 driver cannot execute."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from kvsim.native.inputs import (
    load_replay_workload, validate_h20_workload,
    validate_h20_condition_fields,
)
from kvsim.native.conditions import read_conditions


def workload(tokens=None):
    tokens = tokens or [1, 2]
    return {
        "schema": "kvlab-replay-workload/v1",
        "metadata": {"content_source": "historical_capture", "execution_profile": "request-admission"},
        "requests": [{
            "runtime_request_id": "r0", "runtime_session_id": "s0",
            "actor_id": "lead", "source_key": "k0", "node_type": "request",
            "tokens": tokens, "input_tokens": len(tokens), "output_tokens": 1,
            "effective_interval_seconds": 0, "send_after": None, "context_after": None,
            "cache_identity": "", "content_source": "historical_capture",
        }],
    }


class NativeInputTest(unittest.TestCase):
    def load(self, data):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workload.json"
            path.write_text(json.dumps(data))
            return load_replay_workload(path)

    def test_rejects_unknown_profile_and_nonempty_cache_identity(self):
        data = workload()
        data["metadata"]["execution_profile"] = "unknown"
        with self.assertRaisesRegex(ValueError, "unsupported native execution profile"):
            self.load(data)
        data["metadata"]["execution_profile"] = "request-admission"
        data["requests"][0]["cache_identity"] = "tenant-A"
        with self.assertRaisesRegex(ValueError, "non-empty cache identity"):
            self.load(data)

    def test_exporter_capture_requires_provenance_and_keeps_source(self):
        data = workload()
        data["metadata"]["content_source"] = "captured_tokens"
        data["requests"][0]["content_source"] = "captured_tokens"
        with self.assertRaisesRegex(ValueError, "requires tokenizer"):
            self.load(data)
        data["metadata"].update(tokenizer_sha256="recorded-tokenizer", prompt_template="recorded-template")
        self.assertEqual(self.load(data).content_source, "captured_tokens")

    def test_rejects_empty_and_overlong_requests(self):
        data = workload()
        data["requests"] = []
        with self.assertRaisesRegex(ValueError, "no requests"):
            self.load(data)
        frozen = self.load(workload([1] * 81920))
        with self.assertRaisesRegex(ValueError, "max_model_len"):
            validate_h20_workload(frozen)

    def test_rejects_unimplemented_condition_field(self):
        with self.assertRaisesRegex(ValueError, "unsupported H20 condition fields: eviction_policy"):
            validate_h20_condition_fields({"profile": "h20-dsv4-tp2-fp8-5group", "eviction_policy": "lru"})

    def test_three_scheduler_knobs_are_conditions_not_layout_constants(self):
        base = json.loads((Path(__file__).resolve().parents[1] / "native/h20-conditions.json").read_text())
        base.update(client_max_in_flight=8, p_max_num_seqs=4, p_max_num_batched_tokens=16384)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "conditions.json"
            path.write_text(json.dumps(base))
            self.assertEqual(read_conditions(path)["p_max_num_seqs"], 4)
            for field, value in (("client_max_in_flight", True),
                                 ("p_max_num_seqs", 0),
                                 ("p_max_num_batched_tokens", -1)):
                invalid = dict(base, **{field: value})
                path.write_text(json.dumps(invalid))
                with self.assertRaisesRegex(ValueError, field):
                    read_conditions(path)

    def test_multi_p_requires_trace_and_bounded_total_pool(self):
        base = json.loads((Path(__file__).resolve().parents[1] / "native/h20-conditions.json").read_text())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "conditions.json"
            path.write_text(json.dumps(dict(base, p_domains=2)))
            with self.assertRaisesRegex(ValueError, "all-p0 requires one P"):
                read_conditions(path)
            path.write_text(json.dumps(dict(base, p_domains=2, routing="trace", routing_trace="route.json")))
            self.assertEqual(read_conditions(path)["p_domains"], 2)
            path.write_text(json.dumps(dict(base, p_domains=3, routing="trace", routing_trace="route.json")))
            with self.assertRaisesRegex(ValueError, "aggregate physical blocks"):
                read_conditions(path)


if __name__ == "__main__":
    unittest.main()
