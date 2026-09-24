"""Construct 6 long root prompts and one continuation using the real tokenizer; no inference."""
import asyncio,json,sys
from pathlib import Path
from agentinfer.agentbench.replay.analyzer import analyze_replay_trace
from agentinfer.agentbench.replay.planner import build_replay_plan
from agentinfer.agentbench.replay.prompt import PromptBuilder,TokenizerClient,PromptExchange
from replay_config import make_config

base,run=map(Path,sys.argv[1:3])
async def main():
 config=make_config(base,run);plan=build_replay_plan(config,analyze_replay_trace(config.replay.trace_path))
 tokenizer=TokenizerClient(config);builder=PromptBuilder(config,tokenizer);samples=[];first_tokens=[]
 try:
  for task in plan.tasks:
   roots=[n for n in task.requests if n.node_type=='request' and n.context_after is None and (n.planned_input_tokens or 0)>=16000]
   node=min(roots,key=lambda n:n.planned_input_tokens)
   prompt=await builder.build(task,node,None)
   response=await tokenizer._post('/tokenize',json=prompt.tokenizer_payload(config.backend.model));response.raise_for_status();tokens=response.json()['tokens']
   first_tokens.append(tokens)
   samples.append({'session_id':task.runtime_session_id,'source_key':node.source_key,'input_tokens':node.planned_input_tokens,'tokens':tokens,'messages':prompt.messages})
   nexts=[n for n in task.requests if n.context_after==node.source_key and n.context_mode=='append']
   if nexts and len([s for s in samples if 'continuation_of' in s])==0:
    # Only a construction check; this placeholder is never sent to inference.
    nxt=nexts[0];follow=await builder.build(task,nxt,PromptExchange(prompt,'OK'))
    res=await tokenizer._post('/tokenize',json=follow.tokenizer_payload(config.backend.model));res.raise_for_status();ids=res.json()['tokens']
    common=next((i for i,(a,b) in enumerate(zip(tokens,ids)) if a!=b),min(len(tokens),len(ids)))
    samples.append({'continuation_of':node.source_key,'source_key':nxt.source_key,'prefix_common_tokens':common,'previous_tokens':len(tokens),'tokens':ids,'messages':follow.messages,'assistant_placeholder':'OK; construction-only'})
  pairs=[]
  for i,a in enumerate(first_tokens):
   for j,b in enumerate(first_tokens[:i]):
    common=next((k for k,(x,y) in enumerate(zip(a,b)) if x!=y),min(len(a),len(b)))
    pairs.append({'i':i,'j':j,'common_prefix_tokens':common,'shorter_input':min(len(a),len(b))})
  assert len(first_tokens)==6 and all(p['common_prefix_tokens']<p['shorter_input']/2 for p in pairs),pairs
  continuation=[s for s in samples if 'continuation_of' in s];assert continuation and continuation[0]['prefix_common_tokens']>=continuation[0]['previous_tokens']-16
  (run/'prompt-check-samples.json').write_text(json.dumps(samples))
  (run/'prompt-check.json').write_text(json.dumps({'six_distinct_long_prefixes':True,'pairs':pairs,'continuation_common_tokens':continuation[0]['prefix_common_tokens'],'previous_tokens':continuation[0]['previous_tokens'],'inference_requests':0,'planned_requests':sum(n.node_type=='request' for t in plan.tasks for n in t.requests)},indent=2))
 finally:await tokenizer.close()
asyncio.run(main())
