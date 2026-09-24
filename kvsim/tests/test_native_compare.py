"""Portable scan regressions using the bundled three-request native run."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from kvsim.native.compare import compare
from kvsim.native.bundle import build_bundle
from kvsim.native.capacity import capacity_layout, capacities_from_conditions
from kvsim.native.prefix_evidence import make_evidence
from kvsim.native.result_validation import validate_capacity

FIXTURES = Path(__file__).parent / 'fixtures/native'


class NativePartialReportTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'scan'
        shutil.copytree(FIXTURES / 'history', self.root)

    def edit(self, point, filename, change):
        path = self.root / point / filename
        data = json.loads(path.read_text())
        change(data)
        path.write_text(json.dumps(data))

    def test_capacity_selection_rejects_duplicates_and_out_of_range(self):
        for values in ([12, 12], [24, 16], [16, 49], [True, 24]):
            with self.subTest(values=values), self.assertRaises(ValueError):
                capacities_from_conditions({'capacities_gib': values})
        self.assertEqual(capacity_layout(16)['physical_blocks'], 16524)

    def test_selected_scan_reaches_comparison_evidence_and_bundle(self):
        result = compare(self.root)
        self.assertEqual(tuple(result['point_ids']), ('low', 'high'))
        evidence = make_evidence(self.root, FIXTURES / 'history-small-workload.json')
        self.assertEqual(evidence['findings']['low_vs_high']['request_id'], 'history-2')
        bundle = build_bundle(self.root, self.root / 'native-results.json')
        self.assertEqual(set(bundle['runs']), {'low', 'high'})
        self.assertEqual(bundle['runs']['high']['summary']['cumulative_input_processing_tokens'], 2304)
        self.assertNotIn('h20-conditions-events.json', (self.root / 'REPORT.md').read_text())

    def test_evidence_rejects_same_length_different_workload(self):
        compare(self.root)
        data = json.loads((FIXTURES / 'history-small-workload.json').read_text())
        data['requests'][0]['tokens'][0] += 1
        wrong = self.root / 'wrong.json'
        wrong.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'do not match run manifest'):
            make_evidence(self.root, wrong)

    def test_per_p_summary_is_tied_to_assigned_requests(self):
        self.edit('low', 'summary.json', lambda s: s['per_p']['p0'].update(cumulative_input_processing_tokens=1))
        with self.assertRaisesRegex(ValueError, 'p0 summary disagrees'):
            validate_capacity(self.root / 'low')

    def test_incomplete_point_is_retained(self):
        self.edit('low', 'summary.json', lambda s: s.update(status='incomplete',
                  failure_reason='completion notification missing', requests_completed=2,
                  requests_unfinished=1, actual_input_cache_fraction=None))
        self.edit('low', 'summary.json', lambda s: s['per_p']['p0'].update(requests_completed=2))
        path = self.root / 'low/requests.jsonl'
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        rows[-1]['client_complete_step'] = None
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        result = compare(self.root)
        self.assertEqual(result['status'], 'incomplete')
        self.assertEqual(result['comparable_complete_gib'], ('high',))
        self.assertEqual(set(result['summaries']), {'low', 'high'})

    def test_complete_scan_rejects_mixed_execution_conditions(self):
        self.edit('low', 'manifest.json', lambda m: m['conditions'].update(full_sequence_must_fit=False))
        with self.assertRaisesRegex(ValueError, 'different execution conditions'):
            compare(self.root)

    def test_rejects_missing_request_row(self):
        path = self.root / 'low/requests.jsonl'
        path.write_text('\n'.join(path.read_text().splitlines()[:-1]) + '\n')
        with self.assertRaisesRegex(ValueError, 'request rows, summary plans'):
            compare(self.root)

    def test_rejects_summary_processing_mismatch(self):
        self.edit('low', 'summary.json', lambda s: s.update(cumulative_input_processing_tokens=1))
        with self.assertRaisesRegex(ValueError, 'cumulative_input_processing_tokens'):
            compare(self.root)

    def test_rejects_mixed_effective_native_profiles(self):
        self.edit('low', 'manifest.json', lambda m: m['effective_native_profile'].update(retention_interval=0))
        with self.assertRaisesRegex(ValueError, 'native profiles|cache rules'):
            compare(self.root)
