"""Clean attributed shared-memory files from completed smoke3340, inside node01 allocation."""
import json,os,pathlib,socket,stat,sys
root,run=map(pathlib.Path,sys.argv[1:])
old=root/'evidence/pd-capacity-20260919/smoke-3340'
assert socket.gethostname()=='vllm-h20-01'
assert 'JobState=COMPLETED' in (old/'scheduler-final.txt').read_text()
names={'psm_020c8ddd': 251658260, 'psm_0cda6155': 25165836, 'psm_4bfb9e7f': 251658260, 'psm_546ca954': 167772190, 'psm_7c638612': 25165836, 'psm_8279c5e1': 251658260, 'psm_a3689fd2': 167772190, 'psm_f5fe803a': 251658260, 'sem.mp-6tmg1wm1': 32, 'sem.mp-a7v7tvhz': 32, 'sem.mp-gybfyyxy': 32, 'sem.mp-k5smlr3y': 32}
before=(old/'shm-before.txt').read_text();after=(old/'shm-after.txt').read_text()
for name in names:assert name not in before and name in after
for proc in pathlib.Path('/proc').iterdir():
 if not proc.name.isdigit():continue
 try:
  if proc.stat().st_uid!=os.getuid():continue
  maps=(proc/'maps').read_text()
  assert not any('/dev/shm/'+n in maps for n in names),f'File still mapped by {proc.name}'
 except (FileNotFoundError,ProcessLookupError):pass
records=[]
for name,size in names.items():
 p=pathlib.Path('/dev/shm')/name
 if not p.exists():records.append({'name':name,'already_absent':True});continue
 s=p.stat()
 assert stat.S_ISREG(s.st_mode) and s.st_uid==os.getuid() and s.st_size==size
 assert 1789824953<=s.st_mtime<=1789825663,(name,s.st_mtime)
 p.unlink();records.append({'name':name,'inode':s.st_ino,'bytes':size,'mtime':s.st_mtime,'removed':True})
(run/'previous-job-shm-cleanup.json').write_text(json.dumps(records,indent=2))
