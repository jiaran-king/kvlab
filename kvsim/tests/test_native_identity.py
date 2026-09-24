from __future__ import annotations

import unittest

from kvsim.native.identity import run_id


class RunIdentityTest(unittest.TestCase):
    def test_run_identity_distinguishes_knobs_routing_and_budget(self):
        conditions = {
            "profile": "h20-dsv4-tp2-fp8-5group", "client_max_in_flight": 3,
            "p_max_num_seqs": 2, "p_max_num_batched_tokens": 8192,
            "capacities_gib": [16, 24], "routing_trace": "a.json",
        }
        route = {"routing_sha256": "one", "method": "explicit"}
        base = run_id("workload", route, conditions, 16)
        self.assertEqual(base, run_id("workload", route,
                                      dict(conditions, routing_trace="elsewhere/a.json",
                                           capacities_gib=[16]), 16))
        self.assertNotEqual(base, run_id("workload", route, dict(conditions, client_max_in_flight=8), 16))
        self.assertNotEqual(base, run_id("workload", dict(route, routing_sha256="two"), conditions, 16))
        self.assertNotEqual(base, run_id("workload", route, conditions, 24))
