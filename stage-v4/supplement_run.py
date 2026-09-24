"""Read-only per-run supplementary metrics; all outputs go to stage-v2."""
import argparse,csv,json,re,sys
from pathlib import Path
from datetime import datetime,timezone,timedelta
sys.path.insert(0,str(Path(__file__).resolve().parent))
from summarize_point import percentile

def supplement(run,label):
 rows=[json.loads(x) for x in (run/'replay/requests.jsonl').read_text().splitlines()]
 manifest=json.loads((run/'replay/manifest.json').read_text())
 start=datetime.fromisoformat(manifest['created_at']);end=datetime.fromisoformat(manifest['finished_at'])
 stages=[];logs={};zone=timezone(timedelta(hours=8))
 for role in ['P','D']:
  def metrics(phase):
   out={}
   for line in (run/f'formal-{phase}-{role}.prom').read_text().splitlines():
    m=re.fullmatch(r'(vllm:\w+(?:_sum|_count))\{([^}]*)\} ([\d.e+-]+)',line)
    if m:
     name,labels,value=m.groups()
     if not any(x in name for x in ['queue_time_seconds','prefill_time_seconds','time_to_first_token_seconds','decode_time_seconds','inference_time_seconds']):continue
     if name in out:raise ValueError('Multiple engine series must be distinguished: '+name)
     out[name]=float(value)
   return out
  a,b=metrics('before'),metrics('after')
  for name in b:
   if name.endswith('_sum') and any(x in name for x in ['queue_time_seconds','prefill_time_seconds','time_to_first_token_seconds','decode_time_seconds','inference_time_seconds']):
    count=b[name[:-4]+'_count']-a[name[:-4]+'_count'];total=b[name]-a[name]
    stages.append({'run':label,'role':role,'metric':name[:-4],'delta_sum':total,'delta_count':count,'mean_seconds':total/count if count else None})
  events=[]
  for line in (run/(role+'.log')).read_text().splitlines():
   kind='compile_begin' if 'TileLang begins to compile' in line else 'jit_warning' if 'JIT compilation during inference:' in line else 'transfer_summary' if 'KV Transfer metrics:' in line else 'kv_transfer_error' if 'pulling kv_caches' in line and 'failed:' in line else None
   if not kind:continue
   stamp=re.search(r'(\d\d-\d\d \d\d:\d\d:\d\d)',line)
   if not stamp:continue
   dt=datetime.strptime(str(start.year)+'-'+stamp.group(1),'%Y-%m-%d %H:%M:%S').replace(tzinfo=zone)
   if start<=dt<=end:events.append({'kind':kind,'time':dt.isoformat(),'text':line})
  bad=[e for e in events if e['kind']=='transfer_summary' and any(int(v)>0 for v in re.findall(r'Num (?:failed transfers|failed recvs|KV expired reqs)=(\d+)',e['text']))]
  logs[role]={'kv_transfer_error_rank_records':sum(e['kind']=='kv_transfer_error' for e in events),'compile_begin_rank_records':sum(e['kind']=='compile_begin' for e in events),'jit_warning_records':sum(e['kind']=='jit_warning' for e in events),'transfer_summary_records':sum(e['kind']=='transfer_summary' for e in events),'transfer_error_nonzero_records':len(bad) if any(e['kind']=='transfer_summary' for e in events) else None,'events':events}
 good=[r for r in rows if r['status']=='success' and r.get('latency_seconds') is not None]
 result={'label':label,'e2e_sample_count':len(good),'e2e_p50_seconds':percentile([r['latency_seconds'] for r in good],.5),'e2e_p95_seconds':percentile([r['latency_seconds'] for r in good],.95),'formal_manifest_duration_seconds':(end-start).total_seconds(),'stage_means':stages,'log_observations':logs}
 out=Path('stage-v4')/(label+'-supplement.json');out.write_text(json.dumps(result,indent=2));print(out)
 return result
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('run',type=Path);p.add_argument('label');a=p.parse_args();supplement(a.run,a.label)
