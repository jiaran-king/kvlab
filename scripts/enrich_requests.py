"""Join a finished Replay's plan, execution and HTTP outcomes to original rows."""
import argparse
import csv
import json
from pathlib import Path


def enrich(run, trace):
    source = [json.loads(line) for line in trace.read_text().splitlines()]
    plan = json.loads((run / 'replay-plan.json').read_text())
    execution = json.loads((run / 'replay-execution.json').read_text())
    nodes = {n['runtime_request_id']: n for t in execution['tasks'] for n in t['nodes']}
    responses = [json.loads(line) for line in (run / 'requests.jsonl').read_text().splitlines()]
    outcomes = {r['request_id']: r for r in responses}
    assert len(outcomes) == len(responses), 'Duplicate HTTP outcome IDs'
    rows = []
    for task in plan['tasks']:
        actor_turns = {}
        for request in task['requests']:
            if request['node_type'] != 'request':
                continue
            # Analyzer source keys encode the one-based original JSONL line.
            line = int(request['source_key'].split('-')[0][1:])
            original = source[line - 1]
            assert original['session_id'] == task['source_session_id']
            assert original['input_tokens'] == request['planned_input_tokens']
            assert original['output_tokens'] == request['planned_output_tokens']
            rid = request['runtime_request_id']
            node = nodes.get(rid, {})
            response = outcomes.get(rid, {})
            calibration = node.get('prompt_calibration') or {}
            adjustment = calibration.get('adjustment')
            independent = request['context_after'] is None or request['context_mode'] in ('independent', 'reset', 'none')
            reset = adjustment in ('reset', 'reset_and_pad')
            # Missing execution/calibration remains explicit rather than inferred successful.
            cohort = 'first_or_reset' if independent or reset else 'continuation'
            actor = request['actor_id']
            actor_turns[actor] = actor_turns.get(actor, 0) + 1
            rows.append({
                'trace_request_id': original['request_id'], 'source_key': request['source_key'],
                'source_session_id': original['session_id'], 'runtime_request_id': rid,
                'runtime_session_id': task['runtime_session_id'], 'actor_id': actor,
                'actor_turn': actor_turns[actor], 'context_after': request['context_after'],
                'context_mode': request['context_mode'], 'calibration_adjustment': adjustment,
                'cohort': cohort, 'execution_status': node.get('status', 'missing'),
                'http_status': response.get('status', 'not_recorded'),
                'error': response.get('error') or node.get('error'),
                'planned_input_tokens': request['planned_input_tokens'],
                'planned_output_tokens': request['planned_output_tokens'],
                'input_tokens': response.get('input_tokens'), 'output_tokens': response.get('output_tokens'),
                'ttft_seconds': response.get('ttft_seconds'), 'latency_seconds': response.get('latency_seconds'),
                'started_at': response.get('started_at'), 'finished_at': response.get('finished_at'),
                'prompt_preparation_seconds': calibration.get('prompt_preparation_seconds'),
                'calibration_target_met': calibration.get('target_met'),
            })
    assert len(rows) == len(source) == 174, 'Fixed workload coverage mismatch'
    assert set(outcomes) <= {r['runtime_request_id'] for r in rows}, 'Unmapped outcome'
    return rows


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('replay_dir', type=Path)
    parser.add_argument('trace', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    rows = enrich(args.replay_dir, args.trace)
    with args.output.open('w', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(json.dumps({'rows': len(rows), 'output': str(args.output)}))
