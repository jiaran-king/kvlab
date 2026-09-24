from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from kvsim.native.capacity import capacity_layout
from kvsim.native.scenario import validate_scenario


ROOT = Path(__file__).resolve().parents[2]


class ScenarioTest(unittest.TestCase):
    def test_assumed_budget_is_bound_to_resolved_capacity(self):
        conditions = json.loads((Path(__file__).parent / "fixtures/native/scenario-conditions.json").read_text())
        layouts = {gib: capacity_layout(gib) for gib in conditions["capacities_gib"]}
        self.assertEqual(validate_scenario(conditions, layouts)["budgets"]["16"]["source"], "assumed")
        wrong = copy.deepcopy(conditions)
        wrong["scenario"]["budgets"]["16"].update(authority="bytes_per_rank", value=16 * 1024**3 + 1)
        with self.assertRaisesRegex(ValueError, "disagrees with actual resolved capacity"):
            validate_scenario(wrong, layouts)
        measured = copy.deepcopy(conditions)
        measured["scenario"]["budgets"]["16"]["source"] = "measured"
        with self.assertRaisesRegex(ValueError, "needs traceable evidence"):
            validate_scenario(measured, layouts)
