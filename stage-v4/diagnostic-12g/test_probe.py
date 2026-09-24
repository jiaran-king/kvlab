import os,tempfile,sys,types
from pathlib import Path
os.environ['PD_QUERY_DIAGNOSTIC_DIR']=tempfile.mkdtemp(prefix='query-probe-test-')
sys.path.insert(0,str(Path(__file__).parent/'hook'))
import query_probe as q
class Manager:
 def __init__(self):self.block_pool=types.SimpleNamespace(get_num_free_blocks=lambda:10)
 def get_computed_blocks(self,r):return ('blocks',0,0)
 def allocate_slots(self,r,n,**kw):return None if n==5 else ['allocated']
m=types.SimpleNamespace(__name__='vllm.v1.core.kv_cache_manager',KVCacheManager=Manager);q.instrument(m)
class Scheduler:
 def __init__(self):
  self.scheduler_config=types.SimpleNamespace(max_num_seqs=2,enable_chunked_prefill=True);self.scheduler_reserve_full_isl=False;self.need_mamba_block_aligned_split=False;self.connector=None;self.running=[];self.waiting=[];self.requests={}
 def _mamba_block_aligned_split(self,r,n):return n
 def schedule(self):return types.SimpleNamespace(num_scheduled_tokens={'r':4})
m=types.SimpleNamespace(__name__='vllm.v1.core.sched.scheduler',Scheduler=Scheduler);q.instrument(m)
r=types.SimpleNamespace(request_id='r',num_tokens=100,num_prompt_tokens=100,num_computed_tokens=0,num_preemptions=0)
a=Manager();assert a.get_computed_blocks(r)==('blocks',0,0);assert a.allocate_slots(r,5) is None
s=Scheduler();assert s.schedule().num_scheduled_tokens=={'r':4};assert a.allocate_slots(r,4)==['allocated'];q.snapshot()
print('PASS: wrapped lookup/allocation/schedule preserve return values and emit bounded diagnostics')
