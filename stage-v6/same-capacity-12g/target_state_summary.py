#!/usr/bin/env python3
"""Bounded CPU-only extraction for the sole non-zero F12-A/F12-B pair delta."""
import argparse, json, os, struct

TARGET = "r00000372-1c6acbc472187251"

def load_json(path):
    with open(path) as f:
        return json.load(f)

def find_body_record(path, source_key):
    with open(path) as f:
        for line in f:
            rec = json.loads(line)
            if rec.get("source_key") == source_key:
                return {k: rec.get(k) for k in ("source_key", "client_request_id", "context_after", "send_after", "seed")}
    return None

def read_u32_segment(path, offset_bytes, count):
    with open(path, "rb") as f:
        f.seek(offset_bytes)
        raw = f.read(count * 4)
    if len(raw) != count * 4:
        raise ValueError(f"short token segment {path}: {len(raw)} != {count*4}")
    return list(struct.unpack(f"<{count}I", raw))

def lookup_records(path, request_id):
    out = []
    with open(path) as f:
        for line in f:
            rec = json.loads(line)
            if rec.get("request_id") == request_id:
                kind = rec.get("kind")
                if kind in {"P_request_received", "group_lookup", "joint_lookup", "lookup", "lookup_decision"}:
                    # Keep all fields for later audit, but never include token arrays or bodies.
                    out.append(rec)
    return out

def lcp(a, b):
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i

def one(run_name, run_dir, query_file):
    idx = load_json(os.path.join(run_dir, "input-index.json"))
    tgt = idx[TARGET]["record"]
    tgt_file = os.path.join(run_dir, idx[TARGET]["file"])
    tgt_tokens = read_u32_segment(tgt_file, tgt["offset_bytes"], tgt["count"])
    body = find_body_record(os.path.join(run_dir, "request-bodies.jsonl"), TARGET)
    predecessor_key = body.get("context_after") if body else None
    pred = None
    pred_tokens = None
    pred_lcp = None
    if predecessor_key and predecessor_key in idx:
        pred_idx = idx[predecessor_key]["record"]
        pred_file = os.path.join(run_dir, idx[predecessor_key]["file"])
        pred_tokens = read_u32_segment(pred_file, pred_idx["offset_bytes"], pred_idx["count"])
        pred = {"source_key": predecessor_key, "request_id": pred_idx.get("request_id"), "count": pred_idx.get("count"), "time": pred_idx.get("time")}
        pred_lcp = lcp(pred_tokens, tgt_tokens)
    records = lookup_records(os.path.join(run_dir, query_file), tgt["request_id"])
    compact = []
    for r in records:
        kind = r.get("kind")
        if kind == "group_lookup":
            compact.append({k: r.get(k) for k in ("kind", "attempt", "call", "manager", "groups", "candidate", "returned", "alignment_tokens", "drop_eagle_block")})
        elif kind == "P_request_received":
            compact.append({k: r.get(k) for k in ("kind", "time", "prompt_token_count", "request_id")})
        elif kind in {"joint_lookup", "lookup", "lookup_decision"}:
            item = {k: r.get(k) for k in r.keys() if k not in {"request_id", "time"}}
            item["kind"] = kind
            item["time"] = r.get("time")
            compact.append(item)
    return {
        "run": run_name,
        "source_key": TARGET,
        "request_id": tgt.get("request_id"),
        "input_count": tgt.get("count"),
        "semantic_identity": tgt.get("semantic_identity"),
        "context_after": predecessor_key,
        "predecessor": pred,
        "lcp_target_vs_predecessor": pred_lcp,
        "lookup_records": compact,
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--a-dir", required=True)
    ap.add_argument("--b-dir", required=True)
    ap.add_argument("--a-query", required=True)
    ap.add_argument("--b-query", required=True)
    args = ap.parse_args()
    result = {
        "target": TARGET,
        "runs": [
            one("F12-A", args.a_dir, args.a_query),
            one("F12-B-exact", args.b_dir, args.b_query),
        ],
        "method": "Reads only target and context_after token segments from captured uint32 P-input files; no model execution.",
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(result, f, indent=2, sort_keys=True)
        f.write("\n")

if __name__ == "__main__":
    main()
