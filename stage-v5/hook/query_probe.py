"""Bounded, buffered P-side records: prefix lookup -> allocation -> scheduling."""
import atexit,functools,json,os,time
import evidence
from pathlib import Path
_pending=[];_file=None;_rows=0;_totals={};_last_flush=0;_last_snapshot=0

def emit(kind,**fields):
 global _file,_rows,_last_flush
 if _rows>=100000:raise RuntimeError('query diagnostic row limit reached')
 if _file is None:
  _file=(Path(os.environ['PD_QUERY_DIAGNOSTIC_DIR'])/f'query-diagnostic-{os.getpid()}.jsonl').open('a',buffering=65536)
 _file.write(json.dumps(dict(time=time.time(),kind=kind,**fields))+'\n');_rows+=1
 if time.monotonic()-_last_flush>1:_file.flush();_last_flush=time.monotonic()

def snapshot():
 if _file is not None:
  emit('scheduled_totals',requests=_totals);_file.flush()
atexit.register(snapshot)

def instrument(module):
 if module.__name__.endswith('single_type_kv_cache_manager'):
  evidence.instrument_groups(module);return
 if module.__name__.endswith('kv_cache_manager'):
  cls=module.KVCacheManager;get=cls.get_computed_blocks;alloc=cls.allocate_slots
  @functools.wraps(get)
  def lookup(self,request,*args,**kwargs):
   token,ctx=evidence.begin(self,request)
   t=time.perf_counter()
   try:out=get(self,request,*args,**kwargs)
   finally:evidence.current.reset(token)
   emit('joint_lookup',request_id=request.request_id,attempt=ctx['attempt'],calls=ctx['call'],returned=out[1],shared_prefix_metadata=evidence.plain(out[2:]))
   row=dict(request_id=request.request_id,attempt=ctx['attempt'],num_tokens=request.num_tokens,num_prompt_tokens=request.num_prompt_tokens,num_computed_tokens=request.num_computed_tokens,preemptions=request.num_preemptions,hit_tokens=out[1],lookup_seconds=time.perf_counter()-t,allocation=None)
   _pending.append(row);emit('lookup',**row);return out
  @functools.wraps(alloc)
  def allocate(self,request,*args,**kwargs):
   out=alloc(self,request,*args,**kwargs)
   for row in reversed(_pending):
    if row['request_id']==request.request_id:row['allocation']='none' if out is None else 'ok';break
   if out is None:emit('allocation_none',request_id=request.request_id,num_computed_tokens=request.num_computed_tokens,num_prompt_tokens=request.num_prompt_tokens,num_new_tokens=args[0] if args else kwargs.get('num_new_tokens'),num_new_computed_tokens=kwargs.get('num_new_computed_tokens',0),free_blocks=self.block_pool.get_num_free_blocks())
   return out
  cls.get_computed_blocks=lookup;cls.allocate_slots=allocate
 else:
  cls=module.Scheduler;original=cls.schedule;init=cls.__init__
  @functools.wraps(init)
  def initialize(self,*args,**kwargs):
   init(self,*args,**kwargs)
   emit('scheduler_config',max_num_seqs=self.scheduler_config.max_num_seqs,chunked_prefill=self.scheduler_config.enable_chunked_prefill,full_sequence_must_fit=self.scheduler_reserve_full_isl,need_mamba_block_aligned_split=self.need_mamba_block_aligned_split)
   if self.connector is not None:
    matched=self.connector.get_num_new_matched_tokens
    @functools.wraps(matched)
    def match(request,*a,**kw):
     result=matched(request,*a,**kw)
     for row in reversed(_pending):
      if row['request_id']==request.request_id:
       row['external_tokens']=result[0];row['async_load']=result[1]
       if result[0] is None:row['defer_reason']='connector_match_pending'
       break
     return result
    self.connector.get_num_new_matched_tokens=match
  cls.__init__=initialize
  aligned=cls._mamba_block_aligned_split
  @functools.wraps(aligned)
  def align(self,request,*args,**kwargs):
   out=aligned(self,request,*args,**kwargs)
   if out==0:
    for row in reversed(_pending):
     if row['request_id']==request.request_id:row['defer_reason']='aligned_chunk_zero';break
   return out
  cls._mamba_block_aligned_split=align
  @functools.wraps(original)
  def schedule(self,*args,**kwargs):
   global _last_snapshot
   out=original(self,*args,**kwargs)
   for rid,n in out.num_scheduled_tokens.items():_totals[rid]=_totals.get(rid,0)+n
   for row in _pending:
    if row['allocation']=='none':row['defer_reason']='allocation_none'
    elif not out.num_scheduled_tokens.get(row['request_id'],0) and 'defer_reason' not in row:row['defer_reason']='async_load_or_other_unscheduled'
    req=self.requests.get(row['request_id'])
    if req is not None and req.prefill_stats is not None:row['adopted_local_cache_tokens']=req.prefill_stats.num_local_cached_tokens
    emit('lookup_decision',**row,scheduled_tokens=out.num_scheduled_tokens.get(row['request_id'],0),running=len(self.running),waiting=len(self.waiting))
   _pending.clear()
   if time.monotonic()-_last_snapshot>10:snapshot();_last_snapshot=time.monotonic()
   if _totals and len(_totals)>600:raise RuntimeError('diagnostic request limit exceeded')
   return out
  cls.schedule=schedule
  add=cls.add_request
  @functools.wraps(add)
  def add_request(self,request,*args,**kwargs):
   evidence.capture(request)
   return add(self,request,*args,**kwargs)
  cls.add_request=add_request
 emit('installed',module=module.__name__)
