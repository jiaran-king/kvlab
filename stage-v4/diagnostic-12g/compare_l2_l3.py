import csv,json,collections,statistics
from pathlib import Path
from datetime import datetime
runs=[Path('stage-v4/formal-3430'),Path('stage-v4/diagnostic-12g/formal-3442')]
D=[]
for run in runs:
 rows=list(csv.DictReader((run/'requests-enriched.csv').open()));rows.sort(key=lambda r:r['started_at']);by={r['runtime_request_id']:r for r in rows};sk={r['source_key']:r for r in rows}
 for i,r in enumerate(rows):r['order']=i;r['start']=datetime.fromisoformat(r['started_at']).timestamp();r['end']=datetime.fromisoformat(r['finished_at']).timestamp()
 for r in rows:
  if r['context_after']:
   p=sk[r['context_after']];others=[x for x in rows if p['order']<x['order']<r['order']]
   r['gap_requests']=len(others);r['gap_input']=sum(int(x['input_tokens']) for x in others);r['gap_seconds']=r['start']-p['end']
 D.append((rows,by))
a,b=D
for lo,hi in [(0,100),(100,200),(200,300),(300,425)]:
 rs=[r for r in a[0][lo:hi] if r['cohort']=='continuation'];print(lo,hi,len(rs))
 for rows in [rs,[b[1][r['runtime_request_id']] for r in rs]]:
  print({k:round(statistics.mean(float(r[k]) for r in rows),3) for k in ['ttft_seconds','gap_requests','gap_input','gap_seconds']})
for session in sorted(set(r['source_session_id'] for r in a[0])):
 print('session',session[:8])
 for _,by in D:
  rs=[r for r in by.values() if r['source_session_id']==session and r['cohort']=='continuation'];print(len(rs),round(sum(float(r['ttft_seconds']) for r in rs),2))
print('top improved')
for r in sorted(a[0],key=lambda r:float(r['ttft_seconds'])-float(b[1][r['runtime_request_id']]['ttft_seconds']),reverse=True)[:10]:
 t=b[1][r['runtime_request_id']];print(r['source_key'],r['source_session_id'][:8],r['actor_id'][:8],r['actor_turn'],r['input_tokens'],[(z['order'],round(float(z['ttft_seconds']),2),z.get('gap_requests'),round(z.get('gap_seconds',0),2)) for z in [r,t]])
for run in runs:
 samples=[json.loads(l) for l in (run/'prompt-samples.jsonl').read_text().splitlines()]
 if run==runs[0]:sa={s['source_key']:s for s in samples}
 else:
  print('initialsample identical',sum(s['messages'][0]==sa[s['source_key']]['messages'][0] for s in samples),len(samples));print('fullsample identical',sum(all(s[f]==sa[s['source_key']][f] for f in ['system','tools','messages']) for s in samples))
