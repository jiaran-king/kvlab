"""CPU-only reconstruction of HTTP overlap from all 425 saved request records."""
import csv,json
from pathlib import Path
O=Path(__file__).resolve().parent; V=O.parents[1]
runs={'L2':V/'formal-3430','L3':V/'diagnostic-12g/formal-3442'}
base=list(csv.DictReader((runs['L2']/'requests-enriched.csv').open()))
order=sorted(base,key=lambda r:r['started_at']); rank={r['runtime_request_id']:i+1 for i,r in enumerate(order)}
source_rank={r['source_key']:rank[r['runtime_request_id']] for r in order}
probes={r['client_request_id']:r for r in csv.DictReader((V/'diagnostic-12g/per-request-diagnostic.csv').open())}
schedule={}
for line in (V/'diagnostic-12g/formal-3442/query-diagnostic-1274873.jsonl').open():
 e=json.loads(line)
 if e.get('kind')=='lookup_decision' and e.get('scheduled_tokens',0)>0:schedule.setdefault(e['request_id'],e['time'])
allrows=[]; summary={}
for name,p in runs.items():
 plan={n['runtime_request_id']:n for t in json.loads((p/'replay/replay-plan.json').read_text())['tasks'] for n in t['requests']}
 seeds={n.get('backend_sampling_seed'):i for i,n in plan.items()};pid={};events={}
 for ln,line in enumerate((p/'proxy-step.log').read_text().splitlines(),1):
  if not line.startswith('{'):continue
  e=json.loads(line)
  if e.get('event')=='proxy_received':pid[e['request_id']]=seeds.get(e.get('seed'))
  i=pid.get(e.get('request_id'))
  if i:events.setdefault(i,{})[e['event']]={**e,'line':ln}
 ex={n['runtime_request_id']:n for t in json.loads((p/'replay/replay-execution.json').read_text())['tasks'] for n in t['nodes']}
 ad={x['request_id']:x for x in map(json.loads,(p/'request-admission.jsonl').read_text().splitlines())}
 rows={}
 for r in csv.DictReader((p/'requests-enriched.csv').open()):
  i=r['runtime_request_id'];n=plan[i];e=events[i];a=ad[i];c=ex[i]['prompt_calibration'];s=e['P_http_start'];f=e['P_http_response']
  rows[rank[i]]={'run':name,'L2_rank':rank[i],'runtime_request_id':i,'source_key':r['source_key'],'actor_id':r['actor_id'],'input_tokens':int(r['input_tokens']),'send_after_rank':source_rank.get(n['send_after'],'NA'),'context_after_rank':source_rank.get(n['context_after'],'NA'),'P_start':s['time'],'P_end':f['time'],'P_http_seconds':f['time']-s['time'],'client_end':r['finished_at'],'client_end_epoch':a['finished_time'],'admission_enqueue_epoch':a['acquired_time']+a['enqueued_monotonic']-a['acquired_monotonic'],'admission_acquired_epoch':a['acquired_time'],'admission_wait_seconds':a['admission_wait_seconds'],'effective_interval_seconds':n['effective_interval_seconds'],'prompt_preparation_seconds':c.get('prompt_preparation_seconds','NA'),'scheduler_lag_seconds':ex[i]['scheduler_lag_seconds'],'context_mode':r['context_mode'],'adjustment':c['adjustment'],'trimmed_filler_tokens':c['trimmed_filler_tokens'],'cache_adopted':probes[i]['adopted_local_cache_tokens'] if name=='L3' else 'NA','P_schedule_decision_time':schedule.get(probes[i]['server_request_id'],'NA') if name=='L3' else 'NA','proxy_start_line':s['line'],'proxy_end_line':f['line']}
 chains=[]; selected={125,139,140,141,144,146}; flags={k:[] for k in rows}
 for prev,nxt in [(139,144),(141,146)]:
  start,end=rows[prev]['P_end'],rows[nxt]['P_start'];hits=[]
  for k,r in rows.items():
   if r['P_start']<end and r['P_end']>start:
    labels=[]
    if r['P_start']<start:labels.append('already_inflight')
    else:labels.append('arrived_in_gap')
    if r['P_end']>end:labels.append('inflight_at_successor')
    flags[k].append(f'{prev}->{nxt}:'+','.join(labels));selected.add(k);hits.append(k)
  chains.append({'chain':f'{prev}->{nxt}','start':start,'end':end,'gap_seconds':end-start,'overlapping_requests_in_P_arrival_order':sorted(hits,key=lambda k:rows[k]['P_start'])})
 for k in sorted(selected,key=lambda k:rows[k]['P_start']):allrows.append({**rows[k],'chain_overlap':';'.join(flags[k]) or 'endpoint_or_direct_predecessor'})
 r=rows[140];prev=rows[r['send_after_rank']]
 summary[name]={'chains':chains,'request140':r,'predecessor':prev,'predecessor_client_end_to_enqueue':r['admission_enqueue_epoch']-prev['client_end_epoch'],'predecessor_client_end_to_P_start':r['P_start']-prev['client_end_epoch'],'rank141_overlap_with140':max(0,min(rows[141]['P_end'],r['P_end'])-max(rows[141]['P_start'],r['P_start'])),'key_requests':[rows[k] for k in [125,139,140,141,144,146]],'trim_requests':[k for k,r in rows.items() if r['trimmed_filler_tokens']]}
 assert len(rows)==425
with (O/'local-chain-timeline.csv').open('w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=allrows[0]);w.writeheader();w.writerows(allrows)
(O/'local-chain-summary.json').write_text(json.dumps(summary,indent=2))
for name,s in summary.items():
 print(name,json.dumps({k:v for k,v in s.items() if k not in ['request140','predecessor','key_requests']}))
 for r in s['key_requests']:print(r['L2_rank'],*[f'{k}={r[k]}' for k in ['P_start','P_http_seconds','send_after_rank','context_after_rank','effective_interval_seconds','prompt_preparation_seconds','admission_wait_seconds','scheduler_lag_seconds','adjustment','trimmed_filler_tokens']])
