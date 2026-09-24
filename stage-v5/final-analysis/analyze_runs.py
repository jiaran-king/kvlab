"""Read final request/token/query/events under one bounded CPU allocation."""
import array,collections,csv,json,re,sys
from pathlib import Path
from datetime import datetime
base,out=map(Path,sys.argv[1:3]);out.mkdir(parents=True,exist_ok=True)
def load(p):return json.loads(p.read_text())
def stream(p):
 with p.open() as f:
  for line in f:
   if line.startswith('{'):yield json.loads(line)
def pct(vals,q):
 vals=sorted(map(float,vals));z=(len(vals)-1)*q;i=int(z);return vals[i]+(vals[min(i+1,len(vals)-1)]-vals[i])*(z-i)
def scalar(p,name,label=None):
 vals=[float(l.rsplit(' ',1)[1]) for l in p.read_text().splitlines() if l.startswith('vllm:'+name+'{') and (label is None or label in l)]
 assert len(vals)==1,(name,label,vals);return vals[0]
def writecsv(path,rows):
 with path.open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=rows[0]);w.writeheader();w.writerows(rows)
summary=[];allrows={};meta={}
for name,job in [('C12','3458'),('F12','3462'),('F24','3463')]:
 run=base/f'formal-{job}';accept=load(run/'ACCEPTED.json');assert accept['passed'];assert load(run/'cleanup-audit.json')['resource_cleanup_passed']
 rows=list(csv.DictReader((run/'per-request-evidence.csv').open()));facts={r['request_id']:r for r in stream(run/'replay/requests.jsonl')};plan=load(run/'replay/replay-plan.json');nodes={n['source_key']:n for t in plan['tasks'] for n in t['requests']};idx=load(run/'input-index.json')
 tokens={}
 for key,entry in idx.items():
  rec=entry['record']
  with (run/entry['file']).open('rb') as f:f.seek(rec['offset_bytes']);raw=f.read(rec['count']*4)
  a=array.array('I');a.frombytes(raw)
  if sys.byteorder!='little':a.byteswap()
  tokens[key]=a
 groups=collections.defaultdict(list);decisions={}
 for path in run.glob('query-diagnostic-*.jsonl'):
  for e in stream(path):
   if e['kind']=='group_lookup':groups[e['request_id'],e['attempt']].append(e)
   if e['kind']=='lookup_decision' and e['scheduled_tokens']>0:decisions[e['request_id']]=e
 for r in rows:
  key=r['source_key'];n=nodes[key];prev=n['context_after'];cur=tokens[key];lcp=0
  if prev:
   for x,y in zip(cur,tokens[prev]):
    if x!=y:break
    lcp+=1
  e=decisions[r['server_request_id']];calls=sorted(groups[r['server_request_id'],e['attempt']],key=lambda g:g['call']);shrinks=[g for g in calls if g['returned']<g['candidate']]
  r.update(actor_id=n['actor_id'],session_id=facts[r['client_request_id']]['session_id'],context_mode=n['context_mode'],predecessor_input_tokens=len(tokens[prev]) if prev else 0,lcp_tokens=lcp,admission_lookup_hit=e['hit_tokens'],lcp_minus_adopted=lcp-int(r['adopted_local_cache_tokens']),first_reducing_groups=','.join(map(str,shrinks[0]['groups'])) if shrinks else '',first_candidate=shrinks[0]['candidate'] if shrinks else '',first_returned=shrinks[0]['returned'] if shrinks else '',lookup_call_sequence=json.dumps([{k:g[k] for k in ('call','groups','candidate','returned')} for g in calls]))
 writecsv(out/f'{name}-requests.csv',rows);allrows[name]={r['source_key']:r for r in rows}
 before=run/'formal-before-P.prom';after=run/'formal-after-P.prom'
 def delta(k,l=None):return scalar(after,k,l)-scalar(before,k,l)
 a=load(run/'event-formal-start.json');b=load(run/'event-formal-end.json');observer=load(run/'observer-final.json');counts=collections.Counter();seq=set();clears=[];active=False
 formal_start_sequence=a.get('last_sequence',-1)
 formal_end_sequence=b['last_sequence']
 for e in stream(run/'kv-events.jsonl'):
  s=e['sequence'];seq.add(s);v=e['event'];kind=v['type']
  if kind=='AllBlocksCleared':clears.append({'sequence':s,'time':e['timestamp']});active=True;continue
  if active and formal_start_sequence < s <= formal_end_sequence:counts[str(v.get('group_idx')),kind]+=len(v.get('block_hashes',[]))
 assert len(clears)==1 and not observer['errors'];missing=sorted(set(range(max(seq)+1))-seq);assert not missing
 cont=[r for r in rows if r['context_after'] and r['context_mode']!='reset'];total=sum(int(r['input_tokens']) for r in rows);cache=sum(int(r['adopted_local_cache_tokens']) for r in rows)
 execution=load(run/'replay/replay-execution.json')
 times=[datetime.fromisoformat(f['started_at']).timestamp() for f in facts.values()];ends=[datetime.fromisoformat(f['finished_at']).timestamp() for f in facts.values()]
 result=dict(label=name,job=job,p_kv_gib=24 if name=='F24' else 12,requests=len(rows),continuations=len(cont),input_tokens=total,output_tokens=sum(int(r['output_tokens']) for r in rows),local_cache_hit=cache,local_compute=delta('prompt_tokens_by_source_total','source="local_compute"'),external=delta('prompt_tokens_by_source_total','source="external_kv_transfer"'),input_cache_fraction=cache/total,query_tokens=delta('prefix_cache_queries_total'),query_hit_tokens=delta('prefix_cache_hits_total'),p_prefill_mean=delta('request_prefill_time_seconds_sum')/delta('request_prefill_time_seconds_count'),ttft_p50=pct([r['ttft_seconds'] for r in cont],.5),ttft_p95=pct([r['ttft_seconds'] for r in cont],.95),e2e_p50=pct([r['e2e_seconds'] for r in rows],.5),e2e_p95=pct([r['e2e_seconds'] for r in rows],.95),slot_wait_p50=pct([r['slot_wait_seconds'] for r in rows],.5),slot_wait_p95=pct([r['slot_wait_seconds'] for r in rows],.95),enqueue_ttft_p50=pct([r['enqueue_to_first_token_seconds'] for r in cont],.5),enqueue_ttft_p95=pct([r['enqueue_to_first_token_seconds'] for r in cont],.95),request_window_seconds=max(ends)-min(times),task_window_seconds=max(t['finished_clock'] for t in execution['tasks'])-min(t['enqueued_clock'] for t in execution['tasks']),removed_entries=sum(v for (g,k),v in counts.items() if k=='BlockRemoved'),stored_entries=sum(v for (g,k),v in counts.items() if k=='BlockStored'),full_predecessor_lcp=sum(int(r['lcp_tokens'])==int(r['predecessor_input_tokens']) for r in cont),shorter_predecessor_lcp=sum(int(r['lcp_tokens'])<int(r['predecessor_input_tokens']) for r in cont))
 for g in range(5):result['removed_group_'+str(g)]=counts[str(g),'BlockRemoved']
 result['query_hit_rate']=result['query_hit_tokens']/result['query_tokens'];summary.append(result)
 meta[name]={'events':{'clears':clears,'missing_sequences':missing,'errors':observer['errors']},'execution_keys':list(execution),'acceptance':accept}
 # Export raw final counters/identity for compact independent review.
 for f in ['formal-before-P.prom','formal-after-P.prom','formal-before-D.prom','formal-after-D.prom','source-identity.json','ACCEPTED.json','cleanup-audit.json','event-formal-start.json','event-formal-end.json']:(out/f'{name}-{f}').write_bytes((run/f).read_bytes())
paired=[]
for key,a in allrows['F12'].items():
 b=allrows['F24'][key];assert a['input_tokens']==b['input_tokens'] and a['lcp_tokens']==b['lcp_tokens']
 paired.append(dict(source_key=key,actor_id=a['actor_id'],session_id=a['session_id'],context_after=a['context_after'],input_tokens=a['input_tokens'],lcp_tokens=a['lcp_tokens'],F12_adopted=int(a['adopted_local_cache_tokens']),F24_adopted=int(b['adopted_local_cache_tokens']),delta_A=int(b['adopted_local_cache_tokens'])-int(a['adopted_local_cache_tokens']),F12_ttft=float(a['ttft_seconds']),F24_ttft=float(b['ttft_seconds']),F12_first_reducing_groups=a['first_reducing_groups'],F24_first_reducing_groups=b['first_reducing_groups']))
assert sum(r['delta_A'] for r in paired)==summary[2]['local_cache_hit']-summary[1]['local_cache_hit']
writecsv(out/'summary.csv',summary);writecsv(out/'paired-requests.csv',paired)
(out/'analysis.json').write_text(json.dumps({'summary':summary,'metadata':meta,'pair_net':sum(r['delta_A'] for r in paired),'pair_positive':sum(max(r['delta_A'],0) for r in paired),'pair_negative':sum(min(r['delta_A'],0) for r in paired),'pair_counts':dict(collections.Counter('positive' if r['delta_A']>0 else 'negative' if r['delta_A']<0 else 'zero' for r in paired))},indent=2))
print(json.dumps(summary,indent=2))
