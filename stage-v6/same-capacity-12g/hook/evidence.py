"""Request-level observations; never perform an extra cache lookup."""
import atexit,array,dataclasses,functools,json,os,sys,time
from contextvars import ContextVar
from pathlib import Path
current=ContextVar('lookup_attempt',default=None)
attempts={};seen=set();files=[];configured=set()

def plain(x):
 if dataclasses.is_dataclass(x):return plain(dataclasses.asdict(x))
 if isinstance(x,(list,tuple)):return [plain(y) for y in x]
 if isinstance(x,dict):return {str(k):plain(v) for k,v in x.items()}
 if x is None or isinstance(x,(str,int,float,bool)):return x
 return str(x)

def capture(request):
 from query_probe import emit
 if request.request_id in seen:return
 if len(seen)>=600:raise RuntimeError('input capture request bound exceeded')
 ids=request.prompt_token_ids
 if ids is None:raise RuntimeError('Expected actual text prompt_token_ids')
 if len(ids)>81920:raise RuntimeError('Input exceeds fixed model limit')
 if not files:
  d=Path(os.environ['PD_QUERY_DIAGNOSTIC_DIR'])
  files.extend([(d/f'p-input-{os.getpid()}.u32').open('wb',buffering=1048576),(d/f'p-input-{os.getpid()}.jsonl').open('w',buffering=65536)])
 a=array.array('I',ids)
 if a.itemsize!=4:raise RuntimeError('uint32 capture unavailable')
 if sys.byteorder!='little':a.byteswap()
 offset=files[0].tell();files[0].write(a.tobytes());files[0].flush()
 identity={k:plain(getattr(request,k,None)) for k in ('cache_salt','lora_request','mm_features','prompt_embeds','skip_reading_prefix_cache')}
 # This frozen text-only workload must not acquire an unrepresented identity.
 if any(identity[k] for k in ('lora_request','mm_features','prompt_embeds')):raise RuntimeError('Unexpected non-text cache identity')
 row=dict(request_id=request.request_id,time=time.time(),offset_bytes=offset,count=len(ids),semantic_identity=identity)
 files[1].write(json.dumps(row)+'\n');files[1].flush();seen.add(request.request_id)
 emit('P_request_received',request_id=request.request_id,prompt_token_count=len(ids))

def begin(manager,request):
 from query_probe import emit
 capture(request)
 rid=request.request_id;attempts[rid]=attempts.get(rid,0)+1
 ctx={'request_id':rid,'attempt':attempts[rid],'call':0};token=current.set(ctx)
 if id(manager) not in configured:
  c=manager.coordinator
  fields={k:plain(getattr(c,k,None)) for k in ('retention_interval','scheduler_block_size','hash_block_size','use_eagle','eagle_group_ids','enable_partial_hash_hits','dcp_world_size','pcp_world_size')}
  fields['kv_cache_config']=plain(c.kv_cache_config)
  emit('effective_cache_config',**fields);configured.add(id(manager))
 return token,ctx

def instrument_groups(module):
 from query_probe import emit
 for cls in vars(module).values():
  if not isinstance(cls,type) or cls.__module__!=module.__name__:continue
  descriptor=cls.__dict__.get('find_longest_cache_hit')
  if not isinstance(descriptor,classmethod):continue
  original=descriptor.__func__
  def make(fn):
   @functools.wraps(fn)
   def wrapped(klass,*args,**kw):
    ctx=current.get()
    if ctx is None:return fn(klass,*args,**kw)
    # The installed coordinator uses named arguments. Fail rather than invent fields.
    if 'kv_cache_group_ids' not in kw or 'max_length' not in kw:raise RuntimeError('Unexpected group lookup signature')
    ctx['call']+=1;seq=ctx['call'];start=time.time()
    out=fn(klass,*args,**kw)
    emit('group_lookup',request_id=ctx['request_id'],attempt=ctx['attempt'],call=seq,started=start,
         manager=klass.__name__,groups=list(kw['kv_cache_group_ids']),candidate=kw['max_length'],returned=out[1],
         alignment_tokens=kw.get('alignment_tokens'),drop_eagle_block=kw.get('drop_eagle_block'))
    return out
   return wrapped
  cls.find_longest_cache_hit=classmethod(make(original))
 emit('installed',module=module.__name__)

def close():
 for f in files:f.close()
atexit.register(close)
