"""Run unmodified frozen queue/free/allocate/touch methods without vLLM imports.
Only the storage object and cache-eviction callback are substitutes; this test
proves queue and reference semantics, not the complete upstream hash index.
"""
import ast
import json
import random
import subprocess
import unittest
from pathlib import Path
from kvsim.engine import Pool

ROOT = Path(__file__).resolve().parents[1]

class Block:
    def __init__(self, block_id):
        self.block_id = block_id
        self.ref_cnt = 0
        self.block_hash = None
        self.is_null = False
        self.prev_free_block = self.next_free_block = None


def source_class(path, name, methods=None, env=None):
    tree = ast.parse(path.read_text())
    node = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == name)
    if methods is not None:
        node.bases = []
        node.decorator_list = []
        node.body = [x for x in node.body if isinstance(x, ast.FunctionDef) and x.name in methods]
    module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), node], type_ignores=[])
    ns = {'KVCacheBlock': Block, **(env or {})}
    exec(compile(ast.fix_missing_locations(module), str(path), 'exec'), ns)
    return ns[name]


def oracle(total):
    queue = source_class(ROOT/'source/vllm/vllm/v1/core/kv_cache_utils.py', 'FreeKVCacheBlockQueue')
    cls = source_class(ROOT/'source/vllm/vllm/v1/core/block_pool.py', 'BlockPool', {'get_new_blocks','free_blocks','touch','get_num_free_blocks'})
    obj = cls()
    obj.blocks = [Block(i) for i in range(total)]
    obj.free_block_queue = queue(obj.blocks)
    obj.free_block_queue.popleft().is_null = True
    obj.enable_caching = True
    obj.metrics_collector = None
    obj._maybe_evict_cached_block = lambda b: setattr(b, 'block_hash', None)
    return obj


class SourcePoolTests(unittest.TestCase):
    def test_batch_release_matches_frozen_queue(self):
        p=Pool(8);o=oracle(8)
        pages=[p.allocate(0) for _ in range(4)];blocks=o.get_new_blocks(4)
        p.publish(pages[0], 'cached', 0);blocks[0].block_hash='cached'
        # Batch order 4,1,3 => empty 4,3 precede unused 5..7; cached 1 last.
        p.release_many([pages[i] for i in (3,0,2)],1);o.free_blocks([blocks[i] for i in (3,0,2)])
        self.assertEqual([p.allocate(2).id for _ in range(5)],[b.block_id for b in o.get_new_blocks(5)])
        self.assertIsNotNone(p.lookup('cached'))
        self.assertEqual(p.replacements,0)
        self.assertEqual(p.allocate(3).id,o.get_new_blocks(1)[0].block_id)
        self.assertEqual(p.replacements,1)

    def test_seeded_operations_match_source_and_javascript(self):
        rng=random.Random(43);p=Pool(17);o=oracle(17);ops=[];expected=[]
        for seq in range(400):
            live=[x for x in p.pages.values() if x.refs]
            action=rng.choice(['allocate','release','touch','publish'])
            if action=='allocate' and p.available():
                n=min(p.available(),rng.randint(1,4));ids=[p.allocate(seq).id for _ in range(n)]
                self.assertEqual(ids,[b.block_id for b in o.get_new_blocks(n)])
                ops.append(['allocate',n,seq])
            elif action=='release' and live:
                chosen=rng.sample(live,min(len(live),rng.randint(1,4)))
                p.release_many(chosen,seq);o.free_blocks([o.blocks[x.id] for x in chosen]);ops.append(['release',[x.id for x in chosen],seq])
            elif action=='touch' and p.pages:
                x=rng.choice(list(p.pages.values()));p.touch(x);o.touch([o.blocks[x.id]]);ops.append(['touch',x.id,seq])
            elif action=='publish' and live:
                x=rng.choice(live);key='hash-'+str(seq%5)
                p.publish(x,key,seq)
                if o.blocks[x.id].block_hash is None:o.blocks[x.id].block_hash=key
                ops.append(['publish',x.id,seq,key])
            else:continue
            self.assertEqual(p.available(),o.get_num_free_blocks())
            for x in p.pages.values():
                self.assertEqual((x.refs,x.key),(o.blocks[x.id].ref_cnt,o.blocks[x.id].block_hash))
            expected.append({'available':p.available(),'pages':[[x.id,x.refs,x.key] for x in p.pages.values()]})
        script="""const K=require('./kvsim/browser/core.js'),fs=require('fs'),p=new K.Pool(17);const out=[];for(const [op,x,seq,key] of JSON.parse(fs.readFileSync(0,'utf8'))){if(op==='allocate')for(let i=0;i<x;i++)p.allocate(seq);if(op==='release')p.releaseMany(x.map(id=>p.pages.get(id)),seq);if(op==='touch')p.touch(p.pages.get(x));if(op==='publish')p.publish(p.pages.get(x),key,seq);out.push({available:p.available(),pages:[...p.pages.values()].map(x=>[x.id,x.refs,x.key])})}process.stdout.write(JSON.stringify(out));"""
        actual=json.loads(subprocess.check_output(['node','-e',script],input=json.dumps(ops).encode(),cwd=ROOT.parent))
        self.assertEqual(actual,expected)
