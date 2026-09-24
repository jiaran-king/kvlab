"""Bounded KVEvent capture plus two-second metrics snapshots; no model imports."""
import json,signal,sys,time,zlib
from pathlib import Path
import msgspec
import zmq
import httpx

run=Path(sys.argv[1]);deadline=time.monotonic()+10500;stop=False
ctx=zmq.Context();sub=ctx.socket(zmq.SUB);sub.setsockopt(zmq.SUBSCRIBE,b'');sub.setsockopt(zmq.RCVHWM,100000);sub.connect('tcp://127.0.0.1:18557')
replay=ctx.socket(zmq.DEALER);replay.connect('tcp://127.0.0.1:18558')
client=httpx.Client(timeout=4,trust_env=False)
seen=set();last=-1;counts={};errors=[];total_bytes=0;last_scrape=0;last_flush=0;last_replay=0;pending=False;last_clear=None;replay_rounds=0;last_batch_received=None

def term(*args):
 global stop
 stop=True
signal.signal(signal.SIGTERM,term);signal.signal(signal.SIGINT,term)

def state():
 ordered=sorted(seen)
 gaps=[(a+1,b-1) for a,b in zip([-1]+ordered,ordered) if b>a+1]
 return {'time':time.time(),'batches':len(seen),'last_sequence':last,'gaps':gaps,'counts':counts,'errors':errors,'raw_bytes':total_bytes,'replay_pending':pending,'last_clear_sequence':last_clear,'replay_rounds':replay_rounds,'last_batch_received':last_batch_received}

with (run/'kv-events.raw').open('wb',buffering=1024*1024) as raw,(run/'kv-events.jsonl').open('w',buffering=1024*1024) as events,(run/'metrics-samples.jsonl').open('w',buffering=1024*1024) as metrics:
 def capture(frames,origin):
  global last,total_bytes,last_clear,last_batch_received
  topic,seq_bytes,payload=frames
  if not seq_bytes:return
  seq=int.from_bytes(seq_bytes,'big')
  if seq in seen:return
  batch=msgspec.msgpack.decode(payload)
  ts,items=batch[:2];rank=batch[2] if len(batch)>2 else None
  compressed=zlib.compress(payload,1)
  raw.write(seq_bytes+len(compressed).to_bytes(4,'big')+compressed)
  total_bytes+=12+len(compressed)
  for item in items:
   item=dict(item);kind=item.get('type','unknown');counts[kind]=counts.get(kind,0)+1
   if kind=='AllBlocksCleared':last_clear=seq
   if 'token_ids' in item:item['token_ids_count']=len(item.pop('token_ids'))
   events.write(json.dumps({'sequence':seq,'timestamp':ts,'received_at':time.time(),'engine':rank,'origin':origin,'event':item},default=lambda b:b.hex() if isinstance(b,bytes) else str(b))+'\n')
  seen.add(seq);last=max(last,seq);last_batch_received=time.time()
 (run/'observer-ready.json').write_text(json.dumps({'time':time.time()}))
 try:
  while not stop and time.monotonic()<deadline:
   if sub.poll(100):capture(sub.recv_multipart(),'pub')
   while replay.poll(0):
    frames=replay.recv_multipart()
    if len(frames)!=4 or frames[0]!=b'':raise RuntimeError('unexpected replay frames')
    if frames[2]==b'\xff'*8:pending=False;replay_rounds+=1
    else:capture(frames[1:],'replay')
   now=time.monotonic()
   if now-last_replay>=5 and not pending:
    contiguous=-1
    while contiguous+1 in seen:contiguous+=1
    replay.send_multipart([b'',(contiguous+1).to_bytes(8,'big')]);pending=True;last_replay=now
   if now-last_scrape>=2:
    for role,port in [('P',18401),('D',18402)]:
     record={'time':time.time(),'role':role}
     try:
      response=client.get(f'http://127.0.0.1:{port}/metrics');response.raise_for_status();record['text']=response.text
     except httpx.HTTPError as e:record['error']=str(e)
     metrics.write(json.dumps(record)+'\n')
    last_scrape=now
   if now-last_flush>=1:
    raw.flush();events.flush();metrics.flush();(run/'observer-state.json').write_text(json.dumps(state()));last_flush=now
    if any((run/name).stat().st_size>512*2**20 for name in ['kv-events.raw','kv-events.jsonl','metrics-samples.jsonl']):raise RuntimeError('observer file bound exceeded')
 except BaseException as e:
  errors.append(type(e).__name__+': '+str(e));raise
 finally:
  raw.flush();events.flush();metrics.flush();(run/'observer-final.json').write_text(json.dumps(state(),indent=2));sub.close(0);replay.close(0);ctx.term();client.close()
