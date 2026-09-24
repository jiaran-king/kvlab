"""CPU-only native-vLLM scheduler smoke with H20's five cache groups.

This is a mechanism probe, not a historical replay. No model or GPU is used.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace as NS

import torch
from vllm.distributed.kv_transfer.kv_connector.v1.base import SupportsHMA
from vllm.sampling_params import SamplingParams
from vllm.utils.hashing import get_hash_fn_by_name
from vllm.v1.core.kv_cache_utils import get_request_block_hasher, init_none_hash
from vllm.v1.core.sched.scheduler import Scheduler
from vllm.v1.kv_cache_interface import (
    KVCacheConfig,
    KVCacheGroupSpec,
    KVCacheTensor,
    KVQuantMode,
    MLAAttentionSpec,
    SlidingWindowMLASpec,
)
from vllm.v1.outputs import KVConnectorOutput, ModelRunnerOutput
from vllm.v1.request import Request


class NoMultimodal:
    def supports_multimodal_inputs(self, _):
        return False


class NoGrammar:
    def should_advance(self, _):
        return False


class CapturePublisher:
    def __init__(self):
        self.events = []

    def publish(self, batch):
        self.events.extend(batch.events)

    def shutdown(self):
        pass


class OfflineTransfer(SupportsHMA):
    """Only the worker transfer completion signal is simulated.

    Native Scheduler still owns cache allocation, prefix lookup, references,
    release, and any preemption. This adapter delays a finished P request's
    reference release until a later finished_sending notification.
    """

    def __init__(self):
        self.pending = set()

    def bind_gpu_block_pool(self, _):
        pass

    def on_new_request(self, _):
        pass

    def get_num_new_matched_tokens(self, request, num_local):
        return 0, False

    def update_state_after_alloc(self, request, blocks, num_external):
        pass

    def build_connector_meta(self, output):
        return None

    def request_finished_all_groups(self, request, block_ids):
        self.pending.add(request.request_id)
        return True, {"offline_transfer_pending": True}

    def update_connector_output(self, output):
        self.pending.difference_update(output.finished_sending or ())

    def get_kv_connector_stats(self):
        return None

    def take_events(self):
        return None

    def has_pending_push_work(self):
        return bool(self.pending)

    def shutdown(self):
        pass


def make_cache_config(num_blocks=12393):
    layout = json.loads((Path(__file__).with_name("h20-layout.json")).read_text())
    if layout["schema"] != "kvlab-native-h20-layout/v1":
        raise ValueError("unsupported H20 cache layout")
    if layout["reference_num_blocks"] != 12393:
        raise ValueError("unexpected historical reference block count")
    dtypes = {"torch.uint8": torch.uint8, "torch.float32": torch.float32}
    groups = []
    for index, entry in enumerate(layout["kv_cache_groups"]):
        fields = dict(entry["kv_cache_spec"])
        fields["dtype"] = dtypes[fields["dtype"]]
        fields["kv_quant_mode"] = KVQuantMode(fields["kv_quant_mode"])
        spec_cls = MLAAttentionSpec if index == 0 else SlidingWindowMLASpec
        spec = spec_cls(**fields)
        # __post_init__ can recompute local alignment padding, whereas the
        # captured effective hybrid layout uses the shared packed-page size.
        captured_page_size = entry["kv_cache_spec"]["page_size_padded"]
        if spec.page_size_bytes != captured_page_size:
            if captured_page_size < spec.unpadded_page_size_bytes:
                raise ValueError(f"invalid captured page size in group {index}")
            object.__setattr__(spec, "page_size_padded", captured_page_size)
        if spec.block_size != entry["kv_cache_spec"]["block_size"] or \
           spec.page_size_bytes != captured_page_size:
            raise ValueError(f"historical cache spec drift in group {index}")
        groups.append(KVCacheGroupSpec(
            layer_names=entry["layer_names"], kv_cache_spec=spec,
            is_eagle_group=entry["is_eagle_group"],
        ))
    tensors = []
    for entry in layout["kv_cache_tensors"]:
        if entry["size"] != layout["reference_num_blocks"] * entry["block_stride"]:
            raise ValueError("historical KV tensor stride mismatch")
        tensors.append(KVCacheTensor(
            size=num_blocks * entry["block_stride"],
            shared_by=entry["shared_by"],
            offset=entry["offset"], block_stride=entry["block_stride"],
        ))
    return KVCacheConfig(num_blocks=num_blocks, kv_cache_tensors=tensors,
                         kv_cache_groups=groups)


def make_vllm_config(num_blocks=12393, reserve_full_isl=True,
                     max_num_seqs=2, max_num_batched_tokens=8192):
    return NS(
        scheduler_config=NS(
            max_num_seqs=max_num_seqs, max_num_batched_tokens=max_num_batched_tokens,
            max_num_scheduled_tokens=None, policy="fcfs", watermark=0.0,
            scheduler_reserve_full_isl=reserve_full_isl, enable_chunked_prefill=True,
            long_prefill_token_threshold=0,
        ),
        cache_config=NS(
            num_gpu_blocks=num_blocks, enable_prefix_caching=True,
            block_size=4, mamba_cache_mode="none",
            prefix_caching_hash_algo="sha256",
        ),
        model_config=NS(
            is_encoder_decoder=False, is_diffusion=False,
            max_model_len=81920, enable_return_routed_experts=False,
        ),
        parallel_config=NS(
            data_parallel_index=0, pipeline_parallel_size=1,
            decode_context_parallel_size=1, prefill_context_parallel_size=1,
        ),
        observability_config=NS(
            kv_cache_metrics=False, kv_cache_metrics_sample=0,
            enable_mfu_metrics=False, enable_logging_iteration_details=False,
        ),
        kv_events_config=NS(enable_kv_cache_events=True, publisher="null"),
        kv_transfer_config=None, ec_transfer_config=None,
        lora_config=None, speculative_config=None,
        num_speculative_tokens=0, max_in_flight_tokens=0,
        max_concurrent_batches=1, use_v2_model_runner=False,
    )


def run():
    cache = make_cache_config()
    config = make_vllm_config()
    scheduler = Scheduler(
        vllm_config=config, kv_cache_config=cache,
        structured_output_manager=NoGrammar(), block_size=256,
        hash_block_size=4, mm_registry=NoMultimodal(), log_stats=False,
    )
    publisher = CapturePublisher()
    scheduler.kv_event_publisher = publisher
    connector = OfflineTransfer()
    scheduler.connector = connector
    hash_fn = get_hash_fn_by_name("sha256")
    init_none_hash(hash_fn)
    hasher = get_request_block_hasher(4, hash_fn)
    inputs = {"A": [11] * 8500, "B": [22] * 20000}
    for request_id, tokens in inputs.items():
        scheduler.add_request(Request(
            request_id=request_id, prompt_token_ids=tokens,
            sampling_params=SamplingParams(max_tokens=2, ignore_eos=True),
            pooling_params=None, block_hasher=hasher,
        ))

    steps = []
    released = set()
    for step in range(1, 12):
        scheduled = scheduler.schedule()
        req_ids = list(scheduled.num_scheduled_tokens)
        generated = []
        for req_id in req_ids:
            request = scheduler.requests[req_id]
            generated.append(
                [100 + len(request.output_token_ids)]
                if request.num_computed_tokens >= request.num_prompt_tokens else []
            )
        # Each transfer completes at the next logical scheduler step.
        completed_transfer = set(connector.pending)
        output = ModelRunnerOutput(
            req_ids=req_ids,
            req_id_to_index={req_id: i for i, req_id in enumerate(req_ids)},
            sampled_token_ids=generated,
            kv_connector_output=(
                KVConnectorOutput(finished_sending=completed_transfer)
                if completed_transfer else None
            ),
        )
        scheduler.update_from_output(scheduled, output)
        released.update(completed_transfer)
        steps.append({
            "step": step,
            "scheduled": scheduled.num_scheduled_tokens,
            "running_after": [request.request_id for request in scheduler.running],
            "pending_transfer": sorted(connector.pending),
            "transfer_complete": sorted(completed_transfer),
            "events_total": len(publisher.events),
        })
        if not scheduler.has_requests() and not connector.pending:
            break
    result = {
        "mode": "native-vllm-cpu-mechanism-probe",
        "historical_exactness": "not claimed: synthetic tokens and offline transfer adapter; cache layout is reconstructed from recorded effective config",
        "cache_groups": [
            {"block_size": g.kv_cache_spec.block_size,
             "window": getattr(g.kv_cache_spec, "sliding_window", None)}
            for g in cache.kv_cache_groups
        ],
        "steps": steps,
        "event_types": [type(event).__name__ for event in publisher.events[:20]],
        "event_count": len(publisher.events),
        "unfinished_requests": scheduler.get_num_unfinished_requests(),
    }
    print(json.dumps(result, ensure_ascii=False))
    scheduler.shutdown()
    assert any(set(s["running_after"]) == {"A", "B"} for s in steps)
    assert released == {"A", "B"} and result["event_count"] > 0
    assert result["unfinished_requests"] == 0


if __name__ == "__main__":
    run()
