"""Bounded in-allocation validation. Acceptance is written only after all gates."""
import array,collections,csv,json,os,re,sys
from pathlib import Path

def lines(p):
 with Path(p).open() as f:
  for line in f:
   if line.startswith('{'):yield json.loads(line)
def token_records(run):
 result={}
 for p in run.glob('p-input-*.jsonl'):
  with p.with_suffix('.u32').open('rb') as f:
   for r in lines(p):
    assert r['request_id'] not in result
    f.seek(r['offset_bytes']);raw=f.read(r['count']*4);assert len(raw)==r['count']*4
    result[r['request_id']]=(r,raw)
 return result

def observations(run):return [e for p in run.glob('query-diagnostic-*.jsonl') for e in lines(p)]
def scalar(path,name,label=None):
 values=[]
 for line in path.read_text().splitlines():
  if line.startswith(name+'{') and (label is None or label in line):values.append(float(line.rsplit(' ',1)[1]))
 assert len(values)==1,(name,label,values)
 return values[0]
def check_smoke(run):
 ev=observations(run);tokens=token_records(run)
 groups=[e for e in ev if e['kind']=='group_lookup'];joint=[e for e in ev if e['kind']=='joint_lookup'];dec=[e for e in ev if e['kind']=='lookup_decision' and e['scheduled_tokens']>0]
 assert groups and joint and len(dec)>=2
 assert all(e['request_id'] in tokens for e in dec)
 assert any(e.get('adopted_local_cache_tokens',0)>0 for e in dec),'warmup did not reuse prefix'
 for g in groups:assert any(j['request_id']==g['request_id'] and j['attempt']==g['attempt'] for j in joint)
 (run/'capture-smoke.json').write_text(json.dumps({'passed':True,'inputs':len(tokens),'groups':len(groups)}))

def check_formal(run):
 lo=json.loads((run/'event-formal-start.json').read_text())['reset_time']
 hi=json.loads((run/'event-formal-end.json').read_text())['requests_drained_time']
 ev=[e for e in observations(run) if lo<=e['time']<=hi]
 bodies={r['source_key']:r for r in lines(run/'request-bodies.jsonl')};assert len(bodies)==425
 facts={r['request_id']:r for r in lines(run/'replay/requests.jsonl')};assert len(facts)==425
 plan=json.loads((run/'replay/replay-plan.json').read_text());nodes={n['source_key']:n for t in plan['tasks'] for n in t['requests']}
 baseline=json.loads((run.parent.parent/'stage-v4/formal-3430/replay/replay-plan.json').read_text())
 assert plan['tasks']==baseline['tasks'],'425 plan/namespace/seed drift'
 seeds={r['seed']:k for k,r in bodies.items()};assert len(seeds)==425
 proxies={}
 for e in lines(run/'proxy-step.log'):
  if e.get('event')=='proxy_received' and lo<=e['time']<=hi:
   assert e['seed'] in seeds
   proxies[e['request_id']]=seeds[e['seed']]
 assert len(proxies)==425
 tok=token_records(run);query=[e for e in ev if e['kind']=='lookup'];joint={(e['request_id'],e['attempt']):e for e in ev if e['kind']=='joint_lookup'}
 groups=collections.defaultdict(list);dec=collections.defaultdict(list)
 for e in ev:
  if e['kind']=='group_lookup':groups[e['request_id'],e['attempt']].append(e)
  if e['kind']=='lookup_decision':dec[e['request_id']].append(e)
 rows=[];idx={}
 admission={e['request_id']:e for e in lines(run/'request-admission.jsonl')}
 from datetime import datetime
 for rid,es in dec.items():
  proxy=re.search(r'chatcmpl-([0-9a-f-]{36})-',rid).group(1);key=proxies[proxy];record,raw=tok[rid]
  body=bodies[key];n=nodes[key];f=facts[body['client_request_id']]
  assert f['status']=='success' and f['error'] is None
  assert record['count']==f['input_tokens']==n['planned_input_tokens']
  assert f['output_tokens']==n['planned_output_tokens']
  ok=[e for e in es if e['scheduled_tokens']>0];assert len(ok)==1
  for e in es:
   j=joint[rid,e['attempt']];calls=groups[rid,e['attempt']]
   assert calls and len(calls)==j['calls'] and sorted(c['call'] for c in calls)==list(range(1,len(calls)+1))
   assert j['returned']==e['hit_tokens']
  a=admission[f['request_id']];start=datetime.fromisoformat(f['started_at']).timestamp()
  enqueue=a['acquired_time']+a['enqueued_monotonic']-a['acquired_monotonic']
  adopted=ok[0]['adopted_local_cache_tokens']
  rows.append(dict(source_key=key,client_request_id=f['request_id'],server_request_id=rid,context_after=body['context_after'],input_tokens=f['input_tokens'],output_tokens=f['output_tokens'],adopted_local_cache_tokens=adopted,query_calls=len(es),query_tokens=sum(e['num_tokens'] for e in es),query_hit_tokens=sum(e['hit_tokens'] for e in es),external_tokens=ok[0].get('external_tokens',0),first_query_time=min(e['time'] for e in es),first_schedule_decision=ok[0]['time'],ttft_seconds=f['ttft_seconds'],e2e_seconds=f['latency_seconds'],slot_wait_seconds=a['admission_wait_seconds'],slot_to_send_seconds=start-a['acquired_time'],enqueue_to_first_token_seconds=start+f['ttft_seconds']-enqueue))
  assert key not in idx
  idx[key]={'record':record,'file':next(p.with_suffix('.u32').name for p in run.glob('p-input-*.jsonl') if any(r['request_id']==rid for r in lines(p)))}
 assert len(rows)==425 and set(idx)==set(bodies)
 before=run/'formal-before-P.prom';after=run/'formal-after-P.prom'
 def delta(name,label=None):return scalar(after,name,label)-scalar(before,name,label)
 # Engine0 is the sole exported P counter series in this frozen deployment.
 for name,field in [('vllm:prefix_cache_queries','query_tokens'),('vllm:prefix_cache_hits','query_hit_tokens')]:
  candidates=[name,name+'_total'];actual=next(x for x in candidates if x+'{' in after.read_text())
  assert sum(r[field] for r in rows)==delta(actual),(field,sum(r[field] for r in rows),delta(actual))
 assert sum(r['adopted_local_cache_tokens'] for r in rows)==delta('vllm:prompt_tokens_by_source_total','source="local_cache_hit"')
 external=delta('vllm:prompt_tokens_by_source_total','source="external_kv_transfer"')
 local=delta('vllm:prompt_tokens_by_source_total','source="local_compute"')
 assert sum(r['external_tokens'] or 0 for r in rows)==external
 assert sum(r['input_tokens']-r['adopted_local_cache_tokens']-(r['external_tokens'] or 0) for r in rows)==local
 frozen=os.environ.get('FROZEN_RUN')
 if frozen:
  old=Path(frozen);oldidx=json.loads((old/'input-index.json').read_text())
  assert json.loads((run/'source-identity.json').read_text())==json.loads((old/'source-identity.json').read_text())
  for role in ['P','D']:
   cfg=json.loads((run/f'{role}-config.json').read_text());orig=json.loads((old/f'{role}-config.json').read_text())
   assert cfg['devices']==orig['devices'],('physical assignment differs',role)
   def without_budget(cmd):
    i=cmd.index('--kv-cache-memory-bytes');return cmd[:i]+cmd[i+2:]
   assert without_budget(cfg['command'])==without_budget(orig['command'])
  def cache_settings(path):
   e=next(e for e in observations(path) if e['kind']=='effective_cache_config')
   e={k:v for k,v in e.items() if k not in ['time','kind']}
   e['kv_cache_config'].pop('num_blocks',None)
   e['kv_cache_config'].pop('kv_cache_tensors',None) # tensor byte allocations derive from budget
   return e
  assert cache_settings(run)==cache_settings(old),'effective cache settings differ beyond budget'

  oldb={r['source_key']:r for r in lines(old/'request-bodies.jsonl')}
  for key,info in idx.items():
   prev=oldidx[key];rec=info['record'];pre=prev['record']
   assert rec['count']==pre['count'] and rec['semantic_identity']==pre['semantic_identity']
   with (old/prev['file']).open('rb') as f:f.seek(pre['offset_bytes']);oldraw=f.read(pre['count']*4)
   assert oldraw==tok[rec['request_id']][1],('P token mismatch',key)
   x=dict(bodies[key]['body']);y=dict(oldb[key]['body']);x.pop('vllm_xargs',None);y.pop('vllm_xargs',None)
   assert x==y,('business body mismatch',key)
 # Cleanup is part of acceptance, not merely the client return code.
 c=json.loads((run/'controller-cleanup.json').read_text());assert not c['remaining']
 for role in ['P','D']:
  clean=json.loads((run/f'{role}-cleanup.json').read_text())
  assert not clean['remaining'] and clean['returncode']==0,(role,clean)
 audit=json.loads((run/'cleanup-audit.json').read_text());assert audit['resource_cleanup_passed']
 (run/'input-index.json').write_text(json.dumps(idx,indent=2))
 with (run/'per-request-evidence.csv').open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=rows[0]);w.writeheader();w.writerows(rows)
 result={'passed':True,'requests':425,'input_tokens':sum(r['input_tokens'] for r in rows),'adopted':sum(r['adopted_local_cache_tokens'] for r in rows),'frozen_input_verified':bool(frozen),'query_calls':len(query)}
 (run/'ACCEPTED.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
if __name__=='__main__':
 mode,run=sys.argv[1],Path(sys.argv[2])
 if mode=='smoke':check_smoke(run)
 elif mode=='formal':check_formal(run)
 else:raise ValueError(mode)
