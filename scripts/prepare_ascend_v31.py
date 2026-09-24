"""Convert the verified final v3.1 capture to KVLab's frozen workload format.

This freezes *engine* input tokens and the actual P route/order. It does not
simulate cache behavior or use measured hit/compute values in the workload.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path

RUNS = (
    'cal10-v31-0924-01', 'cal16-v31-0924-01',
    'cal24-v31-0924-01', 'formal01-v31-0924-01',
)

def digest_tokens(tokens):
    return hashlib.sha256(json.dumps(tokens, separators=(',', ':')).encode()).hexdigest()

def convert(plan_path: Path, output_dir: Path, base: Path, bodies: Path):
    plan = json.loads(plan_path.read_text())
    planned = {}
    for task in plan['tasks']:
        by_key = {r['source_key']: r['runtime_request_id'] for r in task['requests']}
        for row in task['requests']:
            rid = row['runtime_request_id']
            assert rid not in planned
            planned[rid] = (task, row, by_key)
    assert len(planned) == 1313
    routes_by_run = {}
    outputs_by_run = {}
    engines_by_run = {}
    manifest_digests = set()
    for run in RUNS:
        folder = base / run
        route = json.loads((folder / 'route-audit.json').read_text())
        assert route['status'] == 'PASS' and len(route['routes']) == len(planned)
        routes_by_run[run] = route['routes']
        sse = json.loads((folder / 'sse-audit.json').read_text())
        outputs_by_run[run] = {r['request_id']: r['output_token_count'] for r in sse['results']}
        eng = json.loads((folder / 'engine-event-audit.json').read_text())
        engines_by_run[run] = {r['request_id']: r for r in eng['rows']}
        assert set(outputs_by_run[run]) == set(engines_by_run[run]) == set(planned)
        manifest_digests.add(hashlib.sha256((folder / 'frozen-input-manifest.json').read_bytes()).hexdigest())
    assert len(manifest_digests) == 1, 'runs use different frozen input manifests'
    reference = RUNS[1]
    manifest = json.loads((base / reference / 'frozen-input-manifest.json').read_text())
    expected_files = {row['path']: row['sha256'] for row in manifest['files']}
    assert len(expected_files) == 2626
    assert {p.name for p in bodies.iterdir() if p.suffix == '.json' and p.name != 'frozen-manifest.json'} == set(expected_files)
    for name, expected_sha in expected_files.items():
        assert hashlib.sha256((bodies / name).read_bytes()).hexdigest() == expected_sha, name
    rank_order = lambda rows, rank: [r['request_id'] for r in sorted(
        (x for x in rows if x['rank'] == rank), key=lambda x: x['order_index'])]
    for run in RUNS:
        for rank in range(4):
            assert rank_order(routes_by_run[run], rank) == rank_order(routes_by_run[reference], rank)
        assert outputs_by_run[run] == outputs_by_run[reference]
        for rid, row in engines_by_run[reference].items():
            peer = engines_by_run[run][rid]
            assert (row['engine_input_sha256'], row['input_tokens'], row['rank']) == (
                peer['engine_input_sha256'], peer['input_tokens'], peer['rank'])
    route_rows = sorted(routes_by_run[reference], key=lambda r: r['admitted_monotonic'])
    assert len({r['request_id'] for r in route_rows}) == len(planned)
    seen = set()
    workload_rows = []
    route_assignments = []
    token_total = 0
    for order, route in enumerate(route_rows):
        rid = route['request_id']
        task, source, by_key = planned[rid]
        frozen = json.loads((bodies / (rid + '.input.json')).read_text())
        body = json.loads((bodies / (rid + '.json')).read_text())
        assert frozen['request_id'] == body['request_id'] == rid
        assert body['session_id'] == task['runtime_session_id'] == route['session_id']
        assert body['source_key'] == source['source_key']
        assert frozen['input_sha256'] == digest_tokens(frozen['tokens'])
        assert frozen['body_sha256'] == body['body_sha256']
        assert frozen['tokens'][-1] == 128822
        tokens = frozen['tokens'][:-1]
        assert len(frozen['tokens']) == engines_by_run[reference][rid]['tokenizer_tokens']
        assert len(tokens) == engines_by_run[reference][rid]['input_tokens']
        assert digest_tokens(tokens) == engines_by_run[reference][rid]['engine_input_sha256']
        assert engines_by_run[reference][rid]['input_normalization'] == 'drop_terminal_128822'
        deps = {}
        for field in ('send_after', 'context_after'):
            key = source[field]
            deps[field] = by_key[key] if key is not None else None
            assert deps[field] is None or deps[field] in seen, f'{rid} {field} is not prior'
        workload_rows.append({
            'runtime_request_id': rid,
            'runtime_session_id': route['session_id'],
            'actor_id': source['actor_id'],
            'source_key': source['source_key'],
            'node_type': 'request',
            'tokens': tokens,
            'input_tokens': len(tokens),
            'output_tokens': outputs_by_run[reference][rid],
            'content_source': 'historical_capture',
            'cache_identity': '',
            'send_after': deps['send_after'],
            'context_after': deps['context_after'],
            'effective_interval_seconds': 0,
        })
        route_assignments.append({'order': order, 'request_id': rid,
                                  'assigned_p': f"p{route['rank']}"})
        token_total += len(tokens)
        seen.add(rid)
    assert token_total == 32360331
    output_dir.mkdir(parents=True, exist_ok=True)
    workload_path = output_dir / 'v31-engine-workload.json.gz'
    payload = {
        'schema': 'kvlab-replay-workload/v1',
        'metadata': {
            'content_source': 'historical_capture',
            'execution_profile': 'request-admission',
            'capture_provenance': {
                'runs': list(RUNS),
                'frozen_manifest_sha256': next(iter(manifest_digests)),
                'input_normalization': 'per-request verified terminal 128822 removal',
                'output_lengths': 'archived sse-audit.json, identical across all four runs',
                'ordering': 'cal16 captured admission interleave; per-P order verified in all four runs',
            },
            'historical_order_source': {'run': reference, 'field': 'admitted_monotonic'},
        },
        'requests': workload_rows,
    }
    with gzip.GzipFile(filename='', mode='wb', fileobj=workload_path.open('wb'), mtime=0) as stream:
        stream.write(json.dumps(payload, separators=(',', ':'), ensure_ascii=False).encode())
    workload_sha = hashlib.sha256(workload_path.read_bytes()).hexdigest()
    routing = {
        'schema': 'kvlab-native-routing/v1',
        'workload_sha256': workload_sha,
        'domains': [f'p{i}' for i in range(4)],
        'source': 'actual_capture',
        'method': 'final v3.1 route-audit rank and per-P order',
        'reference_config': {'runs': list(RUNS), 'route_reference_run': reference},
        'timestamp_semantics': 'global admission interleave from reference run only',
        'assignments': route_assignments,
    }
    (output_dir / 'v31-routing.json').write_text(json.dumps(routing, separators=(',', ':')))
    assignments = {row['request_id']: row['assigned_p'] for row in route_assignments}
    for rank in range(4):
        domain = f'p{rank}'
        stream_path = output_dir / f'v31-{domain}-requests.jsonl.gz'
        with gzip.GzipFile(filename='', mode='wb', fileobj=stream_path.open('wb'), mtime=0) as stream:
            for row in workload_rows:
                if assignments[row['runtime_request_id']] == domain:
                    stream.write(json.dumps(row, separators=(',', ':')).encode() + b'\n')
    return {'requests': len(workload_rows), 'engine_input_tokens': token_total,
            'actual_output_tokens': sum(outputs_by_run[reference].values()),
            'per_p_requests': {f'p{i}': sum(x['assigned_p'] == f'p{i}' for x in route_assignments)
                               for i in range(4)}, 'workload_sha256': workload_sha}

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--archive-root', type=Path, required=True)
    parser.add_argument('--bodies-dir', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(convert(args.plan, args.output_dir, args.archive_root, args.bodies_dir), indent=2))
