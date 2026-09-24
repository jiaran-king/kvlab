import csv,json,re,collections
from pathlib import Path
r=Path(__file__).parent/'formal-3442';out=r.parent
load=lambda n:json.loads((r/n).read_text())
a=load('event-formal-start.json')['reset_time'];b=load('event-formal-end.json')['requests_drained_time'];ev=[json.loads(l) for p in r.glob('query-diagnostic-*.jsonl') for l in p.read_text().splitlines()];formal=[e for e in ev if a<=e['time']<=b]
q=[e for e in formal if e['kind']=='lookup'];dec=[e for e in formal if e['kind']=='lookup_decision'];by=collections.defaultdict(list)
for e in dec:by[e['request_id']].append(e)
plan=load('replay/replay-plan.json');seedmap={n['backend_sampling_seed']:n['runtime_request_id'] for t in plan['tasks'] for n in t['requests']};assert len(seedmap)==425
proxy={}
for line in (r/'proxy-step.log').read_text().splitlines():
 if not line.startswith('{'):continue
 e=json.loads(line)
 if e.get('event')=='proxy_received' and e.get('seed') in seedmap:proxy[e['request_id']]=seedmap[e['seed']]
requests={x['runtime_request_id']:x for x in csv.DictReader((r/'requests-enriched.csv').open())};totals=[e for e in ev if e['kind']=='scheduled_totals'][-1]['requests'];rows=[]
for rid,es in by.items():
 pid=re.search(r'chatcmpl-([0-9a-f-]{36})-',rid).group(1);client=proxy[pid];req=requests[client];ok=[e for e in es if e['scheduled_tokens']>0];assert len(ok)==1
 failed=[e for e in es if not e['scheduled_tokens']];extra=sum(e['num_tokens'] for e in failed);adopted=ok[0]['adopted_local_cache_tokens'];local=int(req['input_tokens'])-adopted
 assert totals[rid]==local,(rid,totals[rid],local)
 rows.append({'server_request_id':rid,'client_request_id':client,'trace_request_id':req['trace_request_id'],'actor_id':req['actor_id'],'session_id':req['source_session_id'],'query_calls':len(es),'query_tokens':sum(e['num_tokens'] for e in es),'query_hit_tokens':sum(e['hit_tokens'] for e in es),'extra_query_tokens':extra,'failed_admission_hits':sum(e['hit_tokens'] for e in failed),'defer_reasons':','.join(sorted({e.get('defer_reason','unknown') for e in failed})),'lookup_to_admit_seconds':ok[0]['time']-es[0]['time'],'adopted_local_cache_tokens':adopted,'scheduled_token_total':totals[rid],'input_tokens':int(req['input_tokens']),'ttft_seconds':float(req['ttft_seconds'])})
p=load('point-summary.json');assert sum(e['num_tokens'] for e in q)==p['p_query_tokens'];assert sum(e['hit_tokens'] for e in q)==p['p_hit_tokens'];assert sum(x['extra_query_tokens'] for x in rows)==p['p_query_tokens']-p['actual_input_tokens_sum']
result={'requests':len(rows),'lookup_calls':len(q),'query_tokens':sum(e['num_tokens'] for e in q),'query_hits':sum(e['hit_tokens'] for e in q),'extra_query_tokens':sum(x['extra_query_tokens'] for x in rows),'repeat_request_count':sum(x['query_calls']>1 for x in rows),'repeat_attempt_count':len(q)-len(rows),'defer_reasons':dict(collections.Counter(e.get('defer_reason','scheduled') for e in dec)),'failed_attempt_hits':sum(x['failed_admission_hits'] for x in rows),'sum_lookup_seconds':sum(e['lookup_seconds'] for e in q),'max_lookup_to_admit_seconds':max(x['lookup_to_admit_seconds'] for x in rows),'scheduled_tokens':sum(totals[rid] for rid in by),'per_request_scheduled_tokens_equal_input_minus_adopted_cache':True,'query_and_hit_match_formal_counters':True,'caveat':'Scheduled token totals measure scheduler output, not GPU FLOPs. Allocation failure sub-branch (full-sequence admission gate vs chunk allocation) was not instrumented.'}
(out/'diagnostic-summary.json').write_text(json.dumps(result,indent=2))
with (out/'per-request-diagnostic.csv').open('w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=rows[0].keys());w.writeheader();w.writerows(rows)
print(json.dumps(result,indent=2));print('repeat requests',[(x['input_tokens'],x['query_calls'],round(x['lookup_to_admit_seconds'],3),round(x['ttft_seconds'],3)) for x in rows if x['query_calls']>1])
old=json.loads(Path('stage-v4/formal-3430/replay/replay-plan.json').read_text());assert old['tasks']==plan['tasks'];print('L2/L3 task plans exact match')
