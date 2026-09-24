"""Check six-session admission, three-request bound, cancellation and failure release."""
import asyncio
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace as NS
from request_admission import install

@dataclass
class Result:
    enqueued_clock: float=0
    permit_acquired_clock: float=0
    finished_clock: float=0
    permit_wait_seconds: float=0

async def check():
    with tempfile.TemporaryDirectory() as d:
        entered=[]; sent=[]; active=0; peak=0
        class Transport:
            async def send(self, task, node, prompt):
                nonlocal active,peak
                active+=1;peak=max(peak,active);sent.append(task.runtime_session_id)
                try:
                    await asyncio.sleep(.01)
                    if node.source_key=='bad':raise ValueError('expected')
                    return 'ok'
                finally:active-=1
        class Executor:
            async def _execute_task(self,task):
                entered.append(task.runtime_session_id)
                for i in range(2):
                    node=NS(runtime_request_id=f'{task.runtime_session_id}-{i}',actor_id='sub',planned_input_tokens=0,source_key='ok')
                    await self.transport.send(task,node,None)
                return Result()
        install(Executor,Transport,d)
        e=Executor();e.transport=Transport();e.config=NS(experiment=NS(max_concurrency=3))
        e.plan=NS(tasks=[NS(runtime_session_id=str(i)) for i in range(6)])
        result=await e.execute()
        assert len(result)==6 and len(entered)==6 and peak==3
        assert len(set(sent[:6]))==6, sent
        task=e.plan.tasks[0]
        bad=NS(runtime_request_id='bad',actor_id='sub',planned_input_tokens=0,source_key='bad')
        try:await e.transport.send(task,bad,None)
        except ValueError:pass
        else:raise AssertionError('failure swallowed')
        cancel=asyncio.create_task(e.transport.send(task,NS(runtime_request_id='cancel',actor_id='sub',planned_input_tokens=0,source_key='ok'),None))
        await asyncio.sleep(.001);cancel.cancel()
        try:await cancel
        except asyncio.CancelledError:pass
        assert e.transport._active_requests==0 and e.transport._request_slots._value==3
        records=[json.loads(l) for l in (Path(d)/'request-admission.jsonl').read_text().splitlines()]
        assert len(records)==14
        print('PASS: six sessions interleave; peak requests=3; errors/cancellation release slots; 14 admissions recorded')
asyncio.run(check())
