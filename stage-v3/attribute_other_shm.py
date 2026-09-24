import os,json,pathlib
print("AUDIT_JOB",os.environ.get("SLURM_JOB_ID"))
pids=[2225276, 2232097, 2232098, 2236491, 2236492]
names=['sem.mp-l746xbrd', 'psm_67fbf33b', 'sem.mp-p5p828gj', 'psm_afabd325', 'psm_98c89fe6', 'psm_5f7d81f7']
for pid in pids:
 p=pathlib.Path('/proc')/str(pid)
 try:
  cgroup=(p/'cgroup').read_text()
  record={'pid':pid,'cgroup':cgroup,'cmd':(p/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace'),'exe':os.readlink(str(p/'exe')),'cwd':os.readlink(str(p/'cwd')),'stat':(p/'stat').read_text()}
  record['matching_shm_maps']=[l for l in (p/'maps').read_text().splitlines() if any('/dev/shm/'+name in l for name in names)]
  record['all_shm_maps']=[l for l in (p/'maps').read_text().splitlines() if '/dev/shm/' in l]
  print(json.dumps(record))
 except (OSError,PermissionError) as e:print(json.dumps({'pid':pid,'read_error':str(e)}))

for name in names:
 try:
  st=os.stat('/dev/shm/'+name);print(json.dumps({'shm':name,'inode':st.st_ino,'size':st.st_size}))
 except OSError as e:print(json.dumps({'shm':name,'error':str(e)}))

try:
 print("ROOT_TRANSIENT_PID",pathlib.Path("/proc/2283418/stat").read_text())
except OSError as e:print("ROOT_TRANSIENT_PID",str(e))
