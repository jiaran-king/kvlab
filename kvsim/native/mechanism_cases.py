"""Bounded native Scheduler mechanism cases, run in the pinned CPU environment."""

from __future__ import annotations

import json
import functools

from vllm.sampling_params import SamplingParams
from vllm.utils.hashing import get_hash_fn_by_name
from vllm.v1.core.kv_cache_utils import get_request_block_hasher, init_none_hash
from vllm.v1.core.sched.output import SchedulerOutput
from vllm.v1.core.sched.scheduler import Scheduler
from vllm.v1.outputs import KVConnectorOutput, ModelRunnerOutput
from vllm.v1.request import Request

from kvsim.native.probe_native import (
    CapturePublisher, NoGrammar, NoMultimodal, OfflineTransfer,
    make_cache_config, make_vllm_config,
)


def trial(blocks: int, inputs: dict[str, list[int]], sequential: bool,
          observe: bool = True, chunk_limit: int = 0,
          max_steps: int = 40, capture_admission: bool = False) -> dict:
    config = make_vllm_config(blocks)
    config.kv_events_config.enable_kv_cache_events = observe
    config.scheduler_config.long_prefill_token_threshold = chunk_limit
    scheduler = Scheduler(
        vllm_config=config,
        kv_cache_config=make_cache_config(blocks),
        structured_output_manager=NoGrammar(),
        block_size=256, hash_block_size=4,
        mm_registry=NoMultimodal(), log_stats=False,
    )
    publisher = CapturePublisher()
    scheduler.kv_event_publisher = publisher
    connector = OfflineTransfer()
    scheduler.connector = connector
    hash_fn = get_hash_fn_by_name("sha256")
    init_none_hash(hash_fn)
    hasher = get_request_block_hasher(4, hash_fn)
    submitted: set[str] = set()
    released: set[str] = set()
    adopted: dict[str, int] = {}
    waiting_steps = 0
    peak_running = 0
    preemptions: dict[str, int] = {}
    processing_tokens = {req_id: 0 for req_id in inputs}
    min_free = blocks
    empty = 0
    group_lookups: list[dict] = []
    timeline: list[dict] = []
    current_request = [None]
    current_step = [0]
    original_get = scheduler.kv_cache_manager.get_computed_blocks
    coordinator = scheduler.kv_cache_manager.coordinator
    original_estimate = coordinator.get_num_blocks_to_allocate
    admission_checks: list[dict] = []

    def observed_estimate(*args, **kwargs):
        required = original_estimate(*args, **kwargs)
        if kwargs.get("apply_admission_cap"):
            admission_checks.append({
                "step": current_step[0],
                "request_id": kwargs["request_id"],
                "full_sequence_tokens": kwargs["num_tokens"],
                "required_blocks": required,
                "free_blocks_before": scheduler.kv_cache_manager.block_pool.get_num_free_blocks(),
            })
        return required

    def observed_get(request):
        current_request[0] = request.request_id
        try:
            return original_get(request)
        finally:
            current_request[0] = None

    patched = []
    if observe:
        scheduler.kv_cache_manager.get_computed_blocks = observed_get
    if capture_admission:
        coordinator.get_num_blocks_to_allocate = observed_estimate
    for attention_group in (
        scheduler.kv_cache_manager.coordinator.attention_groups if observe else []
    ):
        cls = attention_group.manager_cls
        if any(previous is cls for previous, _ in patched):
            continue
        descriptor = cls.__dict__["find_longest_cache_hit"]
        original = descriptor.__func__

        def make_observer(fn):
            @functools.wraps(fn)
            def observed(klass, *args, **kwargs):
                result = fn(klass, *args, **kwargs)
                if current_request[0] is not None:
                    group_lookups.append({
                        "request_id": current_request[0],
                        "groups": list(kwargs["kv_cache_group_ids"]),
                        "candidate": kwargs["max_length"],
                        "returned": result[1],
                    })
                return result
            return observed

        cls.find_longest_cache_hit = classmethod(make_observer(original))
        patched.append((cls, descriptor))

    def check_pool():
        pool = scheduler.kv_cache_manager.block_pool
        usable = [block for block in pool.blocks if not block.is_null]
        free = sum(block.ref_cnt == 0 for block in usable)
        assert free == pool.get_num_free_blocks(), (
            "free queue/reference conservation", free,
            pool.get_num_free_blocks(), blocks,
        )
        assert all(block.ref_cnt >= 0 for block in usable)

    def submit(req_id: str, tokens: list[int]):
        scheduler.add_request(Request(
            request_id=req_id, prompt_token_ids=tokens,
            sampling_params=SamplingParams(max_tokens=1, ignore_eos=True),
            pooling_params=None, block_hasher=hasher,
        ))
        submitted.add(req_id)

    try:
        if not sequential:
            for req_id, tokens in inputs.items():
                submit(req_id, tokens)
        for step in range(1, max_steps + 1):
            current_step[0] = step
            pending = set(connector.pending)
            if pending:
                scheduler.update_from_output(
                    SchedulerOutput.make_empty(),
                    ModelRunnerOutput.with_kv_conn_output_only(
                        KVConnectorOutput(finished_sending=pending)
                    ),
                )
                released.update(pending)
            if sequential:
                for req_id, tokens in inputs.items():
                    if req_id not in submitted and len(released) == len(submitted):
                        submit(req_id, tokens)
                        break
            if len(released) == len(inputs):
                break
            before = {
                "step": step,
                "running_before": [req.request_id for req in scheduler.running],
                "waiting_before": len(scheduler.waiting),
                "free_blocks_before": scheduler.kv_cache_manager.block_pool.get_num_free_blocks(),
            }
            waiting_steps += bool(scheduler.waiting)
            scheduled = scheduler.schedule()
            for req_id, count in scheduled.num_scheduled_tokens.items():
                processing_tokens[req_id] += count
            peak_running = max(peak_running, len(scheduler.running))
            min_free = min(min_free, scheduler.kv_cache_manager.block_pool.get_num_free_blocks())
            for item in scheduled.scheduled_new_reqs:
                adopted[item.req_id] = item.num_computed_tokens
            ids = list(scheduled.num_scheduled_tokens)
            generated = [
                [101] if scheduler.requests[req_id].num_computed_tokens >=
                scheduler.requests[req_id].num_prompt_tokens else []
                for req_id in ids
            ]
            scheduler.update_from_output(scheduled, ModelRunnerOutput(
                req_ids=ids,
                req_id_to_index={req_id: index for index, req_id in enumerate(ids)},
                sampled_token_ids=generated,
            ))
            check_pool()
            for req_id in submitted:
                if req_id in scheduler.requests:
                    preemptions[req_id] = scheduler.requests[req_id].num_preemptions
            timeline.append({
                **before,
                "scheduled": dict(scheduled.num_scheduled_tokens),
                "preempted_req_ids": sorted(scheduled.preempted_req_ids),
                "resumed_req_ids": sorted(scheduled.scheduled_cached_reqs.resumed_req_ids),
                "running_after": [req.request_id for req in scheduler.running],
                "waiting_after": len(scheduler.waiting),
                "free_blocks_after": scheduler.kv_cache_manager.block_pool.get_num_free_blocks(),
                "preemptions": dict(preemptions),
                "pending_transfer": sorted(connector.pending),
            })
            empty = 0 if ids or pending else empty + 1
            if empty > 2:
                break
        return {
            "physical_blocks": blocks,
            "sequential": sequential,
            "observed": observe,
            "submitted": sorted(submitted),
            "released": sorted(released),
            "adopted_tokens": adopted,
            "waiting_steps": waiting_steps,
            "peak_running": peak_running,
            "preemptions": preemptions,
            "processing_tokens": processing_tokens,
            "chunk_limit": chunk_limit,
            "admission_checks": admission_checks,
            "min_free_blocks": min_free,
            "event_types": {
                name: sum(type(event).__name__ == name for event in publisher.events)
                for name in {type(event).__name__ for event in publisher.events}
            },
            "group_lookups": group_lookups,
            "timeline": timeline,
            "all_references_released": all(
                block.ref_cnt == 0
                for block in scheduler.kv_cache_manager.block_pool.blocks
                if not block.is_null
            ),
        }
    finally:
        if capture_admission:
            coordinator.get_num_blocks_to_allocate = original_estimate
        for cls, descriptor in patched:
            cls.find_longest_cache_hit = descriptor
        scheduler.shutdown()


def main():
    shared = [11] * 9216
    identity = trial(12393, {"A": shared, "B": shared, "C": [12] * 9216}, True)
    assert identity["released"] == ["A", "B", "C"], identity
    assert identity["adopted_tokens"]["B"] > 0, identity
    assert identity["adopted_tokens"]["C"] == 0, identity
    assert identity["event_types"].get("BlockStored", 0) > 0, identity
    b_calls = [call for call in identity["group_lookups"]
               if call["request_id"] == "B"]
    assert [call["groups"] for call in b_calls[:4]] == [
        [0], [1, 2], [3], [4]
    ], b_calls
    assert [call["groups"] for call in b_calls[4:]] == [
        [1, 2], [3], [4]
    ], b_calls
    assert all(call["returned"] == 8960 for call in b_calls), b_calls
    assert b_calls[-1]["returned"] == identity["adopted_tokens"]["B"], b_calls
    assert identity["all_references_released"], identity
    unobserved = trial(12393, {"A": shared, "B": shared,
                               "C": [12] * 9216}, True, observe=False)
    for key in ("submitted", "released", "adopted_tokens", "waiting_steps",
                "peak_running", "preemptions", "min_free_blocks",
                "all_references_released"):
        assert identity[key] == unobserved[key], (key, identity[key], unobserved[key])
    retention = trial(3600, {"A": shared, "B": shared, "C": [12] * 9216}, True)
    assert retention["released"] == ["A", "B", "C"], retention
    assert retention["adopted_tokens"]["B"] > 0, retention
    assert retention["event_types"].get("BlockRemoved", 0) > 0, retention
    assert retention["all_references_released"], retention
    pressure = [trial(blocks, {"A": [11] * 10000, "B": [12] * 10000}, False)
                for blocks in (3600, 5000, 7000)]
    assert pressure[0]["peak_running"] == 2
    assert pressure[0]["event_types"].get("BlockRemoved", 0) > 0
    assert all(case["all_references_released"] for case in pressure)
    preemption_probe = trial(3600, {"A": [11] * 30000,
                                    "B": [12] * 30000}, False)
    print(json.dumps({"identity": identity, "unobserved": unobserved,
                      "retention": retention,
                      "pressure": pressure,
                      "preemption_probe": preemption_probe}, indent=2))


if __name__ == "__main__":
    main()
