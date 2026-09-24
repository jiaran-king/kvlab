"""Run the fixed selected trace once. Calling this consumes a formal-run slot."""
import fcntl,json,sys,time,os
from pathlib import Path
from agentinfer.agentbench.replay.config import ReplayBenchConfig
from agentinfer.agentbench.replay.runner import run_replay
from agentinfer.agentbench.replay.executor import ReplayExecutor
from agentinfer.agentbench.replay.transport import ReplayTransport
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'stage-v4'))
from request_admission import install

base,run=map(Path,sys.argv[1:3]);label=sys.argv[3]
install(ReplayExecutor, ReplayTransport, run)
from client_capture import install as install_capture
from agentinfer.agentbench.replay.prompt import PromptBuilder
install_capture(ReplayTransport,PromptBuilder,run,os.environ.get('FROZEN_RUN'))
manifest=json.loads((base/'stage-v4/successful-425-manifest.json').read_text())
from replay_config import make_config
config=make_config(base,run)
(run/'replay-config.json').write_text(config.model_dump_json(indent=2))
# Serial controller owns service resources; file lock also prevents budget overspend.
with (base/'stage-v5/retry-1/formal-runs.jsonl').open('a+') as ledger:
 fcntl.flock(ledger,fcntl.LOCK_EX)
 ledger.seek(0);previous=[json.loads(x) for x in ledger if x.strip()]
 assert label in ['C12','F12','F24']
 assert len(previous)<3,'Formal-run budget exhausted'
 assert not any(x['label']==label for x in previous),'This formal run was already started'
 ledger.write(json.dumps({'ordinal':len(previous)+1,'label':label,'run':str(run),'started_at':time.time(),'planned_requests':manifest['planned_requests']})+'\n');ledger.flush()
print(run_replay(config),flush=True)
