"""Summarize one finished capacity point from its preserved evidence."""
import argparse
import csv
import json
import math
import re
from datetime import datetime
from pathlib import Path
from enrich_requests import enrich
from metric_delta import delta


def percentile(values, fraction):
    values = sorted(values)
    if not values:
        return None
    index = (len(values) - 1) * fraction
    low, high = math.floor(index), math.ceil(index)
    return values[low] + (values[high] - values[low]) * (index - low)


def summarize(run, trace, label):
    rows = enrich(run / 'replay', trace)
    execution = json.loads((run / 'replay/replay-execution.json').read_text())
    changes = {role: delta(run / f'formal-before-{role}.prom', run / f'formal-after-{role}.prom')
               for role in ('P', 'D')}

    def value(role, metric, source=None):
        matches = [row for row in changes[role] if row['metric'] == f'vllm:{metric}'
                   and (source is None or row['labels'].get('source') == source)]
        if not matches:
            return None
        assert len(matches) == 1, f'Ambiguous series, do not sum TP duplicates: {matches}'
        return matches[0]['delta']

    config_lines = [line for line in (run / 'formal-before-P.prom').read_text().splitlines()
                    if line.startswith('vllm:cache_config_info{')]
    assert len(config_lines) == 1
    cache = dict(re.findall(r'(\w+)="([^"]*)"', config_lines[0]))
    queried = value('P', 'prefix_cache_queries_total')
    hits = value('P', 'prefix_cache_hits_total')
    starts = [datetime.fromisoformat(row['started_at']) for row in rows if row['started_at']]
    ends = [datetime.fromisoformat(row['finished_at']) for row in rows if row['finished_at']]
    task_starts = [task['enqueued_clock'] for task in execution['tasks'] if task.get('enqueued_clock') is not None]
    task_ends = [task['finished_clock'] for task in execution['tasks'] if task.get('finished_clock') is not None]
    result = {
        'label': label, 'run': str(run), 'planned': len(rows),
        'success': sum(row['http_status'] == 'success' for row in rows),
        'failed': sum(row['http_status'] not in ('success', 'not_recorded') for row in rows),
        'not_recorded': sum(row['http_status'] == 'not_recorded' for row in rows),
        'p_kv_budget_bytes_per_card': int(cache['kv_cache_memory_bytes']),
        'p_num_gpu_blocks': int(cache['num_gpu_blocks']),
        'p_scheduler_capacity_tokens': int(cache['kv_cache_size_tokens']),
        'p_resolved_min_group_block_size': int(cache['block_size']),
        'p_query_tokens': queried, 'p_hit_tokens': hits,
        'p_local_hit_fraction': hits / queried if queried and hits is not None else None,
        'p_local_compute_tokens': value('P', 'prompt_tokens_by_source_total', 'local_compute'),
        'p_local_compute_measurement': 'runtime prompt_tokens_by_source counter; not all physical recomputation',
        'p_external_tokens': value('P', 'prompt_tokens_by_source_total', 'external_kv_transfer'),
        'd_local_compute_tokens': value('D', 'prompt_tokens_by_source_total', 'local_compute'),
        'd_external_tokens': value('D', 'prompt_tokens_by_source_total', 'external_kv_transfer'),
        'p_preemptions': value('P', 'num_preemptions_total'),
        'd_preemptions': value('D', 'num_preemptions_total'),
        'request_window_seconds': (max(ends) - min(starts)).total_seconds() if starts and ends else None,
        'replay_task_window_seconds': max(task_ends) - min(task_starts) if task_starts and task_ends else None,
        'actual_input_tokens_sum': sum(row['input_tokens'] or 0 for row in rows),
        'actual_output_tokens_sum': sum(row['output_tokens'] or 0 for row in rows),
        'input_length_mismatches': sum(row['input_tokens'] is not None and row['input_tokens'] != row['planned_input_tokens'] for row in rows),
        'output_length_mismatches': sum(row['output_tokens'] is not None and row['output_tokens'] != row['planned_output_tokens'] for row in rows),
    }
    for cohort in ('first_or_reset', 'continuation'):
        selected = [row for row in rows if row['cohort'] == cohort]
        ttfts = [row['ttft_seconds'] for row in selected
                 if row['http_status'] == 'success' and row['ttft_seconds'] is not None]
        result[f'{cohort}_planned'] = len(selected)
        result[f'{cohort}_ttft_n'] = len(ttfts)
        for name, q in [('p50', .5), ('p95', .95)]:
            result[f'{cohort}_ttft_{name}_seconds'] = percentile(ttfts, q)
    with (run / 'requests-enriched.csv').open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (run / 'metric-deltas.json').write_text(json.dumps(changes, indent=2))
    (run / 'point-summary.json').write_text(json.dumps(result, indent=2))
    print(json.dumps({'point': result, 'execution_summary': execution['summary']}, indent=2))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('run', type=Path)
    parser.add_argument('trace', type=Path)
    parser.add_argument('label')
    args = parser.parse_args()
    summarize(args.run, args.trace, args.label)
