"""CPU tests for observer transparency and frozen-input independence."""
import ast,asyncio,dataclasses,json,os,sys,tempfile,types
from pathlib import Path
HERE=Path(__file__).resolve().parent
root=Path(tempfile.mkdtemp(prefix='v5-check-'));os.environ['PD_QUERY_DIAGNOSTIC_DIR']=str(root)
sys.path.insert(0,str(HERE/'hook'));sys.path.insert(0,str(HERE));import query_probe as q
calls=[];sentinel=object();blocks=object();result=(blocks,8,16)
class Group:
 @classmethod
 def find_longest_cache_hit(cls,**kw):calls.append(kw);return ('blocks',8)
Group.__module__='vllm.v1.core.single_type_kv_cache_manager'
q.instrument(types.SimpleNamespace(__name__=Group.__module__,Group=Group))
class Manager:
 def __init__(self):self.coordinator=types.SimpleNamespace(kv_cache_config={'groups':[1,2]});self.block_pool=types.SimpleNamespace(get_num_free_blocks=lambda:10)
 def get_computed_blocks(self,r):
  Group.find_longest_cache_hit(block_hashes=[],max_length=20,kv_cache_group_ids=[1,2]);return result
 def allocate_slots(self,r,*args,**kw):return sentinel
q.instrument(types.SimpleNamespace(__name__='vllm.v1.core.kv_cache_manager',KVCacheManager=Manager))
r=types.SimpleNamespace(request_id='test',prompt_token_ids=[1,2,3],num_tokens=3,num_prompt_tokens=3,num_computed_tokens=0,num_preemptions=0)
m=Manager();assert m.get_computed_blocks(r) is result;assert m.get_computed_blocks(r) is result;assert len(calls)==2;assert m.allocate_slots(r,1) is sentinel
q._file.flush();ev=[json.loads(x) for x in q._file.name and Path(q._file.name).read_text().splitlines()]
assert [e['attempt'] for e in ev if e['kind']=='group_lookup']==[1,2]
assert all(e['groups']==[1,2] for e in ev if e['kind']=='group_lookup')
assert all(e['shared_prefix_metadata']==[16] for e in ev if e['kind']=='joint_lookup')
from check_evidence import token_records
records=token_records(root);assert len(records)==1 and records['test'][1]==b'\x01\0\0\0\x02\0\0\0\x03\0\0\0'
# Load the frozen dataclass definitions without importing the runtime/client.
prompt_module=types.ModuleType('agentinfer.agentbench.replay.prompt')
source=(HERE.parents[1]/'stage-v4/source/client/agentbench/replay/prompt.py').read_text()
tree=ast.parse(source);nodes=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name in ['PromptCalibration','SyntheticPrompt']]
ns=prompt_module.__dict__;ns.update(dataclass=dataclasses.dataclass)
sys.modules[prompt_module.__name__]=prompt_module
exec(compile(ast.fix_missing_locations(ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),*nodes],type_ignores=[])),'frozen-dataclasses','exec'),ns)
from client_capture import install
class Builder:
 async def build(self,*args,**kw):raise AssertionError('Dynamic builder invoked')
class Transport:
 def _body(self,task,node,prompt):return {'messages':list(prompt.messages),'seed':7,'vllm_xargs':{'identity':'current'}}
prompt=prompt_module.SyntheticPrompt('sys',(),({'role':'user','content':'captured'},))
frozen=root/'frozen';frozen.mkdir();run=root/'fixed';run.mkdir()
record={'source_key':'source','prompt':dataclasses.asdict(prompt),'body':{'messages':[{'role':'user','content':'captured'}],'seed':7,'vllm_xargs':{'identity':'old'}}}
(frozen/'request-bodies.jsonl').write_text(json.dumps(record)+'\n')
install(Transport,Builder,run,frozen)
async def check():
 node=types.SimpleNamespace(source_key='source',runtime_request_id='client',context_after='prev',send_after='prev',backend_sampling_seed=7)
 a=await Builder().build(None,node,'answer A');b=await Builder().build(None,node,'entirely different answer B');assert a==b
 assert Transport()._body(None,node,a)=={'messages':[{'role':'user','content':'captured'}],'seed':7,'vllm_xargs':{'identity':'current'}}
asyncio.run(check())
print('PASS: original calls once, exact tuple identity and metadata preserved; attempts/groups linked; one uint32 input record; frozen body independent of new answers; no dynamic build.')
