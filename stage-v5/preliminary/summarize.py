import csv,json,re
from pathlib import Path
O=Path(__file__).resolve().parent
BASE=O.parents[1]
def pct(xs,q):
 xs=sorted(map(float,xs));t=(len(xs)-1)*q;i=int(t);return xs[i]+(xs[min(i+1,len(xs)-1)]-xs[i])*(t-i)
def loadlines(p):return [json.loads(l) for l in p.read_text().splitlines() if l.startswith('{')]
def report(rows):
 cont=[r for r in rows if r.get('context_after') not in [None,'','NA']]
 total=sum(int(r['input_tokens']) for r in rows);cache=sum(int(r['adopted_local_cache_tokens']) for r in rows)
 return dict(n=len(rows),continuations=len(cont),input=total,adopted=cache,cache_fraction=cache/total,local_compute=total-cache,ttft_p50=pct([r['ttft_seconds'] for r in cont],.5),ttft_p95=pct([r['ttft_seconds'] for r in cont],.95),e2e_p95=pct([r['e2e_seconds'] for r in rows],.95))
full={}
for label,j in [('C12','3458'),('F12','3462')]:
 rows=list(csv.DictReader((O/f'formal-{j}/per-request-evidence.csv').open()));full[label]=report(rows)
 if label=='F12':f12={r['client_request_id']:r for r in rows}
plan=json.loads((BASE/'stage-v4/formal-3430/replay/replay-plan.json').read_text());seeds={n['backend_sampling_seed']:n['runtime_request_id'] for t in plan['tasks'] for n in t['requests']}
p=O/'formal-3463';facts={r['request_id']:r for r in loadlines(p/'replay/requests.jsonl') if r['status']=='success'}
proxy={e['request_id']:seeds[e['seed']] for e in loadlines(p/'proxy-step.log') if e.get('event')=='proxy_received' and e.get('seed') in seeds}
# Warmup has reused seeds; include only P IDs whose proxy_received is after formal factual start.
from datetime import datetime
start=min(datetime.fromisoformat(f['started_at']).timestamp() for f in facts.values())
proxy={e['request_id']:seeds[e['seed']] for e in loadlines(p/'proxy-step.log') if e.get('event')=='proxy_received' and e.get('seed') in seeds and e['time']>=start}
adopt={}
for path in p.glob('query-diagnostic-*.jsonl'):
 for e in loadlines(path):
  if e.get('kind')!='lookup_decision' or not e.get('scheduled_tokens'):continue
  match=re.search(r'chatcmpl-([0-9a-f-]{36})-',e['request_id'])
  if not match or match[1] not in proxy:continue
  rid=proxy[match[1]]
  if rid in facts:
   assert rid not in adopt
   adopt[rid]=e['adopted_local_cache_tokens']
assert set(adopt)==set(facts),(len(adopt),len(facts))
paired=[]
for rid,f in facts.items():
 paired.append({'context_after':f12[rid]['context_after'],'input_tokens':f['input_tokens'],'adopted_local_cache_tokens':adopt[rid],'ttft_seconds':f['ttft_seconds'],'e2e_seconds':f['latency_seconds']})
result={'full':full,'matched_completed_subset':{'F12':report([f12[rid] for rid in facts]),'F24':report(paired)},'F24_snapshot_last_finish':max(r['finished_at'] for r in facts.values())}
(O/'summary.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
