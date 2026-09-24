#!/usr/bin/env python3
"""Create a compact paired report for the two frozen-input 12 GiB runs.

The script deliberately uses request-level evidence already produced by the
acceptance hook.  It does not infer cache state from event counts and does not
turn one run into a stability claim.
"""
import argparse
import csv
import json
import math
from pathlib import Path


FIELDS = [
    "source_key", "actor_id", "session_id", "context_after", "input_tokens",
    "output_tokens", "adopted_local_cache_tokens", "query_calls", "query_tokens",
    "query_hit_tokens", "external_tokens", "ttft_seconds", "e2e_seconds",
    "slot_wait_seconds", "enqueue_to_first_token_seconds", "lcp_tokens",
    "first_reducing_groups", "first_candidate", "first_returned",
]


def read_rows(path: Path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def num(row, key, default=0.0):
    value = row.get(key, "")
    if value in (None, "", "NA", "nan"):
        return default
    return float(value)


def normalize(row):
    out = dict(row)
    for k in FIELDS:
        out.setdefault(k, "")
    return out


def percentile(values, q):
    xs = sorted(float(x) for x in values if math.isfinite(float(x)))
    if not xs:
        return float("nan")
    if len(xs) == 1:
        return xs[0]
    pos = (len(xs) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    if lo == hi:
        return xs[lo]
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)


def summarize(label, rows, accepted=None, cleanup=None):
    total_input = sum(num(r, "input_tokens") for r in rows)
    adopted = sum(num(r, "adopted_local_cache_tokens") for r in rows)
    local = sum(num(r, "input_tokens") - num(r, "adopted_local_cache_tokens") - num(r, "external_tokens") for r in rows)
    query = sum(num(r, "query_tokens") for r in rows)
    hits = sum(num(r, "query_hit_tokens") for r in rows)
    result = {
        "label": label,
        "requests": len(rows),
        "input_tokens": int(total_input),
        "output_tokens": int(sum(num(r, "output_tokens") for r in rows)),
        "adopted_local_cache_tokens": int(adopted),
        "local_compute_tokens": int(local),
        "input_cache_fraction": adopted / total_input if total_input else None,
        "query_tokens": int(query),
        "query_hit_tokens": int(hits),
        "query_hit_rate": hits / query if query else None,
        "query_calls": int(sum(num(r, "query_calls") for r in rows)),
        "ttft_p50": percentile([num(r, "ttft_seconds") for r in rows], .50),
        "ttft_p95": percentile([num(r, "ttft_seconds") for r in rows], .95),
        "e2e_p50": percentile([num(r, "e2e_seconds") for r in rows], .50),
        "e2e_p95": percentile([num(r, "e2e_seconds") for r in rows], .95),
        "slot_wait_p50": percentile([num(r, "slot_wait_seconds") for r in rows], .50),
        "slot_wait_p95": percentile([num(r, "slot_wait_seconds") for r in rows], .95),
        "enqueue_ttft_p50": percentile([num(r, "enqueue_to_first_token_seconds") for r in rows], .50),
        "enqueue_ttft_p95": percentile([num(r, "enqueue_to_first_token_seconds") for r in rows], .95),
    }
    if accepted and accepted.exists():
        result.update({"accepted": json.loads(accepted.read_text()).get("passed", False)})
    if cleanup and cleanup.exists():
        result.update({"cleanup_passed": json.loads(cleanup.read_text()).get("resource_cleanup_passed", False)})
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", type=Path, required=True, help="F12-A request evidence CSV")
    ap.add_argument("--b", type=Path, required=True, help="F12-B request evidence CSV")
    ap.add_argument("--a-label", default="F12A")
    ap.add_argument("--b-label", default="F12B")
    ap.add_argument("--a-run", type=Path, help="A run directory containing ACCEPTED/cleanup metadata")
    ap.add_argument("--b-run", type=Path, help="B run directory containing ACCEPTED/cleanup metadata")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    a = {r["source_key"]: normalize(r) for r in read_rows(args.a)}
    b = {r["source_key"]: normalize(r) for r in read_rows(args.b)}
    common = sorted(set(a) & set(b))
    if set(a) != set(b):
        missing_a, missing_b = sorted(set(b)-set(a)), sorted(set(a)-set(b))
        raise SystemExit(f"source-key mismatch: missing in A={missing_a[:3]} missing in B={missing_b[:3]}")
    paired_path = args.out / "paired-requests.csv"
    columns = ["source_key", "actor_id", "session_id", "input_tokens", "output_tokens",
               "A_adopted", "B_adopted", "delta_adopted_B_minus_A",
               "A_local_compute", "B_local_compute", "delta_local_compute_B_minus_A",
               "A_query_calls", "B_query_calls", "A_query_tokens", "B_query_tokens",
               "A_query_hit_tokens", "B_query_hit_tokens", "A_ttft", "B_ttft",
               "delta_ttft_B_minus_A", "A_e2e", "B_e2e", "delta_e2e_B_minus_A",
               "A_slot_wait", "B_slot_wait", "A_enqueue_ttft", "B_enqueue_ttft",
               "A_lcp_tokens", "B_lcp_tokens", "A_first_reducing_groups", "B_first_reducing_groups"]
    with paired_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        for key in common:
            x, y = a[key], b[key]
            xa, xb = num(x, "adopted_local_cache_tokens"), num(y, "adopted_local_cache_tokens")
            lc_a = num(x, "input_tokens") - xa - num(x, "external_tokens")
            lc_b = num(y, "input_tokens") - xb - num(y, "external_tokens")
            row = {
                "source_key": key, "actor_id": y.get("actor_id") or x.get("actor_id"),
                "session_id": y.get("session_id") or x.get("session_id"),
                "input_tokens": int(num(x, "input_tokens")), "output_tokens": int(num(x, "output_tokens")),
                "A_adopted": int(xa), "B_adopted": int(xb), "delta_adopted_B_minus_A": int(xb-xa),
                "A_local_compute": int(lc_a), "B_local_compute": int(lc_b), "delta_local_compute_B_minus_A": int(lc_b-lc_a),
                "A_query_calls": int(num(x, "query_calls")), "B_query_calls": int(num(y, "query_calls")),
                "A_query_tokens": int(num(x, "query_tokens")), "B_query_tokens": int(num(y, "query_tokens")),
                "A_query_hit_tokens": int(num(x, "query_hit_tokens")), "B_query_hit_tokens": int(num(y, "query_hit_tokens")),
                "A_ttft": num(x, "ttft_seconds"), "B_ttft": num(y, "ttft_seconds"), "delta_ttft_B_minus_A": num(y, "ttft_seconds")-num(x, "ttft_seconds"),
                "A_e2e": num(x, "e2e_seconds"), "B_e2e": num(y, "e2e_seconds"), "delta_e2e_B_minus_A": num(y, "e2e_seconds")-num(x, "e2e_seconds"),
                "A_slot_wait": num(x, "slot_wait_seconds"), "B_slot_wait": num(y, "slot_wait_seconds"),
                "A_enqueue_ttft": num(x, "enqueue_to_first_token_seconds"), "B_enqueue_ttft": num(y, "enqueue_to_first_token_seconds"),
                "A_lcp_tokens": int(num(x, "lcp_tokens")), "B_lcp_tokens": int(num(y, "lcp_tokens")),
                "A_first_reducing_groups": x.get("first_reducing_groups", ""), "B_first_reducing_groups": y.get("first_reducing_groups", ""),
            }
            w.writerow(row)
    a_run = args.a_run or args.a.parent
    b_run = args.b_run or args.b.parent
    accepted_a = a_run / "ACCEPTED.json"
    accepted_b = b_run / "ACCEPTED.json"
    if not accepted_a.exists() and (a_run / "F12-ACCEPTED.json").exists():
        accepted_a = a_run / "F12-ACCEPTED.json"
    if not accepted_b.exists() and (b_run / "F12-ACCEPTED.json").exists():
        accepted_b = b_run / "F12-ACCEPTED.json"
    clean_a = a_run / "cleanup-audit.json"
    clean_b = b_run / "cleanup-audit.json"
    if not clean_a.exists() and (a_run / "F12-cleanup-audit.json").exists():
        clean_a = a_run / "F12-cleanup-audit.json"
    if not clean_b.exists() and (b_run / "F12-cleanup-audit.json").exists():
        clean_b = b_run / "F12-cleanup-audit.json"
    summaries = [summarize(args.a_label, list(a.values()), accepted_a, clean_a), summarize(args.b_label, list(b.values()), accepted_b, clean_b)]
    with (args.out / "summary.csv").open("w", newline="") as f:
        keys = list(summaries[0].keys())
        w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(summaries)
    delta = {k: summaries[1].get(k) - summaries[0].get(k) for k in ["adopted_local_cache_tokens", "local_compute_tokens", "query_tokens", "query_hit_tokens", "query_calls", "ttft_p95", "e2e_p95"]}
    report = args.out / "REPORT.md"
    report_text = f"""# F12-A / F12-B 同容量复用复核

本报告比较同一份冻结输入、相同 12 GiB P 侧预算下的两次运行。F12-B 只用于检验运行间差异；它不替代历史 L2/L3，也不与 F12/F24 容量对照拼成同一曲线。

## 验收

- 配对请求：{len(common)}；A/B 请求键集合一致：`{set(a)==set(b)}`。
- A 接受：`{summaries[0].get('accepted', False)}`；B 接受：`{summaries[1].get('accepted', False)}`。
- A/B 资源清理：`{summaries[0].get('cleanup_passed', False)}` / `{summaries[1].get('cleanup_passed', False)}`。

## 结果

详细逐请求差异见 `paired-requests.csv`，汇总见 `summary.csv`。正的 `delta_adopted_B_minus_A` 表示 B 最终采用更多本地缓存；发送后 TTFT 与入队至首 token 分开保存。

- B−A adopted cache token：`{delta['adopted_local_cache_tokens']}`；local compute token：`{delta['local_compute_tokens']}`。
- B−A query token：`{delta['query_tokens']}`；query hit token：`{delta['query_hit_tokens']}`；query calls：`{delta['query_calls']}`。
- B−A TTFT P95：`{delta['ttft_p95']:.6g}` s；E2E P95：`{delta['e2e_p95']:.6g}` s。

## 解释边界

两次运行均为闭环回放；即使业务输入冻结，依赖完成、客户端槽位与服务端调度仍可产生不同交错。若两次采用量接近，则本实验未发现明显的同容量运行间分歧；这不能证明历史 L2 的异常已被解释。若采用量明显不同，应把差异定位到逐请求输入、查找/采用记录和阶段时间，不能直接称为缓存实现缺陷。
"""
    report.write_text(report_text)
    print(json.dumps({"requests": len(common), "summary": str(args.out / "summary.csv"), "paired": str(paired_path)}))


if __name__ == "__main__":
    main()
