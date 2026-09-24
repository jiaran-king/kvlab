"""Separate reader verifies decision visibility while producer remains alive."""
import json,os,subprocess,sys,tempfile
from pathlib import Path
HERE=Path(__file__).resolve().parent
PRODUCER=r'''
import os,sys,time,types
sys.path.insert(0,sys.argv[1]);import query_probe as q
class Scheduler:
 def __init__(self):
  self.scheduler_config=types.SimpleNamespace(max_num_seqs=2,enable_chunked_prefill=True)
  self.scheduler_reserve_full_isl=True;self.need_mamba_block_aligned_split=False;self.connector=None
  self.running=[];self.waiting=[];self.requests={};self.turn=0
 def _mamba_block_aligned_split(self,*a):return 1
 def add_request(self,*a):return None
 def schedule(self):
  self.turn+=1;rid='r'+str(self.turn)
  q._pending.append(dict(request_id=rid,attempt=1,allocation='ok',hit_tokens=8))
  self.requests[rid]=types.SimpleNamespace(prefill_stats=types.SimpleNamespace(num_local_cached_tokens=8))
  return types.SimpleNamespace(num_scheduled_tokens={rid:1})
q.instrument(types.SimpleNamespace(__name__='vllm.v1.core.sched.scheduler',Scheduler=Scheduler))
s=Scheduler()
# Deliberately suppress the timer-based flush/snapshot for both calls.
q._last_flush=time.monotonic();q._last_snapshot=time.monotonic()
s.schedule();s.schedule()
print(q._file.name,flush=True)
sys.stdin.readline()
os._exit(0)  # No atexit flush: returned batches must already be visible.
'''
def verify(hook,expect_committed):
 with tempfile.TemporaryDirectory(prefix='v5-flush-') as d:
  env=dict(os.environ,PD_QUERY_DIAGNOSTIC_DIR=d,PYTHONPYCACHEPREFIX='/tmp/v5-pycache')
  child=subprocess.Popen([sys.executable,'-c',PRODUCER,str(hook)],env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
  try:
   path=child.stdout.readline().strip();assert path,(child.poll(),child.stderr.read())
   rows=[json.loads(x) for x in Path(path).read_text().splitlines()]
   decisions=[e for e in rows if e['kind']=='lookup_decision']
   commits=[e for e in rows if e['kind']=='query_batch_committed']
   if expect_committed:assert len(decisions)==2 and len(commits)==2,rows
   else:assert len(decisions)<2,rows
   child.stdin.write('\n');child.stdin.flush();assert child.wait(timeout=5)==0
   after=[json.loads(x) for x in Path(path).read_text().splitlines()]
   assert after==rows,'Unexpected reliance on shutdown flush'
   return len(decisions)
  finally:
   if child.poll() is None:child.kill();child.wait(timeout=5)
print('Original visible decisions:',verify(HERE.parent/'hook',False))
print('Fixed visible decisions:',verify(HERE/'hook',True))
print('PASS: regression reproduced; fixed batches visible before process exit, without timer or atexit.')
