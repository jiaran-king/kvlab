"""Verify filtered trace preserves original successful request lengths and dependencies."""
import json,sys
from pathlib import Path
from agentinfer.agentbench.replay.analyzer import analyze_replay_trace
from agentinfer.agentbench.replay.planner import build_replay_plan
from replay_config import make_config
base,run=map(Path,sys.argv[1:3]);s=base/'stage-v4'
original=[json.loads(l) for l in (s/'selected-trace.jsonl').read_text().splitlines()]
subset=[json.loads(l) for l in (s/'successful-425-trace.jsonl').read_text().splitlines()]
old=json.loads((s/'formal-3415/replay/replay-plan.json').read_text())
config=make_config(base,run);new=build_replay_plan(config,analyze_replay_trace(config.replay.trace_path)).to_dict()
def normalize(plan,trace):
 nodes={n['source_key']:n for t in plan['tasks'] for n in t['requests']}
 def source(k):return trace[int(k.split('-')[0][1:])-1]['request_id'] if k else None
 return {source(k):{'input':n['planned_input_tokens'],'output':n['planned_output_tokens'],'actor':n['actor_id'],'context_mode':n['context_mode'],'context_after':source(n['context_after']),'send_after':source(n['send_after'])} for k,n in nodes.items()}
a,b=normalize(old,original),normalize(new,subset)
assert len(b)==425
for key,value in b.items():assert a[key]==value,(key,a[key],value)
manifest=json.loads((s/'successful-425-manifest.json').read_text());assert set(b)==set(manifest['source_request_ids'])
(run/'subset-plan-check.json').write_text(json.dumps({'requests':len(b),'six_sessions':len(new['tasks'])==6,'source_lengths_actors_context_and_send_dependencies_equal':True,'selection':'exact source IDs of successful L outcomes','whole_session_timeout_seconds':5400,'http_timeout_seconds':900},indent=2))
(run/'frozen-plan.json').write_text(json.dumps(new))
print('PASS:425request IDs, lengths, actors and dependency edges preserved')
