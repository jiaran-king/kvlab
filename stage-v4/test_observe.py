"""Exercise live/replayed event deduplication and raw preservation without GPUs."""
import json,subprocess,sys,tempfile,time,zlib
from pathlib import Path
import msgspec,zmq
ctx=zmq.Context();pub=ctx.socket(zmq.PUB);router=ctx.socket(zmq.ROUTER)
pub.bind('tcp://127.0.0.1:18557');router.bind('tcp://127.0.0.1:18558')
with tempfile.TemporaryDirectory() as d:
 run=Path(d);p=subprocess.Popen([sys.executable,str(Path(__file__).with_name('observe.py')),d])
 try:
  batches=[msgspec.msgpack.encode([time.time(),[{'type':'BlockStored','block_hashes':[b'abc'],'token_ids':[1,2],'group_idx':0}],0]),msgspec.msgpack.encode([time.time(),[{'type':'BlockRemoved','block_hashes':[b'abc',b'def'],'group_idx':0}],0])]
  deadline=time.monotonic()+20;sent=False
  while time.monotonic()<deadline:
   if router.poll(100):
    identity,empty,start=router.recv_multipart()
    for seq,body in enumerate(batches):
     if seq>=int.from_bytes(start,'big'):router.send_multipart([identity,b'',b'',seq.to_bytes(8,'big'),body])
    router.send_multipart([identity,b'',b'',b'\xff'*8,b''])
    pub.send_multipart([b'',(1).to_bytes(8,'big'),batches[1]]);sent=True
   state=run/'observer-state.json'
   if state.exists():
    result=json.loads(state.read_text())
    if result['batches']==2 and not result['replay_pending']:break
  else:raise RuntimeError('capture timeout')
  p.terminate();p.wait(timeout=10)
  assert p.returncode==0
  result=json.loads((run/'observer-final.json').read_text());assert result['gaps']==[] and result['counts']=={'BlockStored':1,'BlockRemoved':1},result
  raw=(run/'kv-events.raw').read_bytes();offset=0;found={}
  while offset<len(raw):
   seq=int.from_bytes(raw[offset:offset+8],'big');n=int.from_bytes(raw[offset+8:offset+12],'big');found[seq]=zlib.decompress(raw[offset+12:offset+12+n]);offset+=12+n
  assert found==dict(enumerate(batches))
  print('PASS: replay recovery, duplicate suppression, raw lossless payloads, clean termination')
 finally:
  if p.poll() is None:p.terminate();p.wait(timeout=10)
pub.close(0);router.close(0);ctx.term()
