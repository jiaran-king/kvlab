"""Extract per-engine counter deltas without summing TP duplicates."""
import argparse
import json
import re
from pathlib import Path


def counters(path):
    result = {}
    for line in path.read_text().splitlines():
        match = re.fullmatch(r'(vllm:[\w:]+)\{([^}]*)\}\s+([^ ]+)', line)
        if not match:
            continue
        name, raw_labels, value = match.groups()
        if not name.endswith('_total'):
            continue
        labels = tuple(sorted(re.findall(r'(\w+)="([^"]*)"', raw_labels)))
        result[(name, labels)] = float(value)
    return result


def delta(before, after):
    initial, final = counters(before), counters(after)
    wanted = ('prefix_cache_queries_total', 'prefix_cache_hits_total',
              'external_prefix_cache_hits_total', 'prompt_tokens_by_source_total',
              'num_preemptions_total')
    rows = []
    for (name, labels), value in final.items():
        if name.removeprefix('vllm:') not in wanted:
            continue
        start = initial.get((name, labels))
        diff = None if start is None else value - start
        if diff is not None and diff < 0:
            raise ValueError(f'Counter reset within measurement: {name} {labels}')
        rows.append({'metric': name, 'labels': dict(labels), 'before': start,
                     'after': value, 'delta': diff})
    return rows


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('before', type=Path)
    parser.add_argument('after', type=Path)
    args = parser.parse_args()
    print(json.dumps(delta(args.before, args.after), indent=2))
