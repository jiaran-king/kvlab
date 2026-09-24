"""Wait only for confirmed TCP TIME_WAIT before the unchanged service guard."""
import errno,json,socket,subprocess,sys,time
from pathlib import Path
PORTS=(18400,18401,18402,18998,18557,18558)
def probe(port):
 with socket.socket() as s:s.bind(('127.0.0.1',port))
def tcp(port,state):
 return subprocess.check_output(['ss','-H','-tan','state',state,'sport','=',':'+str(port)],text=True,timeout=5).strip()
def wait_ports(run,ports=PORTS,bind=probe,state=tcp,clock=time.monotonic,sleep=time.sleep,limit=120):
 start=clock();events=[]
 try:
  while True:
   waiting=[]
   for port in ports:
    try:bind(port)
    except OSError as e:
     if e.errno!=errno.EADDRINUSE:raise
     listeners=state(port,'listening');tw=state(port,'time-wait')
     if listeners or not tw:raise RuntimeError(f'Port {port} busy without isolated TIME_WAIT: listener={listeners!r}, time_wait={tw!r}')
     waiting.append(port)
   events.append({'elapsed':clock()-start,'time_wait_ports':waiting})
   if not waiting:return
   if clock()-start>=limit:raise TimeoutError(f'TIME_WAIT did not clear within {limit}s')
   sleep(min(2,limit-(clock()-start)))
 finally:
  (Path(run)/'startup-port-wait.json').write_text(json.dumps({'events':events,'elapsed':clock()-start},indent=2))
if __name__=='__main__':wait_ports(sys.argv[1])
