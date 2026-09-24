"""Count ordered cache-removal entries, never infer their cause from hash identity."""
import argparse,collections,csv,json
from pathlib import Path

def summarize(run):
 start=json.loads((run/'event-formal-start.json').read_text());end=json.loads((run/'event-formal-end.json').read_text());final=json.loads((run/'observer-final.json').read_text())
 events=[json.loads(l) for l in (run/'kv-events.jsonl').read_text().splitlines()]
 events=sorted(enumerate(events),key=lambda x:(x[1]['sequence'],x[0]))
 clears=[i for i,(_,r) in enumerate(events) if r['event']['type']=='AllBlocksCleared' and r['sequence']>start['last_sequence']]
 # If reset was already observed in the pre-start snapshot, use its last clear.
 if start.get('last_clear_sequence') is not None and start.get('counts',{}).get('AllBlocksCleared',0)>start['clears_before']:
  clears=[i for i,(_,r) in enumerate(events) if r['event']['type']=='AllBlocksCleared' and r['sequence']==start['last_clear_sequence']]
 assert clears,'Missing ordered reset event: cannot establish formal event window'
 formal=[r for _,r in events[clears[0]+1:] if r['sequence']<=end['last_sequence']]
 extra_clears=sum(r['event']['type']=='AllBlocksCleared' for r in formal)
 groups=collections.defaultdict(lambda:collections.Counter());specs={}
 requests=[json.loads(l) for l in (run/'replay/requests.jsonl').read_text().splitlines()]
 from datetime import datetime
 completed=sorted(datetime.fromisoformat(r['finished_at']).timestamp() for r in requests)
 import bisect
 curve=[]
 for r in formal:
  e=r['event'];group=(r.get('engine'),e.get('medium'),e.get('group_idx'),e.get('locality'))
  kind=e['type'];n=len(e.get('block_hashes',[]));groups[group][kind]+=n if kind in ('BlockStored','BlockRemoved') else 1
  if kind=='BlockStored':specs[str(e.get('group_idx'))]={k:e[k] for k in ['block_size','kv_cache_spec_kind','kv_cache_spec_sliding_window'] if k in e}
  if kind=='BlockRemoved':curve.append({'timestamp':r['timestamp'],'sequence':r['sequence'],'engine':group[0],'medium':group[1],'group_idx':group[2],'locality':group[3],'removed_entries':n,'cumulative_removed_in_group':groups[group]['BlockRemoved'],'completed_requests':bisect.bisect_right(completed,r['timestamp'])})
 result={'measurement':'cache removal hash entries; cause unavailable in installed event schema','formal_start_reset_sequence':events[clears[0]][1]['sequence'],'formal_end_sequence':end['last_sequence'],'extra_formal_clears':extra_clears,'stream_complete':not end['gaps'] and not final['errors'],'gaps':end['gaps'],'errors':final['errors'],'group_specs':specs,'groups':[dict(engine=k[0],medium=k[1],group_idx=k[2],locality=k[3],counts=dict(v)) for k,v in groups.items()],'total_removed_entries':sum(v['BlockRemoved'] for v in groups.values()),'interpretation':'not physical blocks, bytes, tokens, miss rate or confirmed capacity evictions'}
 (run/'event-summary.json').write_text(json.dumps(result,indent=2))
 with (run/'removal-progress.csv').open('w') as f:
  keys=['timestamp','sequence','engine','medium','group_idx','locality','removed_entries','cumulative_removed_in_group','completed_requests'];w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(curve)
 print(json.dumps(result,indent=2))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('run',type=Path);summarize(p.parse_args().run)
