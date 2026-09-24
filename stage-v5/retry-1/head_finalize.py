"""One read/cleanup pass for the documented Codex reconnect exception."""
import json,os,signal,subprocess,time
from pathlib import Path
p=Path(__file__).parent;record={'time':time.time(),'residues':[]}
for pid in [929540,929600]:
 d=Path('/proc')/str(pid)
 try:
  args=d.joinpath('cmdline').read_bytes().split(b'\0');args=[a.decode() for a in args if a]
  exe=os.readlink(d/'exe');stat=d.joinpath('stat').read_text();cwd=os.readlink(d/'cwd')
  if args!=['codex','app-server','proxy'] or Path(exe).name!='codex' or d.stat().st_uid!=os.getuid():continue
  ppid=int(next(x.split()[1] for x in d.joinpath('status').read_text().splitlines() if x.startswith('PPid:')))
  row={'pid':pid,'args':args,'exe':exe,'cwd':cwd,'stat':stat,'parent':(Path('/proc')/str(ppid)/'cmdline').read_bytes().replace(b'\0',b' ').decode()}
  os.kill(pid,signal.SIGTERM);row['action']='one SIGTERM; no wait/retry; not claimed reaped';record['residues'].append(row)
 except (OSError,StopIteration):pass
for name,cmd in [('jobs',['squeue','-u',os.environ['USER']]),('scheduler',['sinfo']),('memory',['free','-m']),('load',['uptime']),('storage',['df','-h',str(p)]),('ports',['ss','-lnt']),('ipc',['ipcs','-m'])]:
 record[name]=subprocess.check_output(cmd,universal_newlines=True,timeout=15)
(p/'head-submit.json').write_text(json.dumps(record,indent=2));print(json.dumps({k:v for k,v in record.items() if k not in ['residues','ports','ipc']}))
