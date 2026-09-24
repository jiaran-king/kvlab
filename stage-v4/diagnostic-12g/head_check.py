import os,json,signal,subprocess,time
from pathlib import Path
out={'time':time.time(),'known_residues':[]}
for d in Path('/proc').iterdir():
 if not d.name.isdigit():continue
 try:
  cmd=(d/'cmdline').read_bytes().split(b'\0');args=[x.decode(errors='replace') for x in cmd if x]
  if args not in [['codex','--version'],['codex','app-server','proxy']]:continue
  exe=os.readlink(d/'exe');status=(d/'status').read_text();ppid=next(l.split()[1] for l in status.splitlines() if l.startswith('PPid:'))
  if Path(exe).name!='codex' or d.stat().st_uid!=os.getuid():continue
  row={'pid':int(d.name),'ppid':ppid,'args':args,'exe':exe,'cwd':os.readlink(d/'cwd'),'stat':(d/'stat').read_text(),'parent_args':(Path('/proc')/ppid/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace')}
  row['action']='readback only; one prior SIGTERM pass already attempted; unreaped residues not claimed removed';out['known_residues'].append(row)
 except (OSError,StopIteration):pass
for key,cmd in [('scheduler',['sinfo']),('jobs',['squeue','-u',os.environ['USER']]),('memory',['free','-m']),('load',['uptime']),('storage',['df','-h','/home/david_cwq/zhouziheng'])]:
 out[key]=subprocess.check_output(cmd,universal_newlines=True,timeout=15)
print(json.dumps(out,indent=2))
