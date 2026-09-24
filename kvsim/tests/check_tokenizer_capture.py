"""Compare local offline construction with 7 saved server-tokenized prompts."""
import asyncio,json
from pathlib import Path
from kvsim.replay_export import load_replay,make_tokenizer
ROOT=Path(__file__).resolve().parents[2]
async def main():
 C,analyze,plan_builder,Builder,Exchange,Client=load_replay(ROOT/'stage-v4/source/client')
 d=json.loads((ROOT/'stage-v4/formal-3429/replay-config.json').read_text());d['replay']['trace_path']=str(ROOT/'stage-v4/successful-425-trace.jsonl')
 config=C.model_validate(d);plan=plan_builder(config,analyze(config.replay.trace_path));tok=make_tokenizer(Client,ROOT/'output/kvsim/v03/tokenizer/tokenizer.json');builder=Builder(config,tok)
 saved=json.loads((ROOT/'stage-v4/formal-3429/prompt-check-samples.json').read_text());by_source={r['source_key']:r for r in saved};report=[]
 for task in plan.tasks:
  roots=[n for n in task.requests if n.node_type=='request' and n.context_after is None and (n.planned_input_tokens or 0)>=16000]
  n=min(roots,key=lambda n:n.planned_input_tokens);prompt=await builder.build(task,n,None);ids=list(await tok.input_tokens(prompt));ref=by_source[n.source_key];report.append({'source_key':n.source_key,'tokens':len(ids),'exact':ids==ref['tokens']})
  children=[x for x in task.requests if x.context_after==n.source_key and x.context_mode=='append' and x.source_key in by_source]
  for child in children:
   follow=await builder.build(task,child,Exchange(prompt,'OK'));tokens=list(await tok.input_tokens(follow));report.append({'source_key':child.source_key,'tokens':len(tokens),'exact':tokens==by_source[child.source_key]['tokens']})
 (ROOT/'output/kvsim/v03/tokenizer/server-capture-parity.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2));assert len(report)==7 and all(r['exact'] for r in report)
if __name__=='__main__':asyncio.run(main())
