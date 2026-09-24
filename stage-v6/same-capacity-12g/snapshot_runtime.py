import hashlib,json,sys
from pathlib import Path
root,run=map(Path,sys.argv[1:3]);base=root/'evidence/pd-capacity-20260919/stage-v6/same-capacity-12g';runtime=root/'runtime/lib/python3.12/site-packages/vllm'
files={}
for p in (base/'source').rglob('*.py'):
 rel=p.relative_to(base/'source');actual=runtime/rel
 raw=actual.read_bytes();assert raw==p.read_bytes(),('runtime changed since reviewed snapshot',str(rel));files['vllm/'+str(rel)]=hashlib.sha256(raw).hexdigest()
for p in [base/n for n in ('client_capture.py','replay_v4.py','pd_service.py','pd_controller.py')]+list((base/'hook').glob('*.py')):
 files['observation/'+str(p.relative_to(base))]=hashlib.sha256(p.read_bytes()).hexdigest()
(run/'source-identity.json').write_text(json.dumps(files,indent=2))
