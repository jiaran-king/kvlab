"""Freeze the existing Replay export as input to the native offline driver.

This module validates documented workload fields. It does not infer prefix
reuse from session IDs; the full token sequence remains the content identity.
"""

from __future__ import annotations

import json
import gzip
from dataclasses import dataclass
from pathlib import Path
from kvsim.native.capacity import target_layout


SUPPORTED_EXECUTION_PROFILES = {
    "request-admission",
    "historical-first-query-order-conditional",
    "artificial-p-reference-delay-mechanism",
}
H20_CONDITION_FIELDS = {
    "schema", "profile", "p_domains", "routing", "p_max_num_seqs",
    "p_max_num_batched_tokens", "full_sequence_must_fit",
    "client_max_in_flight", "arrival_protocol", "release_protocol",
    "transfer_delay_steps", "capacities_gib", "capacity_points", "max_steps",
    "event_limit", "event_windows",
    "routing_trace",
    "scenario_id",
    "scenario",
}


def validate_h20_condition_fields(conditions: dict) -> None:
    unknown = sorted(set(conditions) - H20_CONDITION_FIELDS)
    if unknown:
        raise ValueError(f"unsupported H20 condition fields: {', '.join(unknown)}")


@dataclass(frozen=True)
class FrozenRequest:
    order: int
    request_id: str
    session_id: str
    actor_id: str
    source_key: str
    node_type: str
    token_ids: tuple[int, ...]
    output_tokens: int
    send_after: str | None
    context_after: str | None
    effective_interval_seconds: float
    transfer_delay_steps: int | None


@dataclass(frozen=True)
class FrozenWorkload:
    source: Path
    content_source: str
    execution_profile: str
    capture_provenance: dict
    order_source: dict
    requests: tuple[FrozenRequest, ...]

    @property
    def total_input_tokens(self) -> int:
        return sum(len(request.token_ids) for request in self.requests)


def load_replay_workload(path: str | Path) -> FrozenWorkload:
    source = Path(path).resolve()
    if source.suffix == ".gz":
        with gzip.open(source, "rt") as stream:
            data = json.load(stream)
    else:
        data = json.loads(source.read_text())
    if data.get("schema") != "kvlab-replay-workload/v1":
        raise ValueError("unsupported workload schema")
    metadata = data["metadata"]
    content_source = metadata["content_source"]
    if content_source not in {"synthetic", "trace_driven_synthetic", "historical_capture", "captured_tokens"}:
        raise ValueError(f"unsupported content source: {content_source}")
    execution_profile = metadata.get("execution_profile")
    if execution_profile not in SUPPORTED_EXECUTION_PROFILES:
        raise ValueError(f"unsupported native execution profile: {execution_profile}")
    if content_source == "captured_tokens" and not all(
        metadata.get(field) for field in ("tokenizer_sha256", "prompt_template")
    ):
        raise ValueError("captured_tokens requires tokenizer and prompt-template provenance")
    rows = data["requests"]
    if not isinstance(rows, list) or not rows:
        raise ValueError("native workload has no requests")
    seen: set[str] = set()
    requests: list[FrozenRequest] = []
    for order, row in enumerate(rows):
        request_id = row["runtime_request_id"]
        if not isinstance(request_id, str) or not request_id or request_id in seen:
            raise ValueError(f"missing or duplicate request ID at row {order}")
        tokens = row["tokens"]
        if not isinstance(tokens, list) or not tokens or any(
            type(token) is not int or token < 0 for token in tokens
        ):
            raise ValueError(f"invalid token array for {request_id}")
        if len(tokens) != row["input_tokens"]:
            raise ValueError(f"input length mismatch for {request_id}")
        if row["content_source"] != content_source:
            raise ValueError(f"content source mismatch for {request_id}")
        if row.get("cache_identity", "") != "":
            raise ValueError(f"non-empty cache identity is unsupported for {request_id}")
        if row["node_type"] != "request":
            raise ValueError(f"unsupported node type for {request_id}")
        output_tokens = row["output_tokens"]
        if type(output_tokens) is not int or output_tokens < 0:
            raise ValueError(f"invalid output length for {request_id}")
        interval = row["effective_interval_seconds"]
        if type(interval) not in (int, float) or interval < 0:
            raise ValueError(f"invalid external interval for {request_id}")
        transfer_delay_steps = row.get("transfer_delay_steps")
        if transfer_delay_steps is not None and (
            type(transfer_delay_steps) is not int or transfer_delay_steps < 1
        ):
            raise ValueError(f"invalid transfer delay for {request_id}")
        for field in ("send_after", "context_after"):
            predecessor = row[field]
            if predecessor is not None and predecessor not in seen:
                raise ValueError(f"{field} for {request_id} is not an earlier request")
        requests.append(
            FrozenRequest(
                order=order,
                request_id=request_id,
                session_id=row["runtime_session_id"],
                actor_id=row["actor_id"],
                source_key=row["source_key"],
                node_type=row["node_type"],
                token_ids=tuple(tokens),
                output_tokens=output_tokens,
                send_after=row["send_after"],
                context_after=row["context_after"],
                effective_interval_seconds=float(interval),
                transfer_delay_steps=transfer_delay_steps,
            )
        )
        seen.add(request_id)
    return FrozenWorkload(
        source=source,
        content_source=content_source,
        execution_profile=execution_profile,
        capture_provenance=metadata.get("capture_provenance", {}),
        order_source=metadata.get("historical_order_source", {}),
        requests=tuple(requests),
    )


def validate_h20_workload(workload: FrozenWorkload) -> None:
    """Reject prompts that cannot fit the fixed H20 P request plus its output token."""
    max_model_len = target_layout()["max_model_len"]
    for row in workload.requests:
        if len(row.token_ids) + 1 > max_model_len:
            raise ValueError(
                f"request {row.request_id} has {len(row.token_ids)} input tokens; "
                f"H20 max_model_len={max_model_len} must also fit one completion token"
            )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workload")
    args = parser.parse_args()
    frozen = load_replay_workload(args.workload)
    print(
        json.dumps(
            {
                "requests": len(frozen.requests),
                "sessions": len({r.session_id for r in frozen.requests}),
                "input_tokens": frozen.total_input_tokens,
                "content_source": frozen.content_source,
                "execution_profile": frozen.execution_profile,
            },
            ensure_ascii=False,
        )
    )
