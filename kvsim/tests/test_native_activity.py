from __future__ import annotations

import unittest
from pathlib import Path

from kvsim.native.activity import activity_by_p
from kvsim.native.result_validation import load_jsonl


ROOT = Path(__file__).resolve().parents[2]


class ActivityTest(unittest.TestCase):
    def test_same_round_parallelism_and_activity_by_p(self):
        point = Path(__file__).parent / "fixtures/native/two_p/1gib"
        steps = load_jsonl(point / "steps.jsonl")
        requests = load_jsonl(point / "requests.jsonl")
        activity = activity_by_p(requests, steps, ["p0", "p1"])
        self.assertEqual({p: row["running_peak"] for p, row in activity.items()},
                         {"p0": 2, "p1": 2})
        self.assertTrue(any(a["scheduled"] and b["scheduled"]
                            for a, b in zip(steps[::2], steps[1::2])))
        self.assertEqual(sum(row["preemptions"] for row in activity.values()), 0)
