"""Offline native Ascend P-cache replay for one v3.1 rank, without a model.

Each P is an independent cache domain. The final route audit shows one request
at a time per P, with the previous P request finished before the next is
admitted. This runner consumes that P's captured order and frees its producer
reference after a simulated transfer-complete notification.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from collections import Counter, deque
from pathlib import Path

from vllm.sampling_params import SamplingParams
from vllm.utils.hashing import get_hash_fn_by_name
from vllm.v1.core.kv_cache_utils import get_request_block_hasher, init_none_hash
from vllm.v1.core.sched.output import SchedulerOutput
from vllm.v1.core.sched.async_scheduler import AsyncScheduler
from vllm.v1.outputs import KVConnectorOutput, ModelRunnerOutput
from vllm.v1.request import Request

# The exact vllm-ascend target commit installs its coordinator patch on import.
import vllm_ascend.patch.platform.patch_kv_cache_coordinator  # noqa: F401

from kvsim.native.accounting import scheduled_input_interval
from kvsim.native.ascend_layout import captured_layout, blocks_for_budget_gib, make_native_cache_config
from kvsim.native.probe_native import NoGrammar, NoMultimodal, OfflineTransfer, make_vllm_config



class AscendOfflineProducer(OfflineTransfer):
    """Mirror the target Mooncake P request truncation before local compute.

    The native Scheduler queries the full prompt (including terminal 128822)
    first. Mooncake then removes that token, sets max_tokens=1 and lets P
    prefill N-1 tokens. Cache lookup, block hashing and allocation remain native.
    """

    def __init__(self):
        super().__init__()
        self.finished_block_lens = {}

    def request_finished_all_groups(self, request, block_ids):
        self.finished_block_lens[request.request_id] = [len(group) for group in block_ids]
        return super().request_finished_all_groups(request, block_ids)

    def get_num_new_matched_tokens(self, request, num_local):
        params = request.kv_transfer_params
        if (params is not None and params.get('do_remote_decode')
                and not params.get('_p_side_truncated')
                and request.num_prompt_tokens > 1):
            if request.prompt_token_ids is None or request.prompt_token_ids[-1] != 128822:
                raise ValueError('P producer request lacks verified terminal 128822')
            request.prompt_token_ids.pop()
            request._all_token_ids.pop()
            request.num_prompt_tokens -= 1
            request.max_tokens = 1
            params['_p_side_truncated'] = True
        return 0, False


def _collect_stats(outputs, totals):
    for value in outputs.values():
        if value.scheduler_stats is None:
            continue
        prefix = value.scheduler_stats.prefix_cache_stats
        totals['prefix_queries'] += prefix.queries
        totals['prefix_hits'] += prefix.hits
        totals['preempted_queries'] += prefix.preempted_queries
        totals['preempted_hits'] += prefix.preempted_hits


def replay(requests_path: Path, budget_gib: int, rank: int, output_path: Path,
           limit: int | None = None) -> dict:
    layout = captured_layout()
    blocks = blocks_for_budget_gib(budget_gib)
    cache = make_native_cache_config(blocks)
    config = make_vllm_config(blocks, reserve_full_isl=True,
                              max_num_seqs=2, max_num_batched_tokens=8192)
    # Real P CLI --block-size 32 remains CacheConfig.block_size; hash block is 2.
    config.cache_config.block_size = layout['scheduler_block_size']
    # Captured P log enables async scheduling on every engine.
    config.scheduler_config.async_scheduling = True
    # Target VllmConfig.max_in_flight_tokens = max_concurrent_batches * MBT.
    # The H20 SimpleNamespace helper pins 0; target PP=1 async has two batches.
    config.max_in_flight_tokens = config.max_concurrent_batches * config.scheduler_config.max_num_batched_tokens
    scheduler = AsyncScheduler(vllm_config=config, kv_cache_config=cache,
                          structured_output_manager=NoGrammar(),
                          block_size=layout['scheduler_block_size'],
                          hash_block_size=layout['hash_block_size'],
                          mm_registry=NoMultimodal(), log_stats=True)
    coordinator = scheduler.kv_cache_manager.coordinator
    actual = {
        'coordinator': type(coordinator).__name__,
        'num_blocks': len(scheduler.kv_cache_manager.block_pool.blocks),
        'scheduler_block_size': coordinator.scheduler_block_size,
        'hash_block_size': coordinator.hash_block_size,
        'lcm_block_size': coordinator.lcm_block_size,
        'hit_alignment': coordinator._cache_hit_alignment_tokens,
        'retention_interval': coordinator.retention_interval,
        'groups': len(coordinator.single_type_managers),
    }
    expected = {
        'coordinator': 'AscendHybridKVCacheCoordinator',
        'num_blocks': blocks,
        'scheduler_block_size': 32,
        'hash_block_size': 2,
        'lcm_block_size': 4096,
        'hit_alignment': 32,
        'retention_interval': 4096,
        'groups': 6,
    }
    if actual != expected:
        scheduler.shutdown()
        raise ValueError(f'constructed native layout differs: {actual} != {expected}')
    transfer = AscendOfflineProducer()
    scheduler.connector = transfer
    fn = get_hash_fn_by_name('sha256')
    init_none_hash(fn)
    hasher = get_request_block_hasher(2, fn)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    seen = set()
    aggregate = Counter()
    count = 0
    try:
        with gzip.open(requests_path, 'rt') as source, output_path.open('w') as output:
            for line in source:
                if limit is not None and count >= limit:
                    break
                row = json.loads(line)
                rid = row['runtime_request_id']
                if rid in seen or len(row['tokens']) != row['input_tokens']:
                    raise ValueError(f'invalid or duplicate request {rid}')
                seen.add(rid)
                tokens = row['tokens']
                full_tokens = tokens + [128822]
                native = Request(request_id=rid, prompt_token_ids=full_tokens,
                                 sampling_params=SamplingParams(max_tokens=row['output_tokens'],
                                     ignore_eos=True, extra_args={'kv_transfer_params':
                                         {'do_remote_decode': True}}),
                                 pooling_params=None, block_hasher=hasher)
                scheduler.add_request(native)
                totals = Counter()
                intervals = []
                adopted = None
                steps = 0
                min_free_blocks = blocks - 1
                queue = deque()
                while steps < 100:
                    # The captured EngineCore.step_with_batch_queue fills its
                    # two-entry async queue before taking the oldest result.
                    while len(queue) < 2 and scheduler.has_requests() and rid not in transfer.pending:
                        steps += 1
                        scheduled = scheduler.schedule()
                        min_free_blocks = min(min_free_blocks, scheduler.kv_cache_manager.block_pool.get_num_free_blocks())
                        ids = list(scheduled.num_scheduled_tokens)
                        if native.num_prompt_tokens != len(tokens):
                            raise RuntimeError(f'{rid} was not P-truncated by the producer')
                        if rid in ids:
                            start, end = scheduled_input_interval(
                                scheduler.requests[rid].num_computed_tokens,
                                scheduled.num_scheduled_tokens[rid], len(tokens))
                            if adopted is None:
                                adopted = start
                            if end > start:
                                intervals.append((start, end))
                        generated = [
                            [128822] if scheduler.requests[x].num_computed_tokens >=
                            scheduler.requests[x].num_prompt_tokens else []
                            for x in ids
                        ]
                        queue.append((scheduled, ids, generated))
                        if scheduled.total_num_scheduled_tokens == 0:
                            break
                    if not queue:
                        raise RuntimeError(f'{rid} has no scheduled output')
                    scheduled, ids, generated = queue.popleft()
                    updates = scheduler.update_from_output(scheduled, ModelRunnerOutput(
                        req_ids=ids,
                        req_id_to_index={x: i for i, x in enumerate(ids)},
                        sampled_token_ids=generated,
                    ))
                    _collect_stats(updates, totals)
                    min_free_blocks = min(min_free_blocks, scheduler.kv_cache_manager.block_pool.get_num_free_blocks())
                    if rid in transfer.pending and not queue:
                        updates = scheduler.update_from_output(
                            SchedulerOutput.make_empty(),
                            ModelRunnerOutput.with_kv_conn_output_only(
                                KVConnectorOutput(finished_sending={rid})))
                        _collect_stats(updates, totals)
                        break
                    if not scheduler.has_requests() and not queue:
                        raise RuntimeError(f'{rid} finished without producer transfer')
                else:
                    raise RuntimeError(f'{rid} did not prefill/transfer in 100 logical steps')
                if rid in transfer.pending or native.num_preemptions:
                    raise RuntimeError(f'{rid} has pending transfer or preemption')
                if adopted is None:
                    raise RuntimeError(f'{rid} never scheduled')
                processed = sum(end - start for start, end in intervals)
                if adopted + processed != len(tokens):
                    raise RuntimeError(f'{rid} input accounting differs: {adopted}+{processed}!={len(tokens)}')
                pool = scheduler.kv_cache_manager.block_pool
                resident_hashed_blocks = sum(
                    block.ref_cnt == 0 and not block.is_null and
                    (block.block_hash is not None or
                     block.block_id in pool.cached_block_hashes_by_block)
                    for block in pool.blocks
                )
                record = {
                    'request_id': rid, 'p_domain': f'p{rank}',
                    'resident_hashed_blocks_after_release': resident_hashed_blocks,
                    'peak_active_blocks': blocks - min_free_blocks - 1,
                    'free_blocks_after_release': pool.get_num_free_blocks(),
                    'input_tokens': len(tokens),
                    'engine_input_sha256': hashlib.sha256(json.dumps(tokens, separators=(',', ':')).encode()).hexdigest(),
                    'initial_adopted_cache_tokens': adopted,
                    'cumulative_input_processing_tokens': processed,
                    'prefix_queries': totals['prefix_queries'],
                    'prefix_hits': totals['prefix_hits'],
                    'preemptions': native.num_preemptions,
                    'steps': steps,
                    'finished_block_lens': transfer.finished_block_lens.pop(rid),
                }
                output.write(json.dumps(record, separators=(',', ':')) + '\n')
                aggregate.update({'input_tokens': len(tokens),
                                  'initial_adopted_cache_tokens': adopted,
                                  'cumulative_input_processing_tokens': processed,
                                  'prefix_queries': totals['prefix_queries'],
                                  'prefix_hits': totals['prefix_hits'],
                                  'requests': 1})
                count += 1
    finally:
        scheduler.shutdown()
    return {'rank': rank, 'budget_gib': budget_gib, 'status': 'complete',
            'requests_completed': count, 'limit': limit, 'native_profile': actual,
            'totals': dict(aggregate)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--requests', type=Path, required=True)
    parser.add_argument('--budget-gib', type=int, required=True)
    parser.add_argument('--rank', type=int, choices=range(4), required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--limit', type=int)
    args = parser.parse_args()
    print(json.dumps(replay(args.requests, args.budget_gib, args.rank,
                            args.output, args.limit), ensure_ascii=False))

if __name__ == '__main__':
    main()
