"""Replace synthetic prompt tokens with a verified historical P-side capture.

The existing workload supplies stable request order and dependencies. The
historical input index maps each source_key to its actual P token span. No
model output is generated or inferred by this conversion.
"""

from __future__ import annotations

import argparse
import gzip
import json
import struct
from pathlib import Path


def convert(workload_path: Path, index_path: Path, tokens_path: Path,
            output_path: Path) -> dict:
    workload = json.loads(workload_path.read_text())
    index = json.loads(index_path.read_text())
    if workload.get("schema") != "kvlab-replay-workload/v1":
        raise ValueError("unsupported workload schema")
    rows = workload["requests"]
    if len(rows) != 425 or len(index) != 425:
        raise ValueError("expected 425 request rows and 425 indexed captures")
    keys = [row["source_key"] for row in rows]
    if len(set(keys)) != 425 or set(keys) != set(index):
        raise ValueError("capture source keys do not match workload one-to-one")

    if tokens_path.suffix == ".gz":
        with gzip.open(tokens_path, "rb") as stream:
            packed = stream.read()
    else:
        packed = tokens_path.read_bytes()
    if len(packed) % 4:
        raise ValueError("captured u32 file is not aligned")

    original_same = 0
    for row in rows:
        record = index[row["source_key"]]["record"]
        identity = record["semantic_identity"]
        if identity != {
            "cache_salt": None,
            "lora_request": None,
            "mm_features": [],
            "prompt_embeds": None,
            "skip_reading_prefix_cache": False,
        }:
            raise ValueError(f"unsupported cache identity for {row['source_key']}")
        count = record["count"]
        offset = record["offset_bytes"]
        if count != row["input_tokens"] or type(offset) is not int or offset < 0:
            raise ValueError(f"capture count or offset mismatch: {row['source_key']}")
        end = offset + 4 * count
        if offset % 4 or end > len(packed):
            raise ValueError(f"capture span out of bounds: {row['source_key']}")
        captured = [value for (value,) in struct.iter_unpack("<I", packed[offset:end])]
        original_same += captured == row["tokens"]
        row["tokens"] = captured
        row["content_source"] = "historical_capture"
        row["capture_server_request_id"] = record["request_id"]

    metadata = workload["metadata"]
    metadata["content_source"] = "historical_capture"
    metadata["capture_provenance"] = {
        "historical_run": "stage-v5/retry-1/formal-3458 (C12 capture for F12/F24)",
        "input_index": str(index_path),
        "token_file": str(tokens_path),
        "mapping": "source_key -> input-index record -> little-endian u32 span",
        "capture_scope": "425 formal P-side inputs; two smoke entries excluded",
        "semantic_identity": "no salt, LoRA, multimodal features, prompt embeddings, or prefix-cache bypass",
    }
    metadata["assumptions"] = [
        "P input token IDs are captured from formal F12, not reconstructed from lengths.",
        "Original workload dependency graph and stable order are retained.",
        "Offline arrival and P release remain deterministic logical approximations.",
        "D output content is already frozen into captured successor P inputs; it is not added to P cache on its own.",
    ]
    result = {
        "requests": len(rows),
        "input_tokens": sum(row["input_tokens"] for row in rows),
        "same_as_prior_synthetic_tokens": original_same,
        "captured_u32_bytes": len(packed),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(workload, ensure_ascii=False, separators=(",", ":")))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workload", type=Path)
    parser.add_argument("index", type=Path)
    parser.add_argument("tokens", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    print(json.dumps(convert(args.workload, args.index, args.tokens, args.output)))
