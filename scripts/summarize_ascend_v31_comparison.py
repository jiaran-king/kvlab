"""Export aggregate Ascend v3.1 evidence without captured tokens or request IDs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def summarize(source: Path) -> dict:
    result = json.loads(source.read_text())
    if result['schema'] != 'kvlab-v31-native-comparison/v1':
        raise ValueError('unexpected comparison schema')
    runs = {}
    for run_id, run in result['runs'].items():
        if len(run['requests']) != 1313 or run['mismatch_count'] != 0:
            raise ValueError(f'{run_id} is incomplete or differs at request level')
        runs[run_id] = {
            'budget_gib_per_p_rank': run['budget_gib_per_p_rank'],
            'request_count': len(run['requests']),
            'mismatch_count': run['mismatch_count'],
            'global': run['global'],
            'per_p': run['per_p'],
        }
    transitions = {}
    for name, value in result['capacity_transitions'].items():
        if value['request_set_symmetric_difference']:
            raise ValueError(f'{name} improved request sets differ')
        transitions[name] = {
            key: number for key, number in value.items()
            if key != 'request_set_symmetric_difference'
        }
    return {
        'schema': 'kvlab-v31-public-aggregate/v1',
        'scope': 'final v3.1 four-P/4K captured configuration; frozen input and route',
        'privacy_note': 'no token IDs, request IDs, session IDs or raw event rows',
        'runs': runs,
        'capacity_transitions': transitions,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--comparison', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    data = summarize(args.comparison)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    print(args.output)


if __name__ == '__main__':
    main()
