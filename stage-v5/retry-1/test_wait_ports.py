import errno,tempfile
from pathlib import Path
from wait_ports import wait_ports
with tempfile.TemporaryDirectory() as d:
 t=[0];calls=[0]
 def bind(p):
  calls[0]+=1
  if calls[0]==1:raise OSError(errno.EADDRINUSE,'time wait')
 def state(p,s):return 'confirmed TIME_WAIT' if s=='time-wait' else ''
 wait_ports(d,ports=[12345],bind=bind,state=state,clock=lambda:t[0],sleep=lambda n:t.__setitem__(0,t[0]+n))
 assert calls[0]==2 and t[0]==2
 def busy(p):raise OSError(errno.EADDRINUSE,'listener')
 try:wait_ports(d,ports=[12345],bind=busy,state=lambda p,s:'listener',sleep=lambda n:(_ for _ in ()).throw(AssertionError('Must not wait for live listener')))
 except RuntimeError:pass
 else:raise AssertionError('live listener accepted')
 t[0]=0
 try:wait_ports(d,ports=[12345],bind=busy,state=state,clock=lambda:t[0],sleep=lambda n:t.__setitem__(0,t[0]+n),limit=4)
 except TimeoutError:assert t[0]==4
 else:raise AssertionError('bound not enforced')
print('PASS: confirmed TIME_WAIT waits then passes; live listener rejected immediately; timeout bounded.')
