import unittest

from kvsim.native.accounting import scheduled_input_interval, completed_input_totals


class AccountingTest(unittest.TestCase):
    def test_adopted_prefix_and_handshake_are_not_local_input(self):
        self.assertEqual(scheduled_input_interval(1025, 257, 1024), (768, 1024))
        self.assertEqual(scheduled_input_interval(1025, 1, 1024), (1024, 1024))

    def test_resume_uses_new_cursor_and_counts_overlaps(self):
        # Process [0,768), then resume from 512 after preemption, not old 768.
        first = scheduled_input_interval(768, 768, 1024)
        resumed = scheduled_input_interval(1024, 512, 1024)
        rows = [{"start": a, "end": b} for a, b in (first, resumed)]
        self.assertEqual(completed_input_totals(rows), {
            "cumulative_input_processing_tokens": 1280,
            "unique_local_input_tokens": 1024,
            "repeated_local_input_tokens": 256,
        })

    def test_recovered_cache_can_leave_gaps_in_local_processing(self):
        result = completed_input_totals([
            {"start": 256, "end": 512}, {"start": 768, "end": 1024},
            {"start": 256, "end": 384},
        ])
        self.assertEqual(result["unique_local_input_tokens"], 512)
        self.assertEqual(result["repeated_local_input_tokens"], 128)
