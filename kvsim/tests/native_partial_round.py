"""Bounded native fault regression. Requires the pinned CPU runtime, no model.

Inject a p1 schedule exception after p0 completes; preserve its real work and
compare the other two completed points. This is a test, not a driver option.
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch

from kvsim.native.run import Scheduler, run_capacity
from kvsim.native.conditions import read_conditions
from kvsim.native.inputs import load_replay_workload
from kvsim.native.routing import load_routing
from kvsim.native.compare import compare
from kvsim.native.result_validation import validate_capacity

root = Path(sys.argv[1]).resolve()
root.mkdir(parents=True, exist_ok=False)
fixtures = Path(__file__).resolve().parent / 'fixtures/native'
conditions = json.loads((fixtures / 'two_p/1gib/manifest.json').read_text())['conditions']
conditions.pop('capacities_gib')
conditions['capacity_points'] = [dict(id=key, authority='physical_blocks', physical_blocks=1032)
                                 for key in ('complete-a', 'partial', 'complete-b')]
conditions['scenario_id'] = 'native-p1-fault-regression'
conditions['routing_trace'] = str(fixtures / 'parallel-route.json')
path = root / 'conditions.json'
path.write_text(json.dumps(conditions, indent=2))
conditions = read_conditions(path)
workload = load_replay_workload(fixtures / 'parallel-workload.json')
routing = load_routing(fixtures / 'parallel-route.json', workload, 2)
original = Scheduler.schedule
seen = []

def fail_second_domain(self):
    if self not in seen:
        seen.append(self)
    if len(seen) == 2 and self is seen[1]:
        raise RuntimeError('intentional test fault: p1 before schedule')
    return original(self)

for key in ('complete-a', 'partial', 'complete-b'):
    if key == 'partial':
        with patch.object(Scheduler, 'schedule', fail_second_domain):
            run_capacity(workload, conditions, key, root / key, routing)
    else:
        run_capacity(workload, conditions, key, root / key, routing)
    summary, rows = validate_capacity(root / key)
    if key == 'partial':
        assert summary['status'] == 'incomplete'
        assert summary['cumulative_input_processing_tokens'] == 768
        assert summary['per_p']['p1']['cumulative_input_processing_tokens'] == 0
        assert summary['peak_active_blocks_global'] is None
        assert summary['observation_boundary']['partial_round']['observed_p_domains'] == ['p0']
    else:
        assert summary['status'] == 'complete'
        assert summary['cumulative_input_processing_tokens'] == 4096
(root / 'scan.json').write_text(json.dumps({'point_ids': ['complete-a', 'partial', 'complete-b']}))
comparison = compare(root)
assert comparison['comparable_complete_gib'] == ('complete-a', 'complete-b')
assert comparison['first_request_difference']['complete-a_vs_complete-b'] is None
(root / 'fault-validation.json').write_text(json.dumps({
    'status': 'passed', 'fault': 'p1 schedule, after real p0 completion',
    'partial_processed_tokens': 768, 'complete_processed_tokens': [4096, 4096],
    'partial_global_full_round_peak': None, 'complete_pair_comparable': True,
}, indent=2))
print('NATIVE_PARTIAL_ROUND_PASS', root)
