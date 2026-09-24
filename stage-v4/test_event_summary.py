"""Check deferred reset ordering and repeated removals without a global hash dedupe."""
import json,tempfile
from pathlib import Path
from summarize_events import summarize
with tempfile.TemporaryDirectory() as d:
 p=Path(d);(p/'replay').mkdir()
 def write(name,data):(p/name).write_text(json.dumps(data))
 write('event-formal-start.json',{'last_sequence':0,'clears_before':0,'counts':{},'last_clear_sequence':None})
 write('event-formal-end.json',{'last_sequence':3,'gaps':[]})
 write('observer-final.json',{'errors':[]})
 events=[(0,'BlockStored',['warm']),(1,'AllBlocksCleared',[]),(1,'BlockStored',['x']),(2,'BlockRemoved',['x','y']),(2,'BlockStored',['x']),(3,'BlockRemoved',['x'])]
 (p/'kv-events.jsonl').write_text(''.join(json.dumps({'sequence':seq,'timestamp':float(seq),'engine':0,'event':{'type':kind,'block_hashes':hashes,'medium':'GPU','group_idx':0}})+'\n' for seq,kind,hashes in events))
 (p/'replay/requests.jsonl').write_text(json.dumps({'finished_at':'1970-01-01T00:00:02+00:00'})+'\n')
 summarize(p);s=json.loads((p/'event-summary.json').read_text());assert s['total_removed_entries']==3 and s['extra_formal_clears']==0 and s['groups'][0]['counts']['BlockStored']==2
 print('PASS: deferred reset excluded; same-batch formal stores retained; repeated removal counted')
