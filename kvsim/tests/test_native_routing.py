"""Frozen placement must bind exact workload bytes and cover each request."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from kvsim.native.inputs import load_replay_workload
from kvsim.native.routing import generate_actor_affinity, load_routing


ROOT = Path(__file__).resolve().parents[2]
WORKLOAD = Path(__file__).parent / "fixtures/native/parallel-workload.json"


class RoutingTest(unittest.TestCase):
    def test_generated_affinity_is_frozen_and_bound(self):
        workload = load_replay_workload(WORKLOAD)
        data = generate_actor_affinity(workload, 2)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "routing.json"
            path.write_text(json.dumps(data))
            frozen = load_routing(path, workload, 2)
            self.assertEqual(len(frozen.assignments), len(workload.requests))
            self.assertLessEqual(set(frozen.assignments.values()), {"p0", "p1"})
            explicit = load_routing(WORKLOAD.with_name("parallel-route.json"), workload, 2)
            self.assertEqual(set(explicit.assignments.values()), {"p0", "p1"})
            for change, message in (
                ({"workload_sha256": "wrong"}, "SHA256"),
                ({"domains": ["p0"]}, "domain map"),
                ({"assignments": data["assignments"][:-1]}, "cover every request"),
            ):
                path.write_text(json.dumps(dict(data, **change)))
                with self.assertRaisesRegex(ValueError, message):
                    load_routing(path, workload, 2)
            swapped = [dict(row) for row in data["assignments"]]
            swapped[0], swapped[1] = swapped[1], swapped[0]
            path.write_text(json.dumps(dict(data, assignments=swapped)))
            with self.assertRaisesRegex(ValueError, "order or request coverage"):
                load_routing(path, workload, 2)
            retry = [dict(row) for row in data["assignments"]]
            retry[0]["attempt"] = 2
            path.write_text(json.dumps(dict(data, assignments=retry)))
            with self.assertRaisesRegex(ValueError, "attempt or placement"):
                load_routing(path, workload, 2)

    def test_all_p0_default_is_only_for_one_domain(self):
        workload = load_replay_workload(WORKLOAD)
        self.assertEqual(set(load_routing(None, workload, 1).assignments.values()), {"p0"})
        with self.assertRaisesRegex(ValueError, "explicit frozen routing"):
            load_routing(None, workload, 2)
