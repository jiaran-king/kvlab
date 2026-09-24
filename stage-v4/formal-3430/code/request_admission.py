"""Stage-v4 only: admit sessions together, limit actual HTTP requests to three."""
import asyncio
import json
import time
from dataclasses import replace
from pathlib import Path


def install(executor_class, transport_class, run):
    run = Path(run)
    original_send = transport_class.send

    async def execute(self):
        self.transport._request_slots = asyncio.Semaphore(self.config.experiment.max_concurrency)
        self.transport._active_requests = 0
        self.transport._sample_counts = {}
        async def session(task):
            now = time.monotonic()
            result = await self._execute_task(task)
            return replace(result, enqueued_clock=now, permit_acquired_clock=now,
                           finished_clock=time.monotonic(), permit_wait_seconds=0)
        return tuple(await asyncio.gather(*(session(task) for task in self.plan.tasks)))

    async def send(self, task, node, prompt):
        enqueued = time.monotonic()
        await asyncio.sleep(0)  # Let already-ready sessions compete before continuation.
        async with self._request_slots:
            acquired = time.monotonic()
            self._active_requests += 1
            record = {'request_id': node.runtime_request_id, 'session_id': task.runtime_session_id,
                      'actor_id': node.actor_id, 'source_key': node.source_key,
                      'enqueued_monotonic': enqueued, 'acquired_monotonic': acquired,
                      'acquired_time': time.time(), 'admission_wait_seconds': acquired-enqueued,
                      'inflight_at_admission': self._active_requests}
            key = task.runtime_session_id
            count = self._sample_counts.get(key, 0)
            if (node.planned_input_tokens or 0) >= 16000 and count < 2:
                sample = dict(record, system=prompt.system, tools=prompt.tools,
                              messages=prompt.messages, context_after=node.context_after)
                with (run/'prompt-samples.jsonl').open('a') as f:
                    f.write(json.dumps(sample)+'\n')
                self._sample_counts[key] = count+1
            try:
                return await original_send(self, task, node, prompt)
            finally:
                record.update(finished_monotonic=time.monotonic(), finished_time=time.time())
                self._active_requests -= 1
                with (run/'request-admission.jsonl').open('a') as f:
                    f.write(json.dumps(record)+'\n')
    executor_class.execute = execute
    transport_class.send = send
