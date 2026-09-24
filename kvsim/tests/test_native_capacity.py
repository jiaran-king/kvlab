import unittest

from kvsim.native.capacity import GIB, capacity_layout, resolve_budget, budgets_from_conditions


class ExactBudgetTest(unittest.TestCase):
    def test_exact_bytes_remainder_and_equivalent_blocks(self):
        stride = capacity_layout(1)["bytes_per_physical_block_per_rank"]
        budget = 3 * GIB // 2 + 123
        count = budget // stride
        by_bytes = resolve_budget({"authority": "bytes_per_rank", "bytes_per_rank": budget})
        both = resolve_budget({"authority": "physical_blocks", "physical_blocks": count,
                               "bytes_per_rank": budget})
        self.assertEqual(by_bytes["physical_blocks"], count)
        self.assertEqual(both["physical_blocks"], count)
        self.assertEqual(by_bytes["budget_bytes_per_rank"], budget)
        self.assertEqual(by_bytes["unused_budget_bytes_per_rank"], budget % stride)
        self.assertEqual(by_bytes["reserved_null_blocks"], 1)
        only_blocks = resolve_budget({"authority": "physical_blocks", "physical_blocks": count})
        self.assertIsNone(only_blocks["budget_bytes_per_rank"])
        self.assertIsNone(only_blocks["budget_gib_per_rank"])
        self.assertEqual(only_blocks["effective_kv_bytes_per_rank"], count * stride)

    def test_conflict_and_minimum_pool(self):
        stride = capacity_layout(1)["bytes_per_physical_block_per_rank"]
        with self.assertRaisesRegex(ValueError, "disagree"):
            resolve_budget({"authority": "bytes_per_rank", "bytes_per_rank": stride * 3,
                            "physical_blocks": 2})
        for point in ({"authority": "physical_blocks", "physical_blocks": 1},
                      {"authority": "bytes_per_rank", "bytes_per_rank": stride - 1}):
            with self.assertRaisesRegex(ValueError, "null block"):
                resolve_budget(point)

    def test_equal_pools_keep_distinct_point_ids(self):
        stride = capacity_layout(1)["bytes_per_physical_block_per_rank"]
        result = budgets_from_conditions({"capacity_points": [
            {"id": "baseline", "authority": "bytes_per_rank", "bytes_per_rank": stride * 3},
            {"id": "variant", "authority": "bytes_per_rank", "bytes_per_rank": stride * 3 + 1},
        ]})
        self.assertEqual(list(result), ["baseline", "variant"])
        self.assertEqual(result["baseline"]["physical_blocks"], result["variant"]["physical_blocks"])

    def test_legacy_uses_same_conversion(self):
        self.assertEqual(budgets_from_conditions({"capacities_gib": [16]})[16],
                         resolve_budget({"authority": "bytes_per_rank", "bytes_per_rank": 16 * GIB}))
