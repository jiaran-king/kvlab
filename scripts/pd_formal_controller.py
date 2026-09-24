"""One formal capacity point after the independent smoke has been accepted."""
import json,os,signal,socket,subprocess,sys,time,urllib.request
from pathlib import Path

root,run=map(Path,sys.argv[1:3]);label=sys.argv[3];base=root/'evidence/pd-capacity-20260919'; children=[]
def interrupted(*args):raise KeyboardInterrupt()
signal.signal(signal.SIGTERM,interrupted)
signal.signal(signal.SIGINT,interrupted)
def launch(cmd,name):
    f=(run/(name+'-step.log')).open('w')
    child=subprocess.Popen(cmd,stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
    f.close();children.append((name,child));return child
def alive():
    for name,proc in children:
        if proc.poll() is not None:raise RuntimeError(f'{name} exited {proc.returncode}')
def wait_ready(url):
    deadline=time.monotonic()+1800
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while time.monotonic()<deadline:
        alive()
        try:
            with opener.open(url,timeout=5) as r:
                if r.status==200:return
        except Exception:pass
        time.sleep(5)
    raise TimeoutError(url)
try:
    for port in [18400,18401,18402,18998]:
        with socket.socket() as s:s.bind(('127.0.0.1',port))
    for role in ['P','D']:
        launch(['srun','--exclusive','--exact','--nodes=1','--ntasks=1','--cpus-per-task=16','--mem=256G','--gres=gpu:h20:2','--time=01:40:00',str(root/'runtime/bin/python'),str(base/'pd_service.py'),str(root),str(run),role],role)
    wait_ready('http://127.0.0.1:18401/health')
    wait_ready('http://127.0.0.1:18402/health')
    (run/'services-ready.json').write_text(json.dumps({'time':time.time()}))
    proxy=launch([str(root/'runtime/bin/python'),str(base/'mooncake_connector_proxy.py'),'--prefill','http://127.0.0.1:18401','18998','--decode','http://127.0.0.1:18402','--port','18400'],'proxy')
    wait_ready('http://127.0.0.1:18400/openapi.json')
    time.sleep(3)
    import httpx
    client=httpx.Client(timeout=900,trust_env=False)
    warmup=launch([str(root/'runtime/bin/python'),str(base/'pd_smoke.py'),str(run),'--warmup'],'warmup')
    if warmup.wait(timeout=900)!=0:raise RuntimeError('warmup failed')
    # Wait for requests/transfers to drain before resetting cache.
    for port in [18401,18402]:
        r=client.get(f'http://127.0.0.1:{port}/metrics');r.raise_for_status()
        (run/f'pre-reset-{port}.prom').write_text(r.text)
    resets=[]
    for attempt in range(6):
        reset=client.post('http://127.0.0.1:18401/reset_prefix_cache')
        resets.append({'status':reset.status_code,'body':reset.text})
        (run/'cache-reset.json').write_text(json.dumps(resets))
        reset.raise_for_status()
        if reset.json().get('success') is True:break
        time.sleep(5)
    else:raise RuntimeError('P cache did not become resettable after warmup; no formal replay started')
    for role,port in [('P',18401),('D',18402)]:
        r=client.get(f'http://127.0.0.1:{port}/metrics');r.raise_for_status()
        (run/f'formal-before-{role}.prom').write_text(r.text)
    replay=launch([str(root/'client/bin/python'),str(base/'replay_selected.py'),str(base),str(run),label],'replay')
    deadline=time.monotonic()+4600
    while replay.poll() is None and time.monotonic()<deadline:
        for name,proc in children:
            if name in ('P','D','proxy') and proc.poll() is not None:raise RuntimeError(f'{name} exited during formal replay')
        time.sleep(5)
    for role,port in [('P',18401),('D',18402)]:
        r=client.get(f'http://127.0.0.1:{port}/metrics');r.raise_for_status()
        (run/f'formal-after-{role}.prom').write_text(r.text)
    if replay.poll()!=0:raise RuntimeError(f'replay failed/timed out: {replay.poll()}')

finally:
    # Stop client/proxy first, then srun forwards TERM to role wrappers.
    for name,child in reversed(children):
        if child.poll() is None and name not in ('P','D'):os.killpg(child.pid,signal.SIGTERM)
    (run/'stop-services').touch()
    deadline=time.monotonic()+80
    while time.monotonic()<deadline and any(c.poll() is None for _,c in children):time.sleep(1)
    for name,child in children:
        if child.poll() is None:child.send_signal(signal.SIGTERM)
    for name,child in children:
        try:child.wait(timeout=35)
        except subprocess.TimeoutExpired:pass
    remaining=[{'name':n,'pid':c.pid} for n,c in children if c.poll() is None]
    (run/'controller-cleanup.json').write_text(json.dumps({'children':[{'name':n,'pid':c.pid,'returncode':c.poll()} for n,c in children],'remaining':remaining},indent=2))
    if remaining:raise RuntimeError(f'controller children remain: {remaining}')
