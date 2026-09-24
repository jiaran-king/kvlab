import ast
import copy
import json
import unittest
from unittest.mock import patch
from pathlib import Path

from kvsim.engine import Pool, simulate
from kvsim.inputs import canonical, compile_scenario, prefix_key, segment, token_parts
from kvsim.profile import resolve


def req(rid, parts, parent=None, domain=0, session=None, output=0):
    return dict(id=rid, session=session or rid, parts=parts, output_tokens=output,
                send_after=parent, context_after=parent, source_kind='explicit_segments', p_domain=domain)


def case(requests, block=32, gib=16, domains=1):
    return compile_scenario(dict(workload='custom', requests=requests, p_domains=domains,
        config=dict(block_size=block, kv_gib=gib), execution=dict(concurrency=1)))


class MechanismTests(unittest.TestCase):
    def test_fragmentation_is_not_identity(self):
        a=req('a',[segment('X',100)])
        b=req('b',[dict(id='X',start=0,length=30),dict(id='X',start=30,length=70)])
        self.assertEqual(prefix_key(a,100),prefix_key(b,100))
        self.assertNotEqual(prefix_key(a,100),prefix_key(req('c',[segment('Y',100)]),100))

    def test_parent_context_is_in_identity(self):
        a=req('a',[segment('A',10),segment('X',10)])
        b=req('b',[segment('B',10),segment('X',10)])
        self.assertNotEqual(prefix_key(a,20),prefix_key(b,20))

    def test_same_content_cross_session_and_last_token(self):
        r=simulate(case([req('a',[segment('X',8192)]),req('b',[segment('X',8192)],'a')]))
        self.assertEqual(r['requests'][1]['adopted_cached_tokens'],4096)
        self.assertEqual(r['requests'][1]['input_compute_tokens'],4096)

    def test_cross_domain_no_sharing(self):
        r=simulate(case([req('a',[segment('X',8192)]),req('b',[segment('X',8192)],'a',1)],domains=2))
        self.assertEqual(r['requests'][1]['adopted_cached_tokens'],0)

    def test_d_output_not_cached(self):
        r=simulate(case([req('a',[segment('X',4096)],output=4096),
                        req('b',[segment('X',4096),segment('a/output',4096)],'a')]))
        self.assertEqual(r['requests'][1]['adopted_cached_tokens'],4096)
        self.assertEqual(r['requests'][1]['input_compute_tokens'],4096)

    def test_same_length_different_content_misses(self):
        r=simulate(case([req('a',[segment('X',8192)]),req('b',[segment('Y',8192)],'a')]))
        self.assertEqual(r['requests'][1]['adopted_cached_tokens'],0)

    def test_reset_content_does_not_clear_cache(self):
        a=req('a',[segment('X',8192)])
        b=req('b',[segment('Y',8192)],'a');b['context_mode']='reset';b['context_after']=None
        c=req('c',[segment('X',8192)],'b')
        r=simulate(case([a,b,c]))
        self.assertEqual(r['requests'][2]['adopted_cached_tokens'],4096)

    def test_pool_references_duplicates_and_eviction(self):
        p=Pool(4)
        a=p.allocate(0);b=p.allocate(0)
        p.publish(a,('g','X'),1);p.publish(b,('g','X'),1)
        self.assertEqual(len(p.index[('g','X')]),2)
        p.release(a,2)
        self.assertIsNotNone(p.lookup(('g','X')))
        p.touch(a)
        self.assertEqual(p.available(),1)
        p.allocate(3)
        p.release(b,4)
        replacement=p.allocate(5)
        self.assertEqual(replacement.id,b.id)
        self.assertEqual(a.refs,1)
        self.assertEqual(p.snapshot()['active'],3)

    def test_low_budget_reports_partial(self):
        s=case([req('a',[segment('X',20000)])],gib=.01)
        r=simulate(s)
        self.assertEqual(r['status'],'infeasible_under_fixed_trace')
        self.assertEqual(r['summary']['completed'],0)
        self.assertEqual(r['summary']['input_cache_fraction'],None)
        self.assertIn('capacity',r['failure']['reason'])

    def test_budget_failure_distinct(self):
        s=case([req('a',[segment('X',8192)])])
        next(e for e in s['events'] if e['kind']=='SCHEDULE')['budget']=1
        r=simulate(s)
        self.assertIn('scheduling_budget',r['failure']['reason'])

    def test_early_complete_invalid(self):
        s=case([req('a',[segment('X',4096)])])
        next(e for e in s['events'] if e['kind']=='P_RELEASE')['kind']='REQUEST_COMPLETE'
        with self.assertRaisesRegex(ValueError,'before P release'):
            simulate(s)

    def test_pending_state_not_published(self):
        s=case([req('a',[segment('X',8192)]),req('b',[segment('X',8192)])])
        s['execution']['concurrency']=2
        s['execution']['step_budget']=16384
        sequence=[('ARRIVE','a'),('ARRIVE','b'),('SCHEDULE','a'),('SCHEDULE','b'),
                  ('STEP_COMPLETE','a'),('STEP_COMPLETE','b'),('P_RELEASE','a'),('P_RELEASE','b'),
                  ('REQUEST_COMPLETE','a'),('REQUEST_COMPLETE','b')]
        s['events']=[dict(seq=i,tick=0,kind=k,request_id=r,**({'target':8192,'budget':8192} if k in ('SCHEDULE','STEP_COMPLETE') else {})) for i,(k,r) in enumerate(sequence)]
        r=simulate(s)
        self.assertEqual(r['requests'][1]['adopted_cached_tokens'],0)

    def test_sparse_groups_recheck_common_boundary(self):
        # A supports 4K/12K; B supports 4K/8K. min(max(A),max(B))
        # would incorrectly select 8K. Independent group eviction can leave
        # precisely these holes; the lookup fixture isolates that condition.
        requests=[req('a',[segment('X',16384)]),req('b',[segment('X',16384)],'a')]
        s=case(requests)
        holes={('SWA-0',prefix_key(requests[0],8192)),
               ('SWA-1',prefix_key(requests[0],12288))}
        original=Pool.lookup
        def lookup(pool,key):
            return None if key in holes else original(pool,key)
        with patch.object(Pool,'lookup',lookup):
            result=simulate(s)
        self.assertEqual(result['requests'][1]['adopted_cached_tokens'],4096)
        self.assertEqual(set(result['requests'][1]['limiting_groups']),{'SWA-0','SWA-1'})

    def test_export_roundtrip_and_no_mutation(self):
        s=compile_scenario({'synthetic':{'chains':2,'rounds':3}})
        original=json.dumps(s,sort_keys=True)
        r=simulate(s)
        r2=simulate(compile_scenario(json.loads(json.dumps(s))))
        self.assertEqual(r,r2)
        self.assertEqual(original,json.dumps(s,sort_keys=True))
        for p in r['per_p']:
            self.assertEqual(sum(p[k] for k in ('active','cached','empty','reserved')),r['profile']['num_blocks'])
        for row in r['requests']:
            self.assertEqual(row['p_input_tokens'],row['adopted_cached_tokens']+row['input_compute_tokens'])

    def test_real_tokens_share_across_captures(self):
        tokens=list(range(8192))
        r=simulate(case([req('a',token_parts(tokens)),req('b',token_parts(tokens),'a')]))
        self.assertEqual(r['requests'][1]['adopted_cached_tokens'],4096)

    def test_425_structure(self):
        s=compile_scenario({'workload':'replay425'})
        self.assertEqual(len(s['requests']),425)
        self.assertEqual(sum(sum(p['length'] for p in r['parts']) for r in s['requests']),13707996)
        self.assertTrue(any('NOT captured' in a for a in s['assumptions']))

    def test_source_layout_table_and_padding(self):
        root=Path(__file__).resolve().parents[1]/'source'
        text=(root/'ascend/vllm_ascend/models/layer/attention/layer.py').read_text()
        tree=ast.parse(text)
        table=next(ast.literal_eval(n.value) for n in ast.walk(tree) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='_DSV4_BLOCK_SIZES' for t in n.targets))
        for b, (sizes,padding) in table.items():
            p=resolve({'block_size':b})
            self.assertEqual(sizes,[b,b,b//16,b//4])
            self.assertEqual(padding,[130*b,1024*b])
            self.assertEqual(p['page_bytes_per_rank'],sum(padding)*22)

    def test_source_retention_masks(self):
        path=Path(__file__).resolve().parents[1]/'source/vllm/vllm/v1/core/single_type_kv_cache_manager.py'
        tree=ast.parse(path.read_text())
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='SlidingWindowManager')
        methods=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in ('reachable_block_mask','_contiguous_blocks_for_hit')]
        stub=ast.ClassDef(name='Reference',bases=[],keywords=[],body=methods,decorator_list=[])
        module=ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),stub],type_ignores=[])
        class Spec: pass
        scope={'SlidingWindowSpec':Spec,'cdiv':lambda a,b:(a+b-1)//b}
        exec(compile(ast.fix_missing_locations(module),str(path),'exec'),scope)
        reference=scope['Reference']
        for b in (32,64,128):
            p=resolve({'block_size':b})
            for g in p['groups']:
                if g['kind']!='window':continue
                spec=Spec();spec.block_size=g['block'];spec.sliding_window=g['window']
                count=p['alignment']//g['block']*2
                actual=reference.reachable_block_mask(0,count,p['alignment'],spec,False,p['retention'],())
                need=(g['window']-1+g['block']-1)//g['block']
                expected=[i%(p['alignment']//g['block'])>=p['alignment']//g['block']-need for i in range(count)]
                self.assertEqual(actual,expected)


if __name__=='__main__':unittest.main()
