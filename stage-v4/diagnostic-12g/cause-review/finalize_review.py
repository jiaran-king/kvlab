import csv,json,re,statistics
from pathlib import Path
O=Path(__file__).parent;V=O.parents[1];runs={'L2':V/'formal-3430','L3':V/'diagnostic-12g/formal-3442'}
config={}
for name,p in runs.items():
 line=next(l for l in (p/'formal-before-P.prom').read_text().splitlines() if l.startswith('vllm:cache_config_info{'))
 config[name]={'cache_config':dict(re.findall(r'(\w+)="([^"]*)"',line)),'retention_interval_historical':'NA','full_sequence_admission_historical':'NA','reset':json.load((p/'cache-reset.json').open()),'recorded_prompt_count':12}
config['L3']['full_sequence_admission_historical']=True
config['cache_config_equal']=config['L2']['cache_config']==config['L3']['cache_config']
config['retention_code_reference']={'path':'current-source-reference/v1/core/kv_cache_coordinator.py:125','status':'current installed source reference only; not an L2 historical effective env snapshot'}
(O/'effective-config-review.json').write_text(json.dumps(config,indent=2))
rows=list(csv.DictReader((O/'request-comparison.csv').open()));diag={x['client_request_id']:x['server_request_id'] for x in csv.DictReader((V/'diagnostic-12g/per-request-diagnostic.csv').open())};dec={}
for f in runs['L3'].glob('query-diagnostic-*.jsonl'):
 for line in f.open():
  e=json.loads(line)
  if e['kind']=='lookup_decision' and e.get('scheduled_tokens',0)>0:dec[e['request_id']]=e['time']
for r in rows:
 r['P_scheduler_decision_time']=dec.get(diag.get(r['runtime_request_id']),'NA') if r['run']=='L3' else 'NA'
 del r['P_schedule_time']
with (O/'request-comparison.csv').open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=rows[0]);w.writeheader();w.writerows(rows)
summary={}
for name in ['L2','L3']:
 rr=[r for r in rows if r['run']==name and r['is_target']=='True'];summary[name]={k:statistics.mean(float(r[k]) for r in rr) for k in ['ttft_seconds','P_http_seconds']}
summary['delta']= {k:summary['L2'][k]-summary['L3'][k] for k in ['ttft_seconds','P_http_seconds']};(O/'target-phase-summary.json').write_text(json.dumps(summary,indent=2))
a=O/'cpu-3448';worker=(a/'worker-pid.txt').read_text().strip();ps=(a/'processes-after.txt').read_text().splitlines()[1:]
cleanup={'job':3448,'gpu_requested':False,'completed_zero':'JobState=COMPLETED' in (O/'cpu-status.txt').read_text() and 'ExitCode=0:0' in (O/'cpu-status.txt').read_text(),'worker_absent':not any(len(l.split())>1 and l.split()[1]==worker for l in ps),'ipc_unchanged':(a/'ipc-before.txt').read_bytes()==(a/'ipc-after.txt').read_bytes(),'exit_code':int((a/'exit-code.txt').read_text()),'no_services_or_listeners_created':True}
(O/'analysis-cleanup.json').write_text(json.dumps(cleanup,indent=2));assert all(cleanup[x] for x in ['completed_zero','worker_absent','ipc_unchanged']) and cleanup['exit_code']==0
print('Saved config, target phase summaries, request scheduler decision times and CPU cleanup evidence')
