"""Run the fixed selected trace once. Calling this consumes a formal-run slot."""
import fcntl,json,sys,time
from pathlib import Path
from agentinfer.agentbench.replay.config import ReplayBenchConfig
from agentinfer.agentbench.replay.runner import run_replay

base,run=map(Path,sys.argv[1:3]);label=sys.argv[3]
config=ReplayBenchConfig.model_validate({
 'experiment':{'task_num':None,'max_concurrency':3,'result_dir':str(run/'replay'),'task_timeout_seconds':3600,'run_timeout_seconds':4500},
 'backend':{'base_url':'http://127.0.0.1:18400','tokenizer_base_url':'http://127.0.0.1:18401','metrics_url':'http://127.0.0.1:18401/metrics','model':'dsv4-replay','endpoint':'/v1/chat/completions','tool_choice':'none'},
 'replay':{'trace_path':str(base/'selected-trace.jsonl'),'sample_seed':0,'interval_mode':'trace','trace_same_agent_gap_scale':0.1,'trace_same_agent_gap_offset_seconds':0,'max_input_tokens':None,'max_output_tokens':None,'context_adjustment_mode':'adaptive','request_timeout_seconds':900}})
(run/'replay-config.json').write_text(config.model_dump_json(indent=2))
# Serial controller owns service resources; file lock also prevents budget overspend.
with (base/'stage-v3/formal-runs.jsonl').open('a+') as ledger:
 fcntl.flock(ledger,fcntl.LOCK_EX)
 ledger.seek(0);previous=[json.loads(x) for x in ledger if x.strip()]
 assert label=='M2', 'Only M2 is authorized in this stage'
 assert len(previous)<1,'Formal-run budget exhausted'
 assert not any(x['run']==str(run) for x in previous),'This formal run was already started'
 ledger.write(json.dumps({'ordinal':len(previous)+1,'label':label,'run':str(run),'started_at':time.time(),'planned_requests':174})+'\n');ledger.flush()
print(run_replay(config),flush=True)
