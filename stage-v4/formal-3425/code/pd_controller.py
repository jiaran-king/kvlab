"""One formal capacity point after the independent smoke has been accepted."""
import json,re,os,signal,socket,subprocess,sys,time,urllib.request
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
def observer_state():
    path=run/'observer-state.json'
    if not path.exists():return {}
    try:return json.loads(path.read_text())
    except json.JSONDecodeError:return {}
def wait_observer(predicate):
    deadline=time.monotonic()+45
    while time.monotonic()<deadline:
        for name,proc in children:
            if name in ('P','D','proxy','observer') and proc.poll() is not None:raise RuntimeError(f'{name} exited {proc.returncode}')
        state=observer_state()
        if predicate(state):return state
        time.sleep(.5)
    raise RuntimeError('KV event boundary not observed: '+str(observer_state()))
def wait_idle():
    deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        vals=[]
        for port in [18401,18402]:
            r=client.get(f'http://127.0.0.1:{port}/metrics');r.raise_for_status()
            vals += [float(line.rsplit(' ',1)[1]) for line in r.text.splitlines() if line.startswith(('vllm:num_requests_running{','vllm:num_requests_waiting{'))]
        if len(vals)==4 and all(v==0 for v in vals):return
        time.sleep(1)
    raise RuntimeError('requests did not drain')
try:
    for port in [18400,18401,18402,18998,18557,18558]:
        with socket.socket() as s:s.bind(('127.0.0.1',port))
    subprocess.run([str(root/'client/bin/python'),str(base/'stage-v4/check_subset_plan.py'),str(base),str(run)],check=True,timeout=60)
    for role in ['P','D']:
        launch(['srun','--exclusive','--exact','--nodes=1','--ntasks=1','--cpus-per-task=16','--mem=256G','--gres=gpu:h20:2','--time=01:55:00',str(root/'runtime/bin/python'),str(base/'stage-v4/pd_service.py'),str(root),str(run),role],role)
    wait_ready('http://127.0.0.1:18401/health')
    wait_ready('http://127.0.0.1:18402/health')
    (run/'services-ready.json').write_text(json.dumps({'time':time.time()}))
    proxy=launch([str(root/'runtime/bin/python'),str(base/'stage-v3/mooncake_connector_proxy.py'),'--prefill','http://127.0.0.1:18401','18998','--decode','http://127.0.0.1:18402','--port','18400'],'proxy')
    wait_ready('http://127.0.0.1:18400/openapi.json')
    time.sleep(3)
    import httpx
    client=httpx.Client(timeout=900,trust_env=False)
    observer=launch([str(root/'runtime/bin/python'),str(base/'stage-v4/observe.py'),str(run)],'observer')
    wait_observer(lambda s:bool(s))
    prompt_check=launch([str(root/'client/bin/python'),str(base/'stage-v4/prompt_check.py'),str(base),str(run)],'prompt-check')
    if prompt_check.wait(timeout=900)!=0:raise RuntimeError('prompt construction check failed')
    warmup=launch([str(root/'runtime/bin/python'),str(base/'pd_smoke.py'),str(run),'--warmup'],'warmup')
    if warmup.wait(timeout=900)!=0:raise RuntimeError('warmup failed')
    wait_idle()
    wait_observer(lambda s:s.get('counts',{}).get('BlockStored',0)>0 and not s.get('gaps'))
    # Wait for requests/transfers to drain before resetting cache.
    for port in [18401,18402]:
        r=client.get(f'http://127.0.0.1:{port}/metrics');r.raise_for_status()
        (run/f'pre-reset-{port}.prom').write_text(r.text)
    resets=[]
    clears_before=observer_state().get('counts',{}).get('AllBlocksCleared',0)
    for attempt in range(6):
        reset=client.post('http://127.0.0.1:18401/reset_prefix_cache')
        resets.append({'status':reset.status_code,'body':reset.text})
        (run/'cache-reset.json').write_text(json.dumps(resets))
        reset.raise_for_status()
        if reset.json().get('success') is True:break
        time.sleep(5)
    else:raise RuntimeError('P cache did not become resettable after warmup; no formal replay started')
    boundary=observer_state()
    boundary.update(reset_success=True,reset_time=time.time(),clears_before=clears_before,reset_event_may_be_deferred=True)
    (run/'event-formal-start.json').write_text(json.dumps(boundary))
    for role,port in [('P',18401),('D',18402)]:
        r=client.get(f'http://127.0.0.1:{port}/metrics');r.raise_for_status()
        (run/f'formal-before-{role}.prom').write_text(r.text)
    replay=launch([str(root/'client/bin/python'),str(base/'stage-v4/replay_v4.py'),str(base),str(run),label],'replay')
    deadline=time.monotonic()+5800
    while replay.poll() is None and time.monotonic()<deadline:
        for name,proc in children:
            if name in ('P','D','proxy','observer') and proc.poll() is not None:raise RuntimeError(f'{name} exited during formal replay')
        time.sleep(5)
    if replay.poll() is None:raise TimeoutError('formal replay deadline')
    wait_idle()
    for role,port in [('P',18401),('D',18402)]:
        r=client.get(f'http://127.0.0.1:{port}/metrics');r.raise_for_status()
        (run/f'formal-after-{role}.prom').write_text(r.text)
    # Scheduler publishes events with model outputs. Drain queued publication and replay tail.
    state=observer_state();rounds=state.get('replay_rounds',0);end_time=time.time()
    boundary=wait_observer(lambda s:s.get('replay_rounds',0)>=rounds+2 and not s.get('gaps') and time.time()-(s.get('last_batch_received') or 0)>=3)
    boundary.update(requests_drained_time=end_time)
    (run/'event-formal-end.json').write_text(json.dumps(boundary))
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
