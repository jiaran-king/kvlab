"""Offline H20-profile capacity scan using the installed native vLLM Scheduler.

Run inside the pinned vLLM 0.26.0 CPU environment, without model execution.
The external lifecycle is deterministic logical steps, not wall-clock time.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import inspect
import json
import os
from collections import Counter
from pathlib import Path

import msgspec
from vllm.sampling_params import SamplingParams
from vllm.utils.hashing import get_hash_fn_by_name
from vllm.v1.core.kv_cache_utils import get_request_block_hasher, init_none_hash
from vllm.v1.core.sched.output import SchedulerOutput
from vllm.v1.core.sched.scheduler import Scheduler
from vllm.v1.core.kv_cache_manager import KVCacheManager
from vllm.v1.core.kv_cache_coordinator import HybridKVCacheCoordinator
from vllm.v1.core.single_type_kv_cache_manager import FullAttentionManager
from vllm.v1.core.block_pool import BlockPool
from vllm.v1.kv_cache_interface import KVCacheConfig
from vllm.v1.outputs import KVConnectorOutput, ModelRunnerOutput
from vllm.v1.request import Request

from kvsim.native.inputs import (
    load_replay_workload, validate_h20_workload,
)
from kvsim.native.capacity import budgets_from_conditions, point_directory, target_layout
from kvsim.native.conditions import read_conditions
from kvsim.native.routing import load_routing
from kvsim.native.identity import run_id
from kvsim.native.scenario import validate_scenario
from kvsim.native.activity import activity_by_p
from kvsim.native.accounting import scheduled_input_interval, completed_input_totals
from kvsim.native.result_validation import load_jsonl, round_observation
from kvsim.native.probe_native import (
    NoGrammar, NoMultimodal, OfflineTransfer, make_cache_config,
    make_vllm_config,
)


class ExecutionIncomplete(RuntimeError):
    """The bounded logical driver could not finish this capacity point."""


def effective_native_profile(scheduler: Scheduler, conditions: dict) -> dict:
    """Read the constructed native core, including environment-derived policy."""
    coordinator = scheduler.kv_cache_manager.coordinator
    actual = {
        "retention_interval": coordinator.retention_interval,
        "scheduler_block_size": coordinator.scheduler_block_size,
        "hash_block_size": coordinator.hash_block_size,
        "max_model_len": scheduler.max_model_len,
        "max_num_seqs": scheduler.scheduler_config.max_num_seqs,
        "max_num_batched_tokens": scheduler.scheduler_config.max_num_batched_tokens,
        "full_sequence_must_fit": scheduler.scheduler_reserve_full_isl,
        "prefix_caching": scheduler.cache_config.enable_prefix_caching,
    }
    layout = target_layout()
    expected = {
        "retention_interval": layout["retention_interval"],
        "scheduler_block_size": layout["scheduler_block_size"],
        "hash_block_size": layout["hash_block_size"],
        "max_model_len": layout["max_model_len"],
        "max_num_seqs": conditions["p_max_num_seqs"],
        "max_num_batched_tokens": conditions["p_max_num_batched_tokens"],
        "full_sequence_must_fit": layout["full_sequence_must_fit"],
        "prefix_caching": layout["prefix_caching"],
    }
    if actual != expected:
        raise ValueError(f"native effective profile differs from frozen H20 layout: {actual} != {expected}")
    return actual


def native_source_identity() -> dict:
    classes = (Scheduler, KVCacheManager, HybridKVCacheCoordinator,
               FullAttentionManager, BlockPool, KVCacheConfig)
    sources = {}
    for cls in classes:
        path = Path(inspect.getsourcefile(cls)).resolve()
        sources[cls.__name__] = {
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    return {"vllm_version": importlib.metadata.version("vllm"),
            "classes": sources}


def jsonable(value):
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, int) and abs(value) > 2**53 - 1:
        return str(value)
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: jsonable(item) for key, item in value.items()}
    return value


class EventWriter:
    def __init__(self, stream, event_limit: int, event_windows: list[list[int]], multi_p=False):
        self.stream = stream
        self.event_limit = event_limit
        self.event_windows = event_windows
        self.total = 0
        self.written = 0
        self.step = 0
        self.types = Counter()
        self.removed_by_group = Counter()
        self.multi_p = multi_p
        self.p_domain = "p0"
        self.types_by_p = {}
        self.removed_by_p = {}

    def write_lifecycle(self, event: str, request_id: str, step: int):
        row = {
            "step": step, "kind": "lifecycle", "event": event,
            "request_id": request_id,
        }
        if self.multi_p:
            row["p_domain"] = self.p_domain
        self.stream.write(json.dumps(row) + "\n")

    def publish(self, batch):
        for event in batch.events:
            name = type(event).__name__
            group = getattr(event, "group_idx", None)
            self.total += 1
            self.types[name] += 1
            self.types_by_p.setdefault(self.p_domain, Counter())[name] += 1
            if name == "BlockRemoved":
                self.removed_by_group[str(group)] += len(event.block_hashes)
                self.removed_by_p.setdefault(self.p_domain, Counter())[str(group)] += len(event.block_hashes)
            in_window = not self.event_windows or any(
                first <= self.step <= last for first, last in self.event_windows
            )
            if self.written < self.event_limit and in_window:
                data = msgspec.to_builtins(event)
                row = {
                    "step": self.step, "kind": "native_kv_event",
                    "event": name, "data": jsonable(data),
                }
                if self.multi_p:
                    row["p_domain"] = self.p_domain
                self.stream.write(json.dumps(row, separators=(",", ":")) + "\n")
                self.written += 1

    def shutdown(self):
        pass


def run_capacity(workload, conditions: dict, gib: int, output_dir: Path, routing=None) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    requests = workload.requests
    if conditions["release_protocol"] == "transfer-next-step-client-following-step" and any(
        row.transfer_delay_steps not in (None, 1) for row in requests
    ):
        raise ValueError("next-step release protocol rejects per-request delays greater than one")
    capacity = budgets_from_conditions(conditions)[gib]
    blocks = capacity["physical_blocks"]
    scenario = validate_scenario(conditions, budgets_from_conditions(conditions))
    if routing is None:
        routing = load_routing(None, workload, conditions["p_domains"])
    identity = run_id(hashlib.sha256(workload.source.read_bytes()).hexdigest(), routing.provenance,
                      conditions, gib)
    domains = [f"p{i}" for i in range(conditions["p_domains"])]
    schedulers = {}
    connectors = {}
    profiles = {}
    try:
        for domain in domains:
            scheduler = Scheduler(
                vllm_config=make_vllm_config(
                    blocks, reserve_full_isl=True,
                    max_num_seqs=conditions["p_max_num_seqs"],
                    max_num_batched_tokens=conditions["p_max_num_batched_tokens"],
                ),
                kv_cache_config=make_cache_config(blocks),
                structured_output_manager=NoGrammar(),
                block_size=256, hash_block_size=4,
                mm_registry=NoMultimodal(), log_stats=True,
            )
            schedulers[domain] = scheduler
            if len(scheduler.kv_cache_manager.block_pool.blocks) != blocks:
                raise ValueError("constructed native physical pool differs from resolved budget")
            profiles[domain] = effective_native_profile(scheduler, conditions)
            connector = OfflineTransfer()
            scheduler.connector = connector
            connectors[domain] = connector
        hash_fn = get_hash_fn_by_name("sha256")
        init_none_hash(hash_fn)
        hasher = get_request_block_hasher(4, hash_fn)
    except Exception:
        for scheduler in schedulers.values():
            scheduler.shutdown()
        raise
    profile = profiles[domains[0]]
    default_transfer_delay = conditions["transfer_delay_steps"]
    submitted = set()
    client_active = set()
    client_completed = set()
    client_completion_at = {}
    transfer_completion_at = {}
    records = {
        row.request_id: {
            "request_id": row.request_id,
            "order": row.order,
            "session_id": row.session_id,
            "actor_id": row.actor_id,
            "p_domain": routing.assignments[row.request_id],
            "input_tokens": len(row.token_ids),
            "input_sha256": hashlib.sha256(json.dumps(row.token_ids, separators=(",", ":")).encode()).hexdigest(),
            "declared_output_tokens": row.output_tokens,
            "source_content": workload.content_source,
            "submitted_step": None,
            "first_scheduled_step": None,
            "initial_adopted_tokens": 0,
            "cumulative_input_processing_tokens": 0,
            "completed_input_intervals": [],
            "prefill_complete_step": None,
            "transfer_delay_steps": row.transfer_delay_steps or default_transfer_delay,
            "transfer_complete_step": None,
            "p_reference_release_step": None,
            "client_complete_step": None,
            "preemptions": 0,
            "preemption_steps": [],
            "resume_steps": [],
        }
        for row in requests
    }
    native_requests = {}
    max_steps = int(conditions["max_steps"])
    if max_steps <= 0:
        raise ValueError("max_steps must be positive")
    empty_steps = 0
    stats_by_p = {domain: Counter() for domain in domains}
    peak_active_blocks_by_p = {domain: 0 for domain in domains}
    peak_reusable_blocks_by_p = {domain: 0 for domain in domains}
    peak_active_blocks_global = 0
    failure_reason = None
    failure_type = None

    def collect_native_stats(outputs, domain):
        for value in outputs.values():
            stats = value.scheduler_stats
            if stats is None:
                continue
            prefix = stats.prefix_cache_stats
            stats_by_p[domain]["prefix_queries"] += prefix.queries
            stats_by_p[domain]["prefix_hits"] += prefix.hits
            stats_by_p[domain]["preempted_queries"] += prefix.preempted_queries
            stats_by_p[domain]["preempted_hits"] += prefix.preempted_hits

    with (output_dir / "events.jsonl").open("w") as event_stream, \
         (output_dir / "steps.jsonl").open("w") as step_stream:
        publisher = EventWriter(
            event_stream, int(conditions["event_limit"]),
            conditions.get("event_windows", []), multi_p=len(domains) > 1,
        )
        for scheduler in schedulers.values():
            scheduler.kv_event_publisher = publisher
        try:
            for step in range(1, max_steps + 1):
                publisher.step = step
                # Phase 1: all due P releases happen before any new admission.
                pending_before = {domain: set(connectors[domain].pending)
                                  for domain in domains}
                for domain in domains:
                    publisher.p_domain = domain
                    due_transfers = {
                        request_id for request_id in pending_before[domain]
                        if transfer_completion_at[request_id] <= step
                    }
                    if not due_transfers:
                        continue
                    outputs = schedulers[domain].update_from_output(
                        SchedulerOutput.make_empty(),
                        ModelRunnerOutput.with_kv_conn_output_only(
                            KVConnectorOutput(finished_sending=due_transfers)
                        ),
                    )
                    collect_native_stats(outputs, domain)
                    for request_id in sorted(due_transfers):
                        records[request_id]["transfer_complete_step"] = step
                        records[request_id]["p_reference_release_step"] = step
                        client_completion_at[request_id] = step + 1
                        publisher.write_lifecycle("TransferComplete", request_id, step)
                        publisher.write_lifecycle("PReferenceRelease", request_id, step)
                        del transfer_completion_at[request_id]

                for request_id, due in list(client_completion_at.items()):
                    if due <= step:
                        publisher.p_domain = routing.assignments[request_id]
                        client_active.remove(request_id)
                        client_completed.add(request_id)
                        records[request_id]["client_complete_step"] = step
                        publisher.write_lifecycle("ClientComplete", request_id, step)
                        del client_completion_at[request_id]

                # Phase 2: one global stable-ready admission pass. No P can
                # observe another P's work from the current scheduling phase.
                for row in requests:
                    if len(client_active) >= conditions["client_max_in_flight"]:
                        break
                    if row.request_id in submitted:
                        continue
                    if row.send_after and row.send_after not in client_completed:
                        continue
                    if row.context_after and row.context_after not in client_completed:
                        continue
                    native = Request(
                        request_id=row.request_id,
                        prompt_token_ids=list(row.token_ids),
                        sampling_params=SamplingParams(max_tokens=1, ignore_eos=True),
                        pooling_params=None, block_hasher=hasher,
                    )
                    domain = routing.assignments[row.request_id]
                    publisher.p_domain = domain
                    schedulers[domain].add_request(native)
                    native_requests[row.request_id] = native
                    submitted.add(row.request_id)
                    client_active.add(row.request_id)
                    records[row.request_id]["submitted_step"] = step
                    publisher.write_lifecycle("Submit", row.request_id, step)

                if len(client_completed) == len(requests):
                    break

                # Phase 3: each independent native P advances at most once.
                any_scheduled = False
                active_this_step = 0
                for domain in domains:
                    publisher.p_domain = domain
                    scheduler = schedulers[domain]
                    connector = connectors[domain]
                    step_record = {
                        "step": step,
                        "client_active": sorted(client_active),
                        "running_before": [request.request_id for request in scheduler.running],
                        "waiting_before": len(scheduler.waiting),
                        "pending_transfer_before": sorted(connector.pending),
                        "pending_transfer_due": {
                            request_id: transfer_completion_at[request_id]
                            for request_id in sorted(connector.pending)
                        },
                        "free_blocks_before": scheduler.kv_cache_manager.block_pool.get_num_free_blocks(),
                    }
                    if len(domains) > 1:
                        step_record["p_domain"] = domain
                    scheduled = scheduler.schedule()
                    step_record["scheduled"] = dict(scheduled.num_scheduled_tokens)
                    step_record["preempted_req_ids"] = sorted(scheduled.preempted_req_ids)
                    step_record["resumed_req_ids"] = sorted(
                        scheduled.scheduled_cached_reqs.resumed_req_ids
                    )
                    step_record["running_after_schedule"] = [
                        request.request_id for request in scheduler.running
                    ]
                    step_record["free_blocks_after_schedule"] = (
                        scheduler.kv_cache_manager.block_pool.get_num_free_blocks()
                    )
                    pool = scheduler.kv_cache_manager.block_pool
                    # Block zero is a reserved null block, not an active
                    # request reference. A free hashed block is reusable even
                    # when its primary hash lives on KVCacheBlock.block_hash.
                    active = max(0, blocks - step_record["free_blocks_after_schedule"] - 1)
                    reusable = sum(
                        block.ref_cnt == 0 and not block.is_null and
                        (block.block_hash is not None or
                         block.block_id in pool.cached_block_hashes_by_block)
                        for block in pool.blocks
                    )
                    step_record["physical_pool_blocks"] = len(pool.blocks)
                    step_record["reserved_blocks_after_schedule"] = sum(block.is_null for block in pool.blocks)
                    step_record["unreferenced_uncached_blocks_after_schedule"] = (
                        len(pool.blocks) - step_record["reserved_blocks_after_schedule"] - active - reusable
                    )
                    step_record["active_ref_blocks_after_schedule"] = active
                    step_record["reusable_cached_blocks_after_schedule"] = reusable
                    active_this_step += active
                    for request_id in step_record["preempted_req_ids"]:
                        records[request_id]["preemption_steps"].append(step)
                        publisher.write_lifecycle("Preempted", request_id, step)
                    for request_id in step_record["resumed_req_ids"]:
                        records[request_id]["resume_steps"].append(step)
                        publisher.write_lifecycle("Resumed", request_id, step)
                    input_intervals = {
                        request_id: scheduled_input_interval(
                            scheduler.requests[request_id].num_computed_tokens,
                            num_tokens, scheduler.requests[request_id].num_prompt_tokens)
                        for request_id, num_tokens in scheduled.num_scheduled_tokens.items()
                    }
                    ids = list(scheduled.num_scheduled_tokens)
                    any_scheduled |= bool(ids)
                    generated = [
                        [100] if scheduler.requests[request_id].num_computed_tokens >=
                        scheduler.requests[request_id].num_prompt_tokens else []
                        for request_id in ids
                    ]
                    outputs = scheduler.update_from_output(
                        scheduled,
                        ModelRunnerOutput(
                            req_ids=ids,
                            req_id_to_index={request_id: i for i, request_id in enumerate(ids)},
                            sampled_token_ids=generated,
                        ),
                    )
                    for request_id, (start, end) in input_intervals.items():
                        record = records[request_id]
                        if record["first_scheduled_step"] is None:
                            record["first_scheduled_step"] = step
                            record["initial_adopted_tokens"] = start
                        if end > start:
                            record["completed_input_intervals"].append({
                                "step": step, "start": start, "end": end,
                            })
                            record["cumulative_input_processing_tokens"] += end - start
                    peak_active_blocks_by_p[domain] = max(peak_active_blocks_by_p[domain], active)
                    peak_reusable_blocks_by_p[domain] = max(peak_reusable_blocks_by_p[domain], reusable)
                    step_stream.write(json.dumps(step_record, separators=(",", ":")) + "\n")
                    collect_native_stats(outputs, domain)
                    for request_id in ids:
                        if request_id in connector.pending and records[request_id]["prefill_complete_step"] is None:
                            records[request_id]["prefill_complete_step"] = step
                            transfer_completion_at[request_id] = (
                                step + records[request_id]["transfer_delay_steps"]
                            )
                            publisher.write_lifecycle("PrefillComplete", request_id, step)

                peak_active_blocks_global = max(peak_active_blocks_global, active_this_step)
                if any_scheduled or any(connector.pending for connector in connectors.values()) or client_completion_at:
                    empty_steps = 0
                else:
                    empty_steps += 1
                if empty_steps >= 2:
                    raise ExecutionIncomplete(
                        f"no progress at step {step}: submitted={len(submitted)} "
                        f"completed={len(client_completed)} waiting="
                        f"{sum(s.get_num_unfinished_requests() for s in schedulers.values())}"
                    )
            else:
                raise ExecutionIncomplete(f"max_steps={max_steps} reached")
        except ExecutionIncomplete as error:
            failure_reason = str(error)
            failure_type = type(error).__name__
        except Exception as error:
            failure_reason = f"{type(error).__name__}: {error}"
            failure_type = type(error).__name__
        finally:
            for scheduler in schedulers.values():
                try:
                    scheduler.shutdown()
                except Exception as error:
                    if failure_reason is None:
                        failure_reason = f"scheduler shutdown {type(error).__name__}: {error}"
                        failure_type = type(error).__name__

    for record in records.values():
        record.update(completed_input_totals(record["completed_input_intervals"]))

    for request_id, native in native_requests.items():
        records[request_id]["preemptions"] = native.num_preemptions

    with (output_dir / "requests.jsonl").open("w") as stream:
        for row in requests:
            stream.write(json.dumps(records[row.request_id], ensure_ascii=False) + "\n")

    input_tokens = sum(len(row.token_ids) for row in requests)
    adopted = sum(record["initial_adopted_tokens"] for record in records.values())
    processed = sum(record["cumulative_input_processing_tokens"] for record in records.values())
    activity = activity_by_p(list(records.values()), load_jsonl(output_dir / "steps.jsonl"), domains)
    aggregate_stats = sum(stats_by_p.values(), Counter())
    prefix_queries = aggregate_stats["prefix_queries"]
    prefix_hits = aggregate_stats["prefix_hits"]
    preempted_queries = aggregate_stats["preempted_queries"]
    preempted_hits = aggregate_stats["preempted_hits"]
    per_p = {}
    for domain in domains:
        members = [record for record in records.values() if record["p_domain"] == domain]
        domain_input = sum(record["input_tokens"] for record in members)
        domain_adopted = sum(record["initial_adopted_tokens"] for record in members)
        domain_stats = stats_by_p[domain]
        per_p[domain] = {
            "requests_planned": len(members),
            "requests_completed": sum(record["client_complete_step"] is not None for record in members),
            "actual_input_tokens": domain_input,
            "initial_adopted_cache_tokens": domain_adopted,
            "actual_input_cache_fraction": domain_adopted / domain_input if domain_input and failure_reason is None else None,
            "cumulative_input_processing_tokens": sum(
                record["cumulative_input_processing_tokens"] for record in members),
            "prefix_queries": domain_stats["prefix_queries"],
            "prefix_hits": domain_stats["prefix_hits"],
            "prefix_query_hit_rate": (domain_stats["prefix_hits"] / domain_stats["prefix_queries"]
                                      if domain_stats["prefix_queries"] else None),
            "preempted_queries": domain_stats["preempted_queries"],
            "preempted_hits": domain_stats["preempted_hits"],
            "native_event_counts": dict(publisher.types_by_p.get(domain, {})),
            "removed_hash_entries_by_group": dict(publisher.removed_by_p.get(domain, {})),
            "peak_active_blocks": peak_active_blocks_by_p[domain],
            "peak_reusable_cached_blocks": peak_reusable_blocks_by_p[domain],
            **activity[domain],
        }
    observation = round_observation(load_jsonl(output_dir / "steps.jsonl"), domains, failure_reason is None)
    summary = {
        "observation_boundary": observation,
        "run_id": identity,
        "scenario_id": conditions.get("scenario_id", "h20-controlled"),
        "budget_provenance": scenario["budgets"][str(gib)],
        "status": "complete" if failure_reason is None else "incomplete",
        "failure_reason": failure_reason,
        "failure_type": failure_type,
        "capacity_gib_per_rank": budgets_from_conditions(conditions)[gib]["budget_gib_per_rank"],
        "point_id": gib,
        "physical_blocks": blocks,
        "p_domains": len(domains),
        "per_p": per_p,
        "peak_active_blocks_global": observation["full_round_active_peak"],
        "waiting_request_steps": sum(item["waiting_request_steps"] for item in activity.values()),
        "preemptions": sum(item["preemptions"] for item in activity.values()),
        "resumes": sum(item["resumes"] for item in activity.values()),
        "capacity_budget": capacity,
        "requests_planned": len(requests),
        "requests_completed": len(client_completed),
        "requests_unfinished": len(requests) - len(client_completed),
        "logical_steps": step,
        "actual_input_tokens": input_tokens,
        "initial_adopted_cache_tokens": adopted,
        "actual_input_cache_fraction": (
            adopted / input_tokens if failure_reason is None and input_tokens else None
        ),
        "cumulative_input_processing_tokens": processed,
        "prefix_queries": prefix_queries,
        "prefix_hits": prefix_hits,
        "prefix_query_hit_rate": prefix_hits / prefix_queries if prefix_queries else None,
        "preempted_queries": preempted_queries,
        "preempted_hits": preempted_hits,
        "native_event_counts": dict(publisher.types),
        "removed_hash_entries_by_group": dict(publisher.removed_by_group),
        "events_written": publisher.written,
        "events_native_total": publisher.total,
        "events_coverage": (
            "all" if publisher.written == publisher.total else
            f"native events in windows {publisher.event_windows or 'from start'}, "
            f"capped at {publisher.event_limit}; {publisher.written}/{publisher.total} written"
        ),
        "content_source": workload.content_source,
        "metric_scope": (
            "all requests" if failure_reason is None
            else f"partial through logical step {step}; unfinished requests retained"
        ),
        "execution_protocol": conditions["release_protocol"],
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    (output_dir / "manifest.json").write_text(json.dumps({
        "run_id": identity,
        "scenario_id": conditions.get("scenario_id", "h20-controlled"),
        "scenario": scenario,
        "workload_path": str(workload.source),
        "workload_sha256": hashlib.sha256(workload.source.read_bytes()).hexdigest(),
        "workload_content_source": workload.content_source,
        "workload_execution_profile": workload.execution_profile,
        "workload_order_source": workload.order_source,
        "workload_capture_provenance": workload.capture_provenance,
        "conditions": conditions,
        "routing": routing.provenance,
        "logical_round_order": "due P releases; client completions; global stable-ready submissions; one native schedule and completion per P in domain order",
        "capacity_budget": capacity,
        "effective_native_profile": profile,
        "effective_native_profile_by_p": profiles,
        "model_execution": "synthetic one-token completion; no tensor computation",
        "arrival_semantics": "stable ready order; effective_interval_seconds deliberately not used",
        "transfer_semantics": (
            "transfer completes after each request's declared positive logical-step "
            "delay following P completion; client completes one step after transfer"
        ),
        "declared_output_semantics": (
            "Replay output length and frozen successor token content are retained as workload "
            "provenance; this P-only logical driver synthesizes one completion token and "
            "does not simulate D decoding time"
        ),
        "prefix_hash_seed": os.environ.get("PYTHONHASHSEED"),
        "native_source_identity": native_source_identity(),
        "input_accounting": "completed-input-intervals/post-schedule-cursor-v1",
        "group_layout_provenance": (
            "stage-v5/formal-3454 effective_cache_config: exact five group "
            "specs/layer names and 63 tensor offsets/strides; tensor sizes "
            "scaled by physical block count; no worker tensor allocation"
        ),
    }, indent=2, ensure_ascii=False))
    return summary


def write_unstarted_capacity(workload, conditions: dict, gib: int,
                             output_dir: Path, error: Exception, routing=None) -> dict:
    """Preserve a planned point if native initialization fails before a run."""
    output_dir.mkdir(parents=True, exist_ok=True)
    reason = f"{type(error).__name__}: {error}"
    identity = run_id(hashlib.sha256(workload.source.read_bytes()).hexdigest(),
                      routing.provenance if routing else {"method": "all-p0"}, conditions, gib)
    scenario = validate_scenario(conditions, budgets_from_conditions(conditions))
    summary_path = output_dir / "summary.json"
    if summary_path.exists() and (output_dir / "requests.jsonl").exists():
        summary = json.loads(summary_path.read_text())
        summary.update(run_id=identity, scenario_id=conditions.get("scenario_id", "h20-controlled"),
                       budget_provenance=scenario["budgets"][str(gib)],
                       status="incomplete", failure_reason=reason,
                       failure_type=type(error).__name__, actual_input_cache_fraction=None)
    else:
        with (output_dir / "requests.jsonl").open("w") as stream:
            for row in workload.requests:
                stream.write(json.dumps({
                    "request_id": row.request_id, "order": row.order,
                    "p_domain": routing.assignments[row.request_id] if routing else "p0",
                    "session_id": row.session_id, "actor_id": row.actor_id,
                    "input_tokens": len(row.token_ids), "source_content": workload.content_source,
                    "input_sha256": hashlib.sha256(json.dumps(row.token_ids, separators=(",", ":")).encode()).hexdigest(),
                    "declared_output_tokens": row.output_tokens,
                    "submitted_step": None, "first_scheduled_step": None,
                    "initial_adopted_tokens": 0, "cumulative_input_processing_tokens": 0,
                    "prefill_complete_step": None, "transfer_delay_steps": row.transfer_delay_steps or conditions["transfer_delay_steps"],
                    "transfer_complete_step": None, "p_reference_release_step": None,
                    "client_complete_step": None, "preemptions": 0,
                    "preemption_steps": [], "resume_steps": [],
                }, ensure_ascii=False) + "\n")
        summary = {
            "run_id": identity, "scenario_id": conditions.get("scenario_id", "h20-controlled"),
            "budget_provenance": scenario["budgets"][str(gib)],
            "status": "not_run", "failure_reason": reason,
            "failure_type": type(error).__name__, "capacity_gib_per_rank": budgets_from_conditions(conditions)[gib]["budget_gib_per_rank"],
        "point_id": gib,
            "physical_blocks": budgets_from_conditions(conditions)[gib]["physical_blocks"],
            "p_domains": conditions["p_domains"],
            "capacity_budget": budgets_from_conditions(conditions)[gib],
            "requests_planned": len(workload.requests), "requests_completed": 0,
            "requests_unfinished": len(workload.requests), "logical_steps": 0,
            "actual_input_tokens": workload.total_input_tokens,
            "initial_adopted_cache_tokens": 0, "actual_input_cache_fraction": None,
            "cumulative_input_processing_tokens": 0,
            "prefix_queries": 0, "prefix_hits": 0, "prefix_query_hit_rate": None,
            "preempted_queries": 0, "preempted_hits": 0,
            "native_event_counts": {}, "removed_hash_entries_by_group": {},
            "events_written": 0, "events_native_total": 0, "events_coverage": "none; point did not start",
            "content_source": workload.content_source,
            "metric_scope": "no execution; all planned requests retained",
            "execution_protocol": conditions["release_protocol"],
        }
        domains = [f"p{i}" for i in range(conditions["p_domains"])]
        summary["per_p"] = {}
        for domain in domains:
            members = [row for row in workload.requests
                       if (routing.assignments[row.request_id] if routing else "p0") == domain]
            summary["per_p"][domain] = {
                "requests_planned": len(members), "requests_completed": 0,
                "actual_input_tokens": sum(len(row.token_ids) for row in members),
                "initial_adopted_cache_tokens": 0,
                "actual_input_cache_fraction": None,
                "cumulative_input_processing_tokens": 0,
                "prefix_queries": 0, "prefix_hits": 0, "prefix_query_hit_rate": None,
                "preempted_queries": 0, "preempted_hits": 0,
                "native_event_counts": {}, "removed_hash_entries_by_group": {},
                "peak_active_blocks": 0, "peak_reusable_cached_blocks": 0,
                "waiting_request_steps": 0, "waiting_peak": 0, "running_peak": 0,
                "preemptions": 0, "resumes": 0,
            }
        summary.update(peak_active_blocks_global=0, waiting_request_steps=0,
                       preemptions=0, resumes=0)
        for filename in ("events.jsonl", "steps.jsonl"):
            (output_dir / filename).touch(exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    manifest = output_dir / "manifest.json"
    if not manifest.exists():
        manifest.write_text(json.dumps({
            "run_id": identity,
            "scenario_id": conditions.get("scenario_id", "h20-controlled"),
            "scenario": scenario,
            "workload_path": str(workload.source),
            "workload_sha256": hashlib.sha256(workload.source.read_bytes()).hexdigest(),
            "workload_content_source": workload.content_source,
            "workload_execution_profile": workload.execution_profile,
            "workload_capture_provenance": workload.capture_provenance,
            "conditions": conditions, "effective_native_profile": None,
            "routing": routing.provenance if routing else None,
            "capacity_budget": budgets_from_conditions(conditions)[gib],
            "initialization_error": reason,
        }, indent=2, ensure_ascii=False))
    return summary


def main():
    if os.environ.get("PYTHONHASHSEED") != "0":
        raise ValueError("set PYTHONHASHSEED=0 before the native capacity scan")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workload", type=Path)
    parser.add_argument("conditions", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    conditions = read_conditions(args.conditions)
    workload = load_replay_workload(args.workload)
    validate_h20_workload(workload)
    routing_path = None
    if conditions["routing"] == "trace":
        routing_path = Path(conditions["routing_trace"])
        if not routing_path.is_absolute():
            routing_path = args.conditions.parent / routing_path
    routing = load_routing(routing_path, workload, conditions["p_domains"])
    if args.output.exists() and any(args.output.iterdir()):
        raise ValueError(f"output directory is not empty: {args.output}")
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "scan.json").write_text(json.dumps({
        "schema": "kvlab-native-scan/v1",
        "point_ids": list(budgets_from_conditions(conditions)),
        **({"capacities_gib": conditions["capacities_gib"]} if "capacities_gib" in conditions else {}),
        "profile": conditions["profile"], "workload": str(workload.source),
        "workload_sha256": hashlib.sha256(workload.source.read_bytes()).hexdigest(),
        "routing": routing.provenance,
    }, indent=2))
    failed = False
    for gib in budgets_from_conditions(conditions):
        output_dir = point_directory(args.output, gib)
        try:
            summary = run_capacity(workload, conditions, gib, output_dir, routing)
        except Exception as error:
            summary = write_unstarted_capacity(workload, conditions, gib, output_dir, error, routing)
        print(json.dumps({**summary, "result_path": str((output_dir / "summary.json").resolve())}, ensure_ascii=False), flush=True)
        failed |= summary["status"] != "complete"
    if failed:
        raise RuntimeError("native scan contains incomplete or unstarted capacity points; inspect each summary")


if __name__ == "__main__":
    main()
