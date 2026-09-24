"""Join existing plan seeds to bounded Proxy phase logs; no timing redefinition."""
import csv,json,sys
from pathlib import Path
from collections import defaultdict,Counter
run=Path(sys.argv[1]);source=[json.loads(l) for l in Path('evidence/selected-trace.jsonl').read_text().splitlines()]
plan=json.loads((run/'replay/replay-plan.json').read_text())
events=[]
for line in (run/'proxy-step.log').read_text().splitlines():
 if line.startswith('{'):
  try:events.append(json.loads(line))
  except ValueError:pass
by_id=defaultdict(list);by_seed=defaultdict(list)
for event in events:
 by_id[event['request_id']].append(event)
 if event['event']=='proxy_received' and event.get('seed') is not None:by_seed[event['seed']].append(event['request_id'])
rows=[]
for task in plan['tasks']:
 for node in task['requests']:
  if node['node_type']!='request':continue
  original=source[int(node['source_key'].split('-')[0][1:])-1]
  ids=by_seed[node['backend_sampling_seed']]
  phases=by_id[ids[0]] if len(ids)==1 else []
  lookup={e['event']:e for e in phases}
  row={'trace_request_id':original['request_id'],'source_key':node['source_key'],'runtime_request_id':node['runtime_request_id'],'seed':node['backend_sampling_seed'],'proxy_id':ids[0] if len(ids)==1 else None,'proxy_id_match_count':len(ids),'planned_input':node['planned_input_tokens'],'planned_output':node['planned_output_tokens']}
  for phase in ['proxy_received','P_http_start','P_http_response','P_http_error','D_http_headers','D_first_chunk','D_stream_end']:
   row[phase+'_time']=lookup.get(phase,{}).get('time')
  for role,phase in [('P','P_http_response'),('D','D_http_headers')]:
   row[role+'_status']=lookup.get(phase,{}).get('status');row[role+'_upstream_header_id']=lookup.get(phase,{}).get('upstream_request_id')
  row['P_error_type']=lookup.get('P_http_error',{}).get('error_type')
  row['P_http_seconds']=(row['P_http_response_time']-row['P_http_start_time']) if row['P_http_response_time'] is not None and row['P_http_start_time'] is not None else None
  rows.append(row)
with (run/'proxy-phases.csv').open('w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
summary={'planned_rows':len(rows),'unique_seed_proxy_matches':sum(r['proxy_id_match_count']==1 for r in rows),'P_http_200':sum(r['P_status']==200 for r in rows),'P_http_errors':sum(r['P_error_type'] is not None for r in rows),'D_stream_ends':sum(r['D_stream_end_time'] is not None for r in rows),'all_log_phase_counts':dict(Counter(e['event'] for e in events)),'timing_note':'P_http_seconds includes HTTP/queue/inference; D_first_chunk is raw stream data, not client valid-token TTFT.'}
(run/'proxy-phase-summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2))
