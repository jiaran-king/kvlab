"""Read captured allocation snapshots; do not touch live or unrelated processes."""
import csv,io,json,re,sys
from pathlib import Path
r=Path(sys.argv[1]);result={};tracked=set();owned_shm=set();uuids=set()
for role in ['P','D']:
 c=json.loads((r/f'{role}-cleanup.json').read_text());result[role+'_remaining']=c['remaining'];tracked.update(map(int,c['tracked']));owned_shm.update(c['mapped_shm'])
 cfg=json.loads((r/f'{role}-config.json').read_text());uuids.update(x['uuid'].removeprefix('GPU-') for x in cfg['devices'])
c=json.loads((r/'controller-cleanup.json').read_text());result['controller_remaining']=c['remaining'];tracked.update(x['pid'] for x in c['children'])
processes=(r/'processes-after.txt').read_text().splitlines();pids={int(line.split()[1]) for line in processes[1:] if len(line.split())>2 and line.split()[1].isdigit()}
result['tracked_pids_remaining']=sorted(tracked&pids)
result['owned_gpu_applications']=[]
for row in csv.DictReader(io.StringIO((r/'gpu-apps-after.csv').read_text())):
 row={k.strip():v.strip() for k,v in row.items()}
 if row.get('gpu_uuid','').removeprefix('GPU-') in uuids:result['owned_gpu_applications'].append(row)
ports=(r/'ports-after.txt').read_text();result['owned_listeners_remaining']=[l for l in ports.splitlines() if any(re.search(r':'+str(p)+r'\s',l) for p in [18400,18401,18402,18998,18557,18558])]
shm=(r/'shm-after.txt').read_text();result['owned_shm_remaining']=[s for s in owned_shm if any(line.split()[-1]==Path(s).name for line in shm.splitlines() if line.split())]
result['ipc_unchanged']=(r/'ipc-before.txt').read_text()==(r/'ipc-after.txt').read_text()
result['scheduler_completed_zero']='JobState=COMPLETED' in (r/'scheduler-final.txt').read_text() and 'ExitCode=0:0' in (r/'scheduler-final.txt').read_text()
result['resource_cleanup_passed']=not any(result[k] for k in ['P_remaining','D_remaining','controller_remaining','tracked_pids_remaining','owned_gpu_applications','owned_listeners_remaining','owned_shm_remaining']) and result['ipc_unchanged']
result['host_health_requires_review']=['memory-before.txt','memory-after.txt','load-before.txt','load-after.txt','storage-before.txt','storage-after.txt','processes-before.txt','processes-after.txt']
(r/'cleanup-audit.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
