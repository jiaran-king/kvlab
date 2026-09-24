import os,json,pathlib
print("AUDIT_JOB",os.environ.get("SLURM_JOB_ID"))
pids=[2475272, 2475275, 2482633, 2482639, 2482653, 2482654, 2486155, 2486156, 2486159, 2486160]
names=['psm_684f8874', 'psm_beb14779', 'sem.mp-yxci2rbj', 'psm_98b7a5bf', 'psm_1d45e6b4', 'sem.mp-fp0ajufi', 'psm_5c486bd8', 'sem.mp-b7dk25nl', 'psm_f489c5c6', 'sem.mp-_fiaseae', 'psm_ac70547e', 'psm_54013d90']
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
