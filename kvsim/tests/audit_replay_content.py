"""Direct original PromptBuilder comparisons for fixed role/context branches."""
import asyncio,json
from pathlib import Path
from kvsim.replay_export import load_replay,make_tokenizer
ROOT=Path(__file__).resolve().parents[2]
async def main():
 C,analyze,planner,Builder,Exchange,Client=load_replay(ROOT/'stage-v4/source/client')
 d=json.loads((ROOT/'stage-v4/formal-3429/replay-config.json').read_text());d['replay']['trace_path']=str(ROOT/'stage-v4/successful-425-trace.jsonl');cfg=C.model_validate(d);plan=planner(cfg,analyze(cfg.replay.trace_path))
 w=json.loads((ROOT/'output/kvsim/v03/replay425-workload.json').read_text());exported={r['runtime_request_id']:r for r in w['requests']}
 tok=make_tokenizer(Client,ROOT/'output/kvsim/v03/tokenizer/tokenizer.json');builder=Builder(cfg,tok);pairs=[(t,n) for t in plan.tasks for n in t.requests if n.node_type=='request']
 checks={
 'independent':next((t,n) for t,n in pairs if n.context_mode=='independent'),
 'append':next((t,n) for t,n in pairs if n.context_mode=='append'),
 'trim':next((t,n) for t,n in pairs if n.context_mode=='trim'),
 'subagent_first':next((t,n) for t,n in pairs if n.prompt_kind=='subagent_first'),
 'lead_resume':next((t,n) for t,n in pairs if n.actor_role=='lead' and n.context_after and n.send_after!=n.context_after),
 }
 cache={};report=[]
 async def construct(task,n):
  if n.runtime_request_id in cache:return cache[n.runtime_request_id]
  by_source={x.source_key:x for x in task.requests}
  parent=await construct(task,by_source[n.context_after]) if n.context_after else None
  prompt=await builder.build(task,n,parent)
  ids=list(await tok.input_tokens(prompt));out=await tok.token_text(n.runtime_request_id+'/output',n.planned_output_tokens)
  exchange=Exchange(prompt,out);cache[n.runtime_request_id]=exchange
  assert ids==exported[n.runtime_request_id]['tokens'],n.runtime_request_id
  return exchange
 for name,(task,n) in checks.items():
  ex=await construct(task,n);row=exported[n.runtime_request_id];ids={x.source_key:x.runtime_request_id for x in task.requests}
  assert row['context_after']==ids.get(n.context_after) and row['send_after']==ids.get(n.send_after)
  report.append({'case':name,'request_id':n.runtime_request_id,'source_key':n.source_key,'tokens':row['input_tokens'],'adjustment':ex.prompt.calibration.adjustment,'exact_builder_match':True})
 small=json.loads((ROOT/'output/kvsim/v03/replay-small-workload.json').read_text());first=[]
 for session in small['metadata']['sessions']:
  first.append(next(r for r in small['requests'] if r['runtime_session_id']==session['id'] and r['node_type']=='request'))
 assert len({r['runtime_request_id'] for r in first})==3
 assert all(a['tokens']!=b['tokens'] for i,a in enumerate(first) for b in first[i+1:])
 result={'fixed_cases':report,'ancestor_prompts_checked':len(cache),'resampled_private_inputs_distinct':True,'provenance':'Original PromptBuilder direct calls; server-capture parity is a separate 7-case check.'}
 (ROOT/'output/kvsim/v03/content-audit.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
if __name__=='__main__':asyncio.run(main())
