import csv,json,statistics
from pathlib import Path
from datetime import datetime
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).parent
runs={'L2':ROOT/'formal-3430','L3':ROOT/'diagnostic-12g/formal-3442'}
rr={k:list(csv.DictReader((p/'requests-enriched.csv').open())) for k,p in runs.items()}
by={k:{r['runtime_request_id']:r for r in rows} for k,rows in rr.items()}
order=sorted(rr['L2'],key=lambda r:r['started_at']);cont=[r for r in order if r['cohort']=='continuation']
wins=[]
for i in range(len(cont)-9):
 ids=[r['runtime_request_id'] for r in cont[i:i+10]];diff=[float(by['L2'][j]['ttft_seconds'])-float(by['L3'][j]['ttft_seconds']) for j in ids]
 wins.append({'i':i,'mean_difference_seconds':statistics.mean(diff),'above_1s':sum(d>1 for d in diff),'first_source_key':cont[i]['source_key']})
# Predefined operational criterion: three consecutive non-overlapping 10-request
# windows each mean >2s and >=6 of 10 individual differences >1s.
def yes(w):return w['mean_difference_seconds']>2 and w['above_1s']>=6
start=next(i for i in range(len(wins)-20) if all(yes(wins[j]) for j in [i,i+10,i+20]))
target=cont[start:start+10];ids={r['runtime_request_id'] for r in target};ranks={r['runtime_request_id']:i+1 for i,r in enumerate(order)}
sk={r['source_key']:r for r in order}
core=set(ids)
for r in target:
 if r['context_after']:core.add(sk[r['context_after']]['runtime_request_id'])
first=min(ranks[j] for j in ids);last=max(ranks[j] for j in ids)
for r in order[max(0,first-6):last+5]:core.add(r['runtime_request_id'])
# Context request metadata only; no model execution or input reconstruction.
proxy={};samples={};inventory={};windows={};output=[]
for name,p in runs.items():
 plan=json.load((p/'replay/replay-plan.json').open());seeds={n['backend_sampling_seed']:n['runtime_request_id'] for t in plan['tasks'] for n in t['requests']};pid={};records=[]
 for lineno,line in enumerate((p/'proxy-step.log').read_text().splitlines(),1):
  if line.startswith('{'):
   e=json.loads(line);e['line']=lineno;records.append(e)
   if e.get('event')=='proxy_received' and e.get('seed') in seeds:pid[e['request_id']]=seeds[e['seed']]
 proxy[name]={}
 for e in records:
  cid=pid.get(e.get('request_id'))
  if cid:proxy[name].setdefault(cid,{})[e['event']]=e
 samples[name]={s['request_id']:s for s in map(json.loads,(p/'prompt-samples.jsonl').read_text().splitlines())}
 facts=[json.loads(l) for l in (p/'replay/requests.jsonl').read_text().splitlines()]
 inventory[name]={'request_fact_keys':list(facts[0]),'full_prompt_samples':len(samples[name]),'target_prompt_samples':sum(i in samples[name] for i in ids),'core_prompt_samples':sum(i in samples[name] for i in core),'actual_output_text_in_request_facts':any(any(k in x for k in ['assistant_content','output_text','response_body','messages']) for x in facts),'kv_event_json_complete_local':(p/'kv-events.jsonl').exists(),'kv_event_partial_bytes':(p/'kv-events.jsonl.partial').stat().st_size if (p/'kv-events.jsonl.partial').exists() else 0}
 es=[proxy[name][i] for i in core];windows[name]={'start':min(e['P_http_start']['time'] for e in es),'end':max(e['P_http_response']['time'] for e in es),'target_start':min(proxy[name][i]['P_http_start']['time'] for i in ids),'target_end':max(proxy[name][i]['P_http_response']['time'] for i in ids)}
 probes=list(csv.DictReader((ROOT/'diagnostic-12g/per-request-diagnostic.csv').open())) if name=='L3' else []
 probe={x['client_request_id']:x for x in probes}
 for i in sorted(core,key=lambda i:ranks[i]):
  r=by[name][i];e=proxy[name][i];q=probe.get(i,{})
  row={'run':name,'is_target':i in ids,'L2_submission_rank':ranks[i],'runtime_request_id':i,'trace_request_id':r['trace_request_id'],'source_key':r['source_key'],'actor_id':r['actor_id'],'context_after':r['context_after'],'input_tokens':r['input_tokens'],'context_mode':r['context_mode'],'calibration_adjustment':r['calibration_adjustment'],'client_start':r['started_at'],'client_end':r['finished_at'],'ttft_seconds':r['ttft_seconds'],'P_http_start':e['P_http_start']['time'],'P_http_response':e['P_http_response']['time'],'P_http_seconds':e['P_http_response']['time']-e['P_http_start']['time'],'proxy_start_line':e['P_http_start']['line'],'proxy_response_line':e['P_http_response']['line'],'D_first_chunk':e.get('D_first_chunk',{}).get('time','NA'),'adopted_local_cache_tokens':q.get('adopted_local_cache_tokens','NA'),'query_calls':q.get('query_calls','NA'),'lookup_to_admit_seconds':q.get('lookup_to_admit_seconds','NA'),'P_schedule_time':'NA','transfer_completed_time':'NA','block_release_time':'NA','actual_prompt_available':i in samples[name],'runtime_token_lcp':'NA'}
  output.append(row)
selection={'rule':'10 consecutive continuations; earliest start with windows i,i+10,i+20 each mean delta>2s and >=6/10 delta>1s; diagnostic selection, not causal onset','continuation_start_index_zero':start,'target_L2_submission_ranks':[ranks[r['runtime_request_id']] for r in target],'target_ids':[r['runtime_request_id'] for r in target],'core_request_count':len(core),'core_ids':sorted(core,key=lambda i:ranks[i]),'windows':windows,'qualifying_windows':[wins[j] for j in [start,start+10,start+20]]}
(OUT/'selection.json').write_text(json.dumps(selection,indent=2));(OUT/'data-inventory.json').write_text(json.dumps(inventory,indent=2));(OUT/'ttft-windows.json').write_text(json.dumps(wins,indent=2))
with (OUT/'request-comparison.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=output[0]);w.writeheader();w.writerows(output)
print(json.dumps(selection,indent=2));print('INVENTORY',json.dumps(inventory,indent=2))
