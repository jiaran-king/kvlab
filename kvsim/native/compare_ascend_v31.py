"""Bind native Ascend replay rows to frozen inputs and archived v3.1 measurements."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path

RUNS = {10: 'cal10-v31-0924-01', 16: 'cal16-v31-0924-01', 24: 'cal24-v31-0924-01'}
FIELDS = {'input_tokens': 'input_tokens',
          'initial_adopted_cache_tokens': 'local_hit',
          'cumulative_input_processing_tokens': 'local_compute',
          'prefix_hits': 'local_hit'}


def load_inputs(base: Path) -> dict:
    inputs = {}
    for rank in range(4):
        with gzip.open(base / f'v31-p{rank}-requests.jsonl.gz', 'rt') as source:
            for line in source:
                row = json.loads(line)
                rid = row['runtime_request_id']
                if rid in inputs:
                    raise ValueError(f'duplicate frozen request {rid}')
                inputs[rid] = {'p_domain': f'p{rank}',
                               'session_id': row['runtime_session_id'],
                               'input_tokens': row['input_tokens'],
                               'engine_input_sha256': hashlib.sha256(json.dumps(
                                   row['tokens'], separators=(',', ':')).encode()).hexdigest()}
    if len(inputs) != 1313:
        raise ValueError(f'expected 1313 frozen requests, got {len(inputs)}')
    return inputs


def compare(base: Path, result_dir: Path) -> dict:
    measured = json.loads((base / 'v31-measured-reference.json').read_text())['runs']
    inputs = load_inputs(base)
    report = {'schema': 'kvlab-v31-native-comparison/v1',
              'comparison_basis': 'frozen engine inputs and actual per-P order',
              'runs': {}, 'capacity_transitions': {}}
    rows_by_budget = {}
    for budget, run_id in RUNS.items():
        reference = measured[run_id]
        pairs = {}
        sums = Counter()
        per_p = {}
        for rank in range(4):
            path = result_dir / f'p{rank}-inflight{budget}-full.jsonl'
            rows = [json.loads(line) for line in path.open()]
            with gzip.open(base / f'v31-p{rank}-requests.jsonl.gz', 'rt') as source:
                expected_order = [json.loads(line)['runtime_request_id'] for line in source]
            if [row['request_id'] for row in rows] != expected_order:
                raise ValueError(f'{run_id} p{rank} request order differs from frozen P route')
            per_sum = Counter()
            for row in rows:
                rid = row['request_id']
                if rid in pairs or rid not in inputs:
                    raise ValueError(f'duplicate or unknown result request {rid}')
                frozen = inputs[rid]
                observed = reference['requests'][rid]
                for field in ('p_domain', 'input_tokens', 'engine_input_sha256'):
                    if row[field] != frozen[field] or (field != 'engine_input_sha256' and row[field] != observed[field]):
                        raise ValueError(f'{run_id} {rid} input identity mismatch at {field}')
                if row['p_domain'] != f'p{rank}':
                    raise ValueError(f'{run_id} {rid} wrong P domain')
                if row['prefix_queries'] != row['input_tokens'] + 1:
                    raise ValueError(f'{run_id} {rid} query denominator mismatch')
                if row['initial_adopted_cache_tokens'] + row['cumulative_input_processing_tokens'] != row['input_tokens']:
                    raise ValueError(f'{run_id} {rid} input accounting mismatch')
                delta = {sim: row[sim] - observed[actual] for sim, actual in FIELDS.items()}
                pair = {'p_domain': row['p_domain'], 'session_id': frozen['session_id'],
                        'input_tokens': row['input_tokens'],
                        'measured': {'adopted': observed['local_hit'],
                                     'local_compute': observed['local_compute'],
                                     'native_queries': row['input_tokens'] + 1,
                                     'native_hits': observed['local_hit']},
                        'simulated': {'adopted': row['initial_adopted_cache_tokens'],
                                      'local_compute': row['cumulative_input_processing_tokens'],
                                      'native_queries': row['prefix_queries'],
                                      'native_hits': row['prefix_hits']},
                        'delta': {'adopted': delta['initial_adopted_cache_tokens'],
                                  'local_compute': delta['cumulative_input_processing_tokens'],
                                  'native_queries': 0,
                                  'native_hits': delta['prefix_hits']}}
                pairs[rid] = pair
                per_sum.update({'requests': 1, 'input_tokens': row['input_tokens'],
                                'adopted': row['initial_adopted_cache_tokens'],
                                'local_compute': row['cumulative_input_processing_tokens'],
                                'native_queries': row['prefix_queries'],
                                'native_hits': row['prefix_hits']})
            target = reference['per_p'][f'p{rank}']
            for key, observed_key in [('requests', 'requests'), ('input_tokens', 'input_tokens'),
                                      ('adopted', 'local_hit'), ('local_compute', 'local_compute'),
                                      ('native_queries', 'native_prefix_queries'),
                                      ('native_hits', 'native_prefix_hits')]:
                if per_sum[key] != target[observed_key] + (0 if key in ('requests', 'input_tokens') else sum(p['delta'][key] for p in pairs.values() if p['p_domain'] == f'p{rank}')):
                    raise ValueError(f'{run_id} p{rank} {key} aggregation inconsistent')
            measured_per_p = {'requests': target['requests'],
                              'input_tokens': target['input_tokens'],
                              'adopted': target['local_hit'],
                              'local_compute': target['local_compute'],
                              'native_queries': target['native_prefix_queries'],
                              'native_hits': target['native_prefix_hits']}
            per_p[f'p{rank}'] = {
                'measured': measured_per_p,
                'simulated': dict(per_sum),
                'delta': {key: per_sum[key] - value
                          for key, value in measured_per_p.items()},
            }
            sums.update(per_sum)
        if set(pairs) != set(inputs) or set(pairs) != set(reference['requests']):
            raise ValueError(f'{run_id} incomplete request coverage')
        global_ref = reference['global']
        global_delta = {'adopted': sums['adopted'] - global_ref['local_hit'],
                        'local_compute': sums['local_compute'] - global_ref['local_compute'],
                        'native_queries': sums['native_queries'] - global_ref['native_prefix_queries'],
                        'native_hits': sums['native_hits'] - global_ref['native_prefix_hits']}
        mismatches = [rid for rid, pair in pairs.items() if any(pair['delta'].values())]
        report['runs'][run_id] = {'budget_gib_per_p_rank': budget,
                                  'global': {'measured': {'requests': global_ref['requests'],
                                                          'input_tokens': global_ref['input_tokens'],
                                                          'adopted': global_ref['local_hit'],
                                                          'local_compute': global_ref['local_compute'],
                                                          'native_queries': global_ref['native_prefix_queries'],
                                                          'native_hits': global_ref['native_prefix_hits']},
                                             'simulated': dict(sums), 'delta': global_delta,
                                             'measured_adoption_fraction': global_ref['actual_adoption_fraction'],
                                             'simulated_adoption_fraction': sums['adopted'] / sums['input_tokens'],
                                             'measured_query_hit_rate': global_ref['native_query_hit_rate'],
                                             'simulated_query_hit_rate': sums['native_hits'] / sums['native_queries']},
                                  'per_p': per_p,
                                  'mismatch_count': len(mismatches),
                                  'first_mismatch': mismatches[0] if mismatches else None,
                                  'requests': pairs}
        rows_by_budget[budget] = pairs
    for lo, hi in ((10, 16), (16, 24)):
        sim_changed = {rid for rid in inputs if rows_by_budget[hi][rid]['simulated']['adopted'] > rows_by_budget[lo][rid]['simulated']['adopted']}
        measured_changed = {rid for rid in inputs if rows_by_budget[hi][rid]['measured']['adopted'] > rows_by_budget[lo][rid]['measured']['adopted']}
        report['capacity_transitions'][f'{lo}_to_{hi}'] = {
            'simulated_improved_requests': len(sim_changed),
            'measured_improved_requests': len(measured_changed),
            'simulated_improved_sessions': len({inputs[r]['session_id'] for r in sim_changed}),
            'measured_improved_sessions': len({inputs[r]['session_id'] for r in measured_changed}),
            'request_set_symmetric_difference': sorted(sim_changed ^ measured_changed)}
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--prepared', type=Path, required=True)
    ap.add_argument('--results', type=Path, required=True)
    ap.add_argument('--output', type=Path)
    args = ap.parse_args()
    result = compare(args.prepared, args.results)
    output = args.output or args.prepared / 'v31-native-comparison.json'
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    for run_id, run in result['runs'].items():
        print(run_id, 'mismatches=', run['mismatch_count'], 'global_delta=', run['global']['delta'])
    print('wrote', output)

if __name__ == '__main__':
    main()
