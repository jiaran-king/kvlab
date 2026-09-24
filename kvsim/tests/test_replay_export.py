"""Run with kvsim/.venv/bin/python; exercises the actual Replay planner.
Test captures are deliberately synthetic fixture values, not historical evidence.
"""
import importlib.util
import sys
import asyncio
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from kvsim.replay_export import export, load_replay

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'stage-v4/source/client'
TRACE=Path(__file__).parent/'fixtures/replay/trace.jsonl'
CONFIG=Path(__file__).parent/'fixtures/replay/config.json'

@unittest.skipUnless(sys.version_info >= (3, 12) and importlib.util.find_spec('httpx') is not None, 'Run with kvsim/.venv/bin/python for original Replay dependencies')
class ExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)
        C,a,p,*_=load_replay(SOURCE)
        data=json.loads(CONFIG.read_text());data['replay']['trace_path']=str(TRACE)
        self.config=C.model_validate(data);self.plan=p(self.config,a(TRACE))
        self.args=Namespace(agentinfer_source=str(SOURCE),agentinfer_commit='7f304555a8bc504c2c2257db2662e896eeeb5c30',config=str(CONFIG),trace=str(TRACE),captures=None,tokenizer=None,output=str(self.path/'workload.json'))

    def test_actual_plan_structure(self):
        self.assertEqual(len(self.plan.tasks),2)
        self.assertEqual(sum(n.node_type=='request' for t in self.plan.tasks for n in t.requests),4)

    def test_different_trace_and_resampling(self):
        C,a,p,*_=load_replay(SOURCE)
        rows=[json.loads(line) for line in TRACE.read_text().splitlines()]
        trace=self.path/'small-trace.jsonl'
        # A distinct, valid two-request trace drawn from one observed session.
        selected=[r for r in rows if r['session_id']==rows[0]['session_id']][:2]
        trace.write_text(''.join(json.dumps(r)+'\n' for r in selected))
        d=json.loads(CONFIG.read_text());d['replay']['trace_path']=str(trace);d['replay']['sample_seed']=17;d['experiment']['task_num']=3
        plan=p(C.model_validate(d),a(trace))
        self.assertEqual(len(plan.tasks),3)
        self.assertEqual(len({t.runtime_session_id for t in plan.tasks}),3)
        ids=[n.runtime_request_id for t in plan.tasks for n in t.requests]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertEqual(plan.to_dict(),p(C.model_validate(d),a(trace)).to_dict())

    def test_missing_assets_cannot_fallback(self):
        with self.assertRaisesRegex(ValueError,'no length-only fallback'):
            asyncio.run(export(self.args))

    def test_runtime_bound_capture_export(self):
        inputs={n.runtime_request_id:{'tokens':[10,11,i+20],'output_tokens':1} for i,n in enumerate(n for t in self.plan.tasks for n in t.requests) if n.node_type=='request'}
        capture=self.path/'capture.json';capture.write_text(json.dumps({'schema':'kvlab-token-capture/v1','metadata':{'tokenizer_sha256':'test-only','prompt_template':'test-only'},'inputs':inputs}))
        self.args.captures=str(capture);asyncio.run(export(self.args));first=Path(self.args.output).read_bytes();asyncio.run(export(self.args));self.assertEqual(first,Path(self.args.output).read_bytes())
        w=json.loads(first);self.assertEqual(len(w['requests']),4)
        by_id={r['runtime_request_id']:r for r in w['requests']}
        for t in self.plan.tasks:
            ids={n.source_key:n.runtime_request_id for n in t.requests}
            for n in t.requests:
                r=by_id[n.runtime_request_id]
                self.assertEqual(r['tokens'],inputs[n.runtime_request_id]['tokens'])
                self.assertEqual(r['send_after'],ids.get(n.send_after));self.assertEqual(r['context_after'],ids.get(n.context_after))
                self.assertEqual(r['effective_interval_seconds'],n.effective_interval_seconds)
        del inputs[next(iter(inputs))];capture.write_text(json.dumps({'schema':'kvlab-token-capture/v1','metadata':{'tokenizer_sha256':'test-only','prompt_template':'test-only'},'inputs':inputs}))
        with self.assertRaisesRegex(ValueError,'Missing capture'):
            asyncio.run(export(self.args))
