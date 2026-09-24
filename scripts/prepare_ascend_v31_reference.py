"""Materialize measured v3.1 cache reference without any simulated values."""
from __future__ import annotations
import json
from pathlib import Path

RUNS = ('cal10-v31-0924-01','cal16-v31-0924-01',
        'cal24-v31-0924-01','formal01-v31-0924-01')
FIELDS = ('input_tokens','local_hit','local_compute','external_kv_transfer')

def materialize(output: Path, base: Path):
    result = {'schema':'kvlab-v31-measured-reference/v1',
              'metric_scope':'archived native P engine events and rank counter deltas',
              'runs':{}}
    for run in RUNS:
        folder=base/run
        engine=json.loads((folder/'engine-event-audit.json').read_text())
        counters=json.loads((folder/'all-rank-metric-deltas.json').read_text())
        assert engine['status']=='PASS' and counters['status']=='SNAPSHOT_DELTAS_VALID'
        requests={row['request_id']:{'p_domain':f"p{row['rank']}",
                  **{key:row[key] for key in FIELDS},
                  'engine_input_sha256':row['engine_input_sha256']}
                  for row in engine['rows']}
        assert len(requests)==1313
        per_p={}
        for rank in range(4):
            domain=f'p{rank}'
            members=[r for r in requests.values() if r['p_domain']==domain]
            deltas=counters['ranks'][domain]['deltas']
            input_tokens=sum(r['input_tokens'] for r in members)
            hit=sum(r['local_hit'] for r in members)
            compute=sum(r['local_compute'] for r in members)
            external=sum(r['external_kv_transfer'] for r in members)
            queries=int(deltas['prefix_cache_queries_total'])
            native_hits=int(deltas['prefix_cache_hits_total'])
            assert input_tokens==int(deltas['prompt_tokens_total'])
            assert hit==native_hits
            assert compute==int(deltas['prompt_tokens_by_source']['local_compute'])
            assert external==int(deltas['prompt_tokens_by_source']['external_kv_transfer'])
            assert input_tokens==hit+compute+external
            per_p[domain]={'requests':len(members),'input_tokens':input_tokens,
                          'local_hit':hit,'local_compute':compute,'external_kv_transfer':external,
                          'native_prefix_queries':queries,'native_prefix_hits':native_hits,
                          'native_query_hit_rate':native_hits/queries if queries else None,
                          'actual_adoption_fraction':hit/input_tokens if input_tokens else None}
        global_={key:sum(p[key] for p in per_p.values()) for key in
                 ('requests','input_tokens','local_hit','local_compute','external_kv_transfer',
                  'native_prefix_queries','native_prefix_hits')}
        global_['native_query_hit_rate']=global_['native_prefix_hits']/global_['native_prefix_queries']
        global_['actual_adoption_fraction']=global_['local_hit']/global_['input_tokens']
        result['runs'][run]={'global':global_,'per_p':per_p,'requests':requests}
    a=result['runs']['cal16-v31-0924-01']['requests']
    b=result['runs']['formal01-v31-0924-01']['requests']
    assert a==b, 'independent 16 GiB repeat differs per request'
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,separators=(',',':'))+'\n')
    return {run:result['runs'][run]['global'] for run in RUNS}

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--archive-root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(materialize(args.output,args.archive_root),indent=2))
