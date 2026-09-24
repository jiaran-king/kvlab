"""Bounded-memory historical event/metric window extraction. No model imports."""
import argparse,json,collections,re
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('base',type=Path);p.add_argument('selection',type=Path);p.add_argument('output',type=Path);a=p.parse_args();sel=json.loads(a.selection.read_text());a.output.mkdir(exist_ok=True,parents=True)
result={}
for name,rel in [('L2','formal-3430'),('L3','diagnostic-12g/formal-3442')]:
 run=a.base/rel;window=sel['windows'][name];start=window['target_start'];stop=window['target_end'];end=json.loads((run/'event-formal-end.json').read_text());final=json.loads((run/'observer-final.json').read_text());counts=collections.Counter();total=collections.Counter();seq=set();clear=[];specs={};fields={};bounds={};active=False;formal_first=None;line_no=0;sequence_backtracks=0;last=-1;batch_pending={};group_first_removed={}
 # Files are capture ordered; summarize counts without assuming cross-message
 # request order. Same-sequence event order remains publisher order.
 with (run/'kv-events.jsonl').open() as f:
  for line_no,line in enumerate(f,1):
   e=json.loads(line);s=e['sequence'];seq.add(s)
   if s<last:sequence_backtracks+=1
   last=s;v=e['event'];kind=v['type'];g=str(v.get('group_idx'));fields.setdefault(kind,list(v))
   if kind=='AllBlocksCleared':clear.append({'sequence':s,'time':e['timestamp'],'line':line_no});active=True;formal_first=s;continue
   if not active or s>end['last_sequence']:continue
   total[(g,kind)]+=len(v.get('block_hashes',[]))
   if kind=='BlockStored':specs[g]={k:v.get(k) for k in ['block_size','kv_cache_spec_kind','kv_cache_spec_sliding_window']}
   if start<=e['timestamp']<=stop:
    counts[(g,kind)]+=len(v.get('block_hashes',[]));bounds.setdefault(g,{'first_sequence':s,'first_line':line_no});bounds[g].update(last_sequence=s,last_line=line_no)
    if kind=='BlockRemoved' and g not in group_first_removed:group_first_removed[g]={'sequence':s,'timestamp':e['timestamp'],'line':line_no,'first_hash':v.get('block_hashes',[None])[0],'association':'not attributed to target request'}
 summary={'run':str(run),'window':{'start':start,'end':stop,'definition':'publisher timestamp within min target P_http_start .. max target P_http_response; may include other concurrent requests'},'stream':{'lines':line_no,'sequences':len(seq),'min_sequence':min(seq),'max_sequence':max(seq),'missing_sequences':[i for i in range(max(seq)+1) if i not in seq],'capture_sequence_backtracks':sequence_backtracks,'observer_errors':final['errors'],'clears':clear},'event_fields':fields,'group_specs':specs,'window_counts':[{'group':g,'kind':k,'entries':n} for (g,k),n in sorted(counts.items())],'formal_counts':[{'group':g,'kind':k,'entries':n} for (g,k),n in sorted(total.items())],'window_bounds':bounds,'first_window_removal_by_group':group_first_removed}
 # Existing metrics read once under this CPU allocation; only two snapshots
 # and their counter deltas are exported, never the periodic file.
 before=None;after=None;names=['prefix_cache_queries_total','prefix_cache_hits_total','prompt_tokens_by_source_total','request_prefill_time_seconds_sum','request_prefill_time_seconds_count']
 with (run/'metrics-samples.jsonl').open() as f:
  for line in f:
   e=json.loads(line)
   if e.get('role')!='P' or 'text' not in e:continue
   if e['time']<=start:before=e
   if e['time']>=stop:after=e;break
 def selected(e):
  if e is None:return None
  return {l.rsplit(' ',1)[0]:float(l.rsplit(' ',1)[1]) for l in e['text'].splitlines() if any(l.startswith('vllm:'+n+'{') for n in names)}
 ba,af=selected(before),selected(after)
 summary['metric_interval']={'start':before['time'] if before else None,'end':after['time'] if after else None,'deltas':{k:af[k]-ba[k] for k in af if k in ba} if ba and af else None,'scope':'bracketing time interval, not exact per-target-request attribution'}
 result[name]=summary
(a.output/'event-window-summary.json').write_text(json.dumps(result,indent=2))
print('Wrote event-window-summary.json; read two histories once; no GPU')
