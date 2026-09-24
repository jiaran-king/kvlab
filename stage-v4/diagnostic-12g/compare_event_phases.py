import json,csv,collections,bisect
from pathlib import Path
from datetime import datetime
result={}
for job in [3430,3442]:
 p=Path('stage-v4/formal-3430') if job==3430 else Path('stage-v4/diagnostic-12g/formal-3442')
 if not (p/'kv-events.jsonl').exists():continue
 rows=list(csv.DictReader((p/'requests-enriched.csv').open()));rows.sort(key=lambda r:r['started_at']);starts=[datetime.fromisoformat(r['started_at']).timestamp() for r in rows];boundary=json.load(open(p/'event-formal-start.json'));end=json.load(open(p/'event-formal-end.json'))
 counts=collections.Counter();ever=collections.defaultdict(set);restore=collections.Counter()
 with (p/'kv-events.jsonl').open() as f:
  for line in f:
   e=json.loads(line)
   if e['timestamp']<starts[0] or e['sequence']>end['last_sequence']:continue
   v=e['event'];kind=v['type'];g=v.get('group_idx');bucket=min(bisect.bisect_right(starts,e['timestamp'])//100,3)
   hashes=v.get('block_hashes',[]);counts[(bucket,g,kind)]+=len(hashes)
   if kind=='BlockStored':
    restore[(bucket,g)]+=sum(h in ever[g] for h in hashes);ever[g].update(hashes)
 result[job]=[dict(bucket=k[0],group=k[1],kind=k[2],entries=v) for k,v in counts.items()]
 print(job,'group0',[(x['bucket'],x['kind'],x['entries']) for x in result[job] if x['group']==0]);print('removed_total',sum(x['entries'] for x in result[job] if x['kind']=='BlockRemoved'))
Path('stage-v4/diagnostic-12g/event-phase-summary.json').write_text(json.dumps(result,indent=2))
