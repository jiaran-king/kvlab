"""Capture real business HTTP payloads; fixed replay bypasses dynamic PromptBuilder."""
import copy,json
from dataclasses import asdict
from pathlib import Path

def load_payloads(path):
 rows=[json.loads(line) for line in Path(path).open()]
 by={r['source_key']:r for r in rows}
 if len(by)!=len(rows):raise ValueError('Duplicate source request capture')
 return by

def install(transport_class,builder_class,run,frozen=None):
 from agentinfer.agentbench.replay.prompt import SyntheticPrompt,PromptCalibration
 run=Path(run);saved=load_payloads(Path(frozen)/'request-bodies.jsonl') if frozen else None
 original=transport_class._body;seen=set()
 sink=(run/'request-bodies.jsonl').open('w',buffering=1048576)
 import atexit
 atexit.register(sink.close)
 if saved is not None:
  async def build(self,task,node,context=None):
   record=saved[node.source_key];p=copy.deepcopy(record['prompt'])
   cal=p.get('calibration')
   if cal:cal['count_history']=tuple(cal['count_history']);p['calibration']=PromptCalibration(**cal)
   p['messages']=tuple(p['messages']);p['tools']=tuple(p['tools'])
   p['preparation_seconds']=0.0
   return SyntheticPrompt(**p)
  builder_class.build=build
 def body(self,task,node,prompt):
  fresh=original(self,task,node,prompt)
  payload=fresh
  if saved is not None:
   payload=copy.deepcopy(saved[node.source_key]['body'])
   # Proxy creates fresh P/D request and transfer identities for every send.
   # This field carries the current plan's stable actor/request mapping.
   payload['vllm_xargs']=fresh['vllm_xargs']
  if node.source_key in seen:raise RuntimeError('Unexpected duplicate send; no implicit retry')
  if len(seen)>=425:raise RuntimeError('Formal request capture bound exceeded')
  seen.add(node.source_key)
  row={'source_key':node.source_key,'client_request_id':node.runtime_request_id,'context_after':node.context_after,
       'send_after':node.send_after,'seed':node.backend_sampling_seed,'body':payload,'prompt':asdict(prompt)}
  sink.write(json.dumps(row,ensure_ascii=False)+'\n');sink.flush()
  if sink.tell()>536870912:raise RuntimeError('Business payload storage exceeds 512 MiB bound')
  return payload
 transport_class._body=body
