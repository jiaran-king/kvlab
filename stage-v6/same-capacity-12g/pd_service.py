"""One SLURM-assigned TP2 service; bounded monitoring and exact descendant cleanup."""
import csv, io, json, os, resource, signal, socket, subprocess, sys, time
from pathlib import Path
import psutil

root, run, role = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
soft,hard=resource.getrlimit(resource.RLIMIT_MEMLOCK)
resource.setrlimit(resource.RLIMIT_MEMLOCK,(hard,hard))
(run/f'{role}-memlock.json').write_text(json.dumps({'before':[soft,hard],'after':resource.getrlimit(resource.RLIMIT_MEMLOCK)}))
with (run/f'{role}-transport-probe.log').open('w') as log:
    subprocess.run([str(root/'runtime/bin/python'),str(root/'evidence/pd-capacity-20260919/pd_transport_probe.py')],stdout=log,stderr=subprocess.STDOUT,timeout=60,check=True)
port = 18401 if role == 'P' else 18402
stop = False
def request_stop(*args):
    global stop
    stop = True
signal.signal(signal.SIGTERM, request_stop)
signal.signal(signal.SIGINT, request_stop)
for n in (port, 18998, 18557, 18558) if role=='P' else (port,):
    with socket.socket() as s:
        s.bind(('127.0.0.1', n))
import torch
assert torch.cuda.device_count()==2, 'Each service must have exactly two SLURM devices'
devices=[{'uuid':str(torch.cuda.get_device_properties(i).uuid),
          'bytes':torch.cuda.get_device_properties(i).total_memory,
          'name':torch.cuda.get_device_name(i)} for i in range(2)]
gpu_output=subprocess.check_output(['nvidia-smi','--query-compute-apps=gpu_uuid,pid,process_name','--format=csv,nounits'],text=True)
own={d['uuid'].removeprefix('GPU-') for d in devices}
overlap=[r for r in csv.DictReader(io.StringIO(gpu_output)) if r['gpu_uuid'].strip().removeprefix('GPU-') in own and int(r[' pid'])!=os.getpid()]
assert not overlap, overlap
cmd=[str(root/'runtime/bin/python'),str(root/'evidence/pd-capacity-20260919/pd_entrypoint.py'),'serve','/home/david_cwq/jinghaoyu/models/DeepSeek-V4-Flash',
 '--served-model-name','dsv4-replay','--host','127.0.0.1','--port',str(port),
 '--tensor-parallel-size','2','--max-model-len','81920','--max-num-batched-tokens','8192',
 '--max-num-seqs','2' if role=='P' else '4','--gpu-memory-utilization','0.90',
 '--kv-cache-dtype','fp8','--block-size','256','--tokenizer-mode','deepseek_v4',
 '--trust-remote-code','--generation-config','vllm','--enforce-eager',
 '--enable-prefix-caching' if role=='P' else '--no-enable-prefix-caching',
 '--enable-prompt-tokens-details','--enable-request-id-headers',
 '--kv-transfer-config',json.dumps({'kv_connector':'MooncakeConnector','kv_role':'kv_producer' if role=='P' else 'kv_consumer'}),
 '--default-chat-template-kwargs',json.dumps({'thinking':False})]
if role=='P':
    cmd += ['--kv-events-config', json.dumps({'enable_kv_cache_events':True,'publisher':'zmq','endpoint':'tcp://127.0.0.1:18557','replay_endpoint':'tcp://127.0.0.1:18558','buffer_steps':10000}), '--kv-cache-metrics','--kv-cache-metrics-sample','0.01']
budget=os.environ.get('P_KV_BYTES' if role=='P' else 'D_KV_BYTES')
if budget: cmd+=['--kv-cache-memory-bytes',budget]
(run/f'{role}-config.json').write_text(json.dumps({'command':cmd,'pid':os.getpid(),'devices':devices,'job':os.environ['SLURM_JOB_ID'],'step':os.environ['SLURM_STEP_ID'],'cuda_visible_devices':os.environ.get('CUDA_VISIBLE_DEVICES'),'cgroup':Path('/proc/self/cgroup').read_text()},indent=2))
if role=='P':
    os.environ['PD_QUERY_DIAGNOSTIC_DIR']=str(run)
    os.environ['PYTHONPATH']=str(root/'evidence/pd-capacity-20260919/stage-v6/same-capacity-12g/hook')+os.pathsep+os.environ.get('PYTHONPATH','')
tracked={}; shared={}; server=None; code=1
try:
    with (run/f'{role}.log').open('w') as log:
        server=subprocess.Popen(cmd,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    deadline=time.monotonic()+6800
    stalled={}
    while not stop and not (run/'stop-services').exists() and time.monotonic()<deadline and server.poll() is None:
        procs=[psutil.Process(server.pid),*psutil.Process(server.pid).children(recursive=True)]
        for p in procs:
            try:
                tracked[p.pid]=p.create_time()
                try: mappings=(Path('/proc')/str(p.pid)/'maps').read_text().splitlines()
                except PermissionError: mappings=[]
                for line in mappings:
                    if '/dev/shm/psm_' in line and not line.endswith('(deleted)'):
                        path=Path(line.split()[-1])
                        try: shared[str(path)]=path.stat().st_ino
                        except FileNotFoundError:pass
                state=p.status()
                if state in ('disk-sleep','zombie'):
                    proc=Path('/proc')/str(p.pid)
                    cpu=p.cpu_times()
                    try:
                        io=p.io_counters();io_progress=(io.read_chars,io.write_chars)
                    except psutil.AccessDenied:
                        io_progress=(None,None)
                    stat=(proc/'stat').read_text().rsplit(')',1)[1].split()
                    progress=(cpu.user,cpu.system,*io_progress,stat[7],stat[9])
                    old=stalled.get(p.pid)
                    since=old[1] if old and old[0]==progress else time.monotonic()
                    stalled[p.pid]=(progress,since)
                    with (run/f'{role}-io-waits.jsonl').open('a') as f:
                        f.write(json.dumps({'pid':p.pid,'time':time.time(),'status':state,'wchan':(proc/'wchan').read_text(),'progress':progress,'no_progress_seconds':time.monotonic()-since})+'\n')
                    if time.monotonic()-since>=30:
                        raise RuntimeError(f'persistent task {state} without CPU/I/O/page-fault progress: {p.pid}')
                else:stalled.pop(p.pid,None)
            except (psutil.NoSuchProcess,FileNotFoundError): pass
        (run/f'{role}-tracked.json').write_text(json.dumps(tracked))
        if len(procs)>96 or psutil.virtual_memory().available<8*2**30 or (run/f'{role}.log').stat().st_size>256*2**20:
            raise RuntimeError('process/memory/log resource bound exceeded')
        time.sleep(5)
    code=0 if stop or (run/'stop-services').exists() else server.poll()
    if code is None: raise TimeoutError('service lifetime exhausted')
finally:
    if server is not None:
        try:
            for p in [psutil.Process(server.pid),*psutil.Process(server.pid).children(recursive=True)]: tracked[p.pid]=p.create_time()
        except psutil.NoSuchProcess: pass
        if server.poll() is None: os.killpg(server.pid,signal.SIGTERM)
        try: server.wait(timeout=15)
        except subprocess.TimeoutExpired: pass
        for pid,stamp in tracked.items():
            try:
                p=psutil.Process(pid)
                if p.create_time()==stamp and p.status()!='zombie': p.kill()
            except psutil.NoSuchProcess: pass
        try: server.wait(timeout=5)
        except subprocess.TimeoutExpired: pass
        time.sleep(2)
    remains=[]
    for pid,stamp in tracked.items():
        try:
            p=psutil.Process(pid)
            if p.create_time()==stamp: remains.append({'pid':pid,'status':p.status()})
        except psutil.NoSuchProcess: pass
    removed=[]
    if not remains:
        for path,inode in shared.items():
            p=Path(path)
            try:
                s=p.stat()
                if s.st_ino==inode and s.st_uid==os.getuid():p.unlink();removed.append(path)
            except FileNotFoundError:pass
    (run/f'{role}-cleanup.json').write_text(json.dumps({'remaining':remains,'tracked':tracked,'returncode':code,'mapped_shm':shared,'removed_shm':removed},indent=2))
    if remains: code=2
sys.exit(code)
