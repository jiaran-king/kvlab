"""Target-source probes; no model imports or tensors.
The coordinator test substitutes group probes to isolate its fixed-point rule.
"""
import unittest
from types import SimpleNamespace as NS
from collections import namedtuple
from kvsim.tests.test_source_pool import source_class,ROOT,Block
from kvsim.profile import resolve
from kvsim.engine import Pool

MANAGER=ROOT/'source/vllm/vllm/v1/core/single_type_kv_cache_manager.py'
CDIV=lambda a,b:(a+b-1)//b

class LifecycleSourceTests(unittest.TestCase):
    def test_duplicate_hash_index(self):
        cls=source_class(ROOT/'source/vllm/vllm/v1/core/block_pool.py','BlockHashToBlockMap')
        ref=cls();pool=Pool(3);a=pool.allocate(0);b=pool.allocate(0)
        for page in (a,b):ref.insert('key',Block(page.id));pool.publish(page,'key',0)
        self.assertEqual(ref.get_one_block('key').block_id,pool.lookup('key').id)
        pool.release(a,1);pool.allocate(2);ref.pop('key',a.id)
        self.assertEqual(ref.get_one_block('key').block_id,pool.lookup('key').id)
        self.assertEqual(b.refs,1)

    def test_window_release_uses_committed_position_and_batch_order(self):
        base=source_class(MANAGER,'SingleTypeKVCacheManager',{'remove_skipped_blocks','_remove_blocks_in_range'})
        window=source_class(MANAGER,'SlidingWindowManager',{'get_num_skipped_tokens'})
        for block,window_size in [(128,128),(8,8),(32,128)]:
            ref=base();ref.block_size=block;ref.sliding_window=window_size;ref.get_num_skipped_tokens=window.get_num_skipped_tokens.__get__(ref)
            ref._null_block=object();pages=[object() for _ in range(1200)];ref.req_to_blocks={'r':pages.copy()};batches=[]
            ref.block_pool=NS(free_blocks=lambda bs:batches.append(list(bs)))
            for position in (0,8192,16384,24576):
                before=ref.req_to_blocks['r'].copy();ref.remove_skipped_blocks('r',position)
                cutoff=max(0,position-window_size+1)//block
                expected=[before[i] for i in reversed(range(min(cutoff,len(before)))) if before[i] is not ref._null_block]
                if expected:self.assertEqual(batches[-1],expected)
                self.assertEqual(sum(x is ref._null_block for x in ref.req_to_blocks['r']),min(cutoff,len(before)))

    def test_admission_cap_differs_from_allocation(self):
        spec=source_class(ROOT/'source/vllm/vllm/v1/kv_cache_interface.py','SlidingWindowSpec',{'max_admission_blocks_per_request'}, {'cdiv':CDIV})
        manager=source_class(MANAGER,'SingleTypeKVCacheManager',{'get_num_blocks_to_allocate','_get_num_evictable_blocks'}, {'cdiv':CDIV})
        for b in (32,64,128):
            for g in resolve({'block_size':b})['groups']:
                if g['kind']!='window':continue
                cap=spec.max_admission_blocks_per_request(NS(sliding_window=g['window'],block_size=g['block']),8192,100000)
                expected=CDIV(min(g['window']-1+8192,100000),g['block'])+1
                self.assertEqual(cap,expected)
                m=manager();m.block_size=g['block'];m.req_to_blocks={};m.num_cached_block={};m._max_admission_blocks_per_request=cap
                m.get_num_skipped_tokens=lambda n:max(0,n-g['window']+1);m._has_partial_local_hit=lambda *_:False
                args=('r',100000,[],0,0,100000)
                self.assertEqual(m.get_num_blocks_to_allocate(*args,apply_admission_cap=True),cap)
                self.assertEqual(m.get_num_blocks_to_allocate(*args,apply_admission_cap=False),CDIV(100000,g['block']))

    def test_source_coordinator_rechecks_sparse_groups(self):
        class Full:pass
        class Mamba:pass
        path=ROOT/'source/ascend/vllm_ascend/patch/platform/patch_kv_cache_coordinator.py'
        cls=source_class(path,'AscendHybridKVCacheCoordinator',{'find_longest_cache_hit'},{'FullAttentionSpec':Full,'MambaSpec':Mamba,'cdiv':CDIV})
        class Probe:
            supports_fine_grained_hash_lookup=False
            @classmethod
            def find_longest_cache_hit(cls,**kw):
                limit=kw['max_length'];choices=kw['kv_cache_spec'].choices
                hit=max([0]+[x for x in choices if x<=limit]);return (([None]*(hit//4096),),hit)
        Group=namedtuple('Group','spec group_ids manager_cls use_eagle')
        c=cls();c.attention_groups=[Group(NS(choices=[4096,12288]),[0],Probe,False),Group(NS(choices=[4096,8192]),[1],Probe,False),Group(NS(choices=[4096,8192,12288]),[2],Probe,False)]
        c.kv_cache_config=NS(kv_cache_groups=[0,1,2]);c._get_effective_block_size=lambda _:4096;c.block_pool=None;c._cache_hit_alignment_tokens=4096;c.dcp_world_size=1;c.enable_partial_hash_hits=False
        blocks,hit,_=c.find_longest_cache_hit([],12288)
        self.assertEqual(hit,4096)  # min(max(A), max(B)) would incorrectly give 8192.
