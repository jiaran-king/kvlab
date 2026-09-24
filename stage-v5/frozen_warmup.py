import json,sys,time
from pathlib import Path
import httpx
from check_evidence import token_records,lines
frozen,run=map(Path,sys.argv[1:3]);bodies=list(lines(frozen/'request-bodies.jsonl'));by={b['source_key']:b for b in bodies}
continuation=next(b for b in bodies if b['context_after'] in by)
pair=[by[continuation['context_after']],continuation];oldidx=json.loads((frozen/'input-index.json').read_text())
start=time.time()
with httpx.Client(timeout=900,trust_env=False) as c:
 for r in pair:
  response=c.post('http://127.0.0.1:18400/v1/chat/completions',json=r['body']);response.raise_for_status()
# Calls consumed full SSE response. P inputs are flushed on add_request.
tokens=token_records(run);proxy={e['request_id']:e['seed'] for e in lines(run/'proxy-step.log') if e.get('event')=='proxy_received' and e['time']>=start}
import re
for r in pair:
 pid=next(k for k,v in proxy.items() if v==r['seed'])
 match=[value for rid,value in tokens.items() if rid.startswith('chatcmpl-'+pid+'-')];assert len(match)==1
 record,raw=match[0];old=oldidx[r['source_key']]
 with (frozen/old['file']).open('rb') as f:f.seek(old['record']['offset_bytes']);expected=f.read(old['record']['count']*4)
 assert raw==expected and record['semantic_identity']==old['record']['semantic_identity']
(run/'frozen-warmup.json').write_text(json.dumps({'passed':True,'sources':[r['source_key'] for r in pair]}))
