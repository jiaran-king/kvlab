"""Three inference requests through the existing P/D proxy, with source metrics."""
import json,sys,time
from pathlib import Path
import httpx

run=Path(sys.argv[1]); p='http://127.0.0.1:18401'; d='http://127.0.0.1:18402'; proxy='http://127.0.0.1:18400'
client=httpx.Client(timeout=900,trust_env=False)
def snap(name):
    for role,url in [('P',p),('D',d)]:
        r=client.get(url+'/metrics');r.raise_for_status();(run/f'{name}-{role}.prom').write_text(r.text)
def request(name,content,output):
    messages=[{'role':'user','content':content}]
    tokenized=client.post(p+'/tokenize',json={'model':'dsv4-replay','messages':messages,'add_generation_prompt':True,'chat_template_kwargs':{'thinking':False}})
    tokenized.raise_for_status();td=tokenized.json()
    (run/f'{name}-tokenized.json').write_text(json.dumps(td))
    body={'model':'dsv4-replay','messages':messages,'max_tokens':output,'min_tokens':output,'ignore_eos':True,'temperature':0,'stream':True,'stream_options':{'include_usage':True},'chat_template_kwargs':{'thinking':False}}
    first=None;usage=None;chunks=[];start=time.monotonic()
    snap(name+'-before')
    start=time.monotonic()
    with client.stream('POST',proxy+'/v1/chat/completions',json=body,headers={'X-Request-Id':'pd-smoke-'+name}) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line.startswith('data: ') or line=='data: [DONE]':continue
            event=json.loads(line[6:]);chunks.append(event)
            if event.get('error'):raise RuntimeError(event)
            if event.get('usage'):usage=event['usage']
            for choice in event.get('choices',[]):
                delta=choice.get('delta',{})
                if first is None and any(delta.get(k) for k in ['content','reasoning','reasoning_content','tool_calls']):first=time.monotonic()-start
    result={'name':name,'tokenized_input':td.get('count',len(td.get('tokens',[]))),'output_target':output,'usage':usage,'ttft':first,'elapsed':time.monotonic()-start,'events':chunks}
    (run/f'{name}-result.json').write_text(json.dumps(result,indent=2))
    assert first is not None and usage and usage.get('completion_tokens')==output,result
    snap(name+'-after')
    print(json.dumps({k:v for k,v in result.items() if k!='events'}),flush=True)

request('cold','A capacity experiment. '+' test'*4096,8)
request('continuation','A capacity experiment. '+' test'*4096+' next'*128,8)
if '--warmup' in sys.argv:
    (run/'warmup-completed.json').write_text(json.dumps({'requests':2}))
    sys.exit(0)
# Calibrate longest smoke prompt locally through tokenizer, without model requests.
target=75340;count=target;content=''
for _ in range(5):
    content='B capacity experiment. '+' test'*count
    r=client.post(p+'/tokenize',json={'model':'dsv4-replay','messages':[{'role':'user','content':content}],'add_generation_prompt':True,'chat_template_kwargs':{'thinking':False}})
    r.raise_for_status();data=r.json();actual=data.get('count',len(data.get('tokens',[])))
    if abs(actual-target)<=8:break
    count+=target-actual
assert abs(actual-target)<=8,actual
request('longest',content,428)
(run/'P-openapi.json').write_text(client.get(p+'/openapi.json').text)
resets=[]
for attempt in range(6):
    r=client.post(p+'/reset_prefix_cache')
    resets.append({'status':r.status_code,'body':r.text})
    (run/'smoke-cache-reset.json').write_text(json.dumps(resets,indent=2))
    r.raise_for_status()
    if r.json().get('success') is True:break
    time.sleep(5)
else:raise RuntimeError('smoke finished but prefix cache reset failed')
(run/'smoke-completed.json').write_text(json.dumps({'requests':3,'note':'Review P local hits and D external transfer counters before formal replay.'}))
