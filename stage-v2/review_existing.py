import csv,json,re,sys
from pathlib import Path
from datetime import datetime,timezone,timedelta
sys.path.insert(0,str(Path('scripts').resolve()))
from summarize_point import percentile
OUT=Path('stage-v2'); tz=timezone(timedelta(hours=8))
def epoch(s):return datetime.fromisoformat(s).timestamp()
def csvsave(name,rows):
 with (OUT/name).open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
allrows={};events={};log_events={};stage=[];checks={}
for label,job in [('H','3343'),('L','3353')]:
 p=Path('evidence/formal-'+job)
 rows=list(csv.DictReader((p/'requests-enriched.csv').open()));allrows[label]=rows
 start=min(epoch(r['started_at']) for r in rows);end=max(epoch(r['finished_at']) for r in rows)
 assert len(rows)==174 and all(r['http_status']=='success' and r['input_tokens']==r['planned_input_tokens'] and r['output_tokens']==r['planned_output_tokens'] for r in rows)
 assert json.loads(json.loads((p/'cache-reset.json').read_text())[-1]['body'])['success']
 ex=json.loads((p/'replay/replay-execution.json').read_text())
 checks[label]={'job':job,'requests':len(rows),'resets':ex['summary']['prompt_calibration_adjustments'].get('reset',0),'exact_calibrations':ex['summary']['prompt_calibration_exact_requests'],'e2e_all_p50':percentile([float(r['latency_seconds']) for r in rows],.5),'e2e_all_p95':percentile([float(r['latency_seconds']) for r in rows],.95)}
 events[label]=[];log_events[label]=[]
 for role in ['P','D']:
  pending={}
  for line in (p/(role+'.log')).read_text().splitlines():
   stamp=re.search(r'(\d\d-\d\d \d\d:\d\d:\d\d)',line)
   kind='jit_warning' if 'JIT compilation during inference:' in line else 'transfer_summary' if 'KV Transfer metrics:' in line else None
   if kind and stamp:
    ts=datetime.strptime('2026-'+stamp.group(1),'%Y-%m-%d %H:%M:%S').replace(tzinfo=tz).timestamp()
    log_events[label].append({'role':role,'kind':kind,'epoch':ts,'text':line})
   m=re.search(r'pid=(\d+)\).*?(2026-\d\d-\d\d \d\d:\d\d:\d\d).*TileLang (begins|completes) to compile kernel `([^`]+)`',line)
   if not m:continue
   pid,stamp,action,kernel=m.groups();t=datetime.strptime(stamp,'%Y-%m-%d %H:%M:%S').replace(tzinfo=tz).timestamp();key=(pid,kernel)
   if action=='begins':pending[key]=t
   elif key in pending:
    begin=pending.pop(key)
    if begin<end and t>start:events[label].append({'role':role,'pid':pid,'kernel':kernel,'start_epoch':begin,'end_epoch':t,'duration_s':t-begin,'start_utc':datetime.fromtimestamp(begin,timezone.utc).isoformat()})
  assert not pending
  def metric(phase):
   out={}
   for line in (p/f'formal-{phase}-{role}.prom').read_text().splitlines():
    m=re.fullmatch(r'(vllm:[\w]+(?:_sum|_count))\{([^}]*)\} ([\d.e+-]+)',line)
    if m:
     n,labels,v=m.groups();assert n not in out;out[n]=float(v)
   return out
  a,b=metric('before'),metric('after')
  for n in b:
   if n.endswith('_sum') and any(x in n for x in ['queue_time_seconds','prefill_time_seconds','time_to_first_token_seconds','decode_time_seconds','inference_time_seconds']):
    c=n[:-4]+'_count';count=b[c]-a[c];stage.append({'run':label,'role':role,'metric':n[:-4],'delta_sum':b[n]-a[n],'delta_count':count,'mean_seconds':(b[n]-a[n])/count if count else None})
 checks[label]['paired_compile_intervals']=len(events[label])
 checks[label]['compile_intervals_sum_rank_seconds']=sum(e['duration_s'] for e in events[label])
checks['time_basis']='Client ISO UTC; worker explicit date timestamps interpreted UTC+8, consistent with startup/SLURM local timestamps and services-ready Unix time. Whole-second compile log precision; line order can be buffered. No cross-host subsecond precision claim.'
paired=[]
for label in ['H','L']:
 other='L' if label=='H' else 'H';lookup={r['trace_request_id']:r for r in allrows[other]}
 for rank,r in enumerate(sorted([r for r in allrows[label] if r['cohort']=='continuation'],key=lambda r:float(r['ttft_seconds']),reverse=True)[:10],1):
  t=epoch(r['started_at']);first=t+float(r['ttft_seconds']);q=lookup[r['trace_request_id']]
  overlap=[e for e in events[label] if e['start_epoch']<first and e['end_epoch']>t]
  item={'tail_run':label,'rank':rank,'trace_request_id':r['trace_request_id'],'session':r['source_session_id'],'actor':r['actor_id'],'actor_turn':r['actor_turn'],'input':r['input_tokens'],'output':r['output_tokens'],'start_utc':r['started_at'],'ttft_s':float(r['ttft_seconds']),'paired_run_start_utc':q['started_at'],'paired_run_ttft_s':float(q['ttft_seconds']),'client_other_inflight_at_send':sum(epoch(x['started_at'])<=t<epoch(x['finished_at']) for x in allrows[label])-1,'overlapping_compile_intervals':len(overlap),'compile_roles':','.join(sorted({e['role'] for e in overlap}))}
  for role in ['P','D']:
   for kind in ['jit_warning','transfer_summary']:
    candidates=[e for e in log_events[label] if e['role']==role and e['kind']==kind]
    near=min(candidates,key=lambda e:abs(e['epoch']-t)) if candidates else None
    item[f'{role}_{kind}_offset_from_send_s']=near['epoch']-t if near else None
    item[f'{role}_{kind}_nearest_record']=near['text'] if near else None
  paired.append(item)
csvsave('tail-pairs.csv',paired);csvsave('stage-means.csv',stage)
(OUT/'compile-intervals.json').write_text(json.dumps(events,indent=2));(OUT/'review-facts.json').write_text(json.dumps(checks,indent=2))
(OUT/'jit-transfer-events.json').write_text(json.dumps(log_events,indent=2))
print(json.dumps(checks,indent=2));print('tail overlaps',[(l,sum(r['overlapping_compile_intervals']>0 for r in paired if r['tail_run']==l)) for l in ['H','L']])
