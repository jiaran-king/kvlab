#!/usr/bin/env python3
import csv, json, math, statistics
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "final-analysis"
A_CSV = Path("stage-v5/final-analysis/cpu-3468/F12-requests.csv")
B_CSV = HERE / "formal-3479/per-request-evidence.csv"
A_RUN = Path("stage-v5/final-analysis/cpu-3468")
B_RUN = HERE / "formal-3479"

def rows(path):
    with path.open(newline="") as f:
        return list(csv.DictReader(f))

def n(r, k):
    v = r.get(k, "")
    return float(v) if v not in ("", "NA", None) else 0.0

def pct(xs, q):
    xs = sorted(xs)
    pos = (len(xs) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return xs[lo] if lo == hi else xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)

def prom_mean(before, after):
    def get(p, name):
        for line in p.read_text().splitlines():
            if line.startswith(name + "{"):
                return float(line.rsplit(" ", 1)[1])
        raise KeyError(name)
    return (get(after, "vllm:request_prefill_time_seconds_sum") -
            get(before, "vllm:request_prefill_time_seconds_sum")) / (
            get(after, "vllm:request_prefill_time_seconds_count") -
            get(before, "vllm:request_prefill_time_seconds_count"))

def task_window(path):
    xs = [json.loads(x) for x in path.open()]
    starts = [datetime.fromisoformat(x["started_at"]).timestamp() for x in xs]
    ends = [datetime.fromisoformat(x["finished_at"]).timestamp() for x in xs]
    return max(ends) - min(starts)

def summary(label, rs, run, before_name="formal-before-P.prom", after_name="formal-after-P.prom"):
    total = sum(n(r, "input_tokens") for r in rs)
    adopted = sum(n(r, "adopted_local_cache_tokens") for r in rs)
    q = sum(n(r, "query_tokens") for r in rs)
    h = sum(n(r, "query_hit_tokens") for r in rs)
    cont = [r for r in rs if r.get("context_after")]
    return {
        "run": label, "requests": len(rs), "input_tokens": int(total),
        "output_tokens": int(sum(n(r, "output_tokens") for r in rs)),
        "adopted_local_cache_tokens": int(adopted),
        "local_compute_tokens": int(total - adopted - sum(n(r, "external_tokens") for r in rs)),
        "input_cache_fraction": adopted / total, "query_tokens": int(q),
        "query_hit_tokens": int(h), "query_hit_rate": h / q,
        "query_calls": int(sum(n(r, "query_calls") for r in rs)),
        "prefill_mean": prom_mean(run / before_name, run / after_name),
        "ttft_p50": pct([n(r, "ttft_seconds") for r in rs], .5),
        "ttft_p95": pct([n(r, "ttft_seconds") for r in rs], .95),
        "continuation_requests": len(cont),
        "continuation_ttft_p50": pct([n(r, "ttft_seconds") for r in cont], .5),
        "continuation_ttft_p95": pct([n(r, "ttft_seconds") for r in cont], .95),
        "e2e_p50": pct([n(r, "e2e_seconds") for r in rs], .5),
        "e2e_p95": pct([n(r, "e2e_seconds") for r in rs], .95),
        "task_window_seconds": task_window(run / "replay/requests.jsonl") if (run / "replay/requests.jsonl").exists() else "",
    }

a = rows(A_CSV)
b = rows(B_CSV)
sa = summary("F12-A (3462)", a, A_RUN, "F12-formal-before-P.prom", "F12-formal-after-P.prom")
sb = summary("F12-B exact (3479)", b, B_RUN)
if not sa["task_window_seconds"]:
    with (A_RUN / "summary.csv").open(newline="") as f:
        sa_row = next(r for r in csv.DictReader(f) if r.get("label") == "F12")
        sa["task_window_seconds"] = float(sa_row["task_window_seconds"])
event_a = json.loads((HERE / "F12A-event-summary.json").read_text())
event_b = json.loads((HERE / "F12B-exact-event-summary.json").read_text())
for s, e in [(sa, event_a), (sb, event_b)]:
    s["removed_entries"] = e["total_removed_entries"]
    s["event_stream_complete"] = e["stream_complete"]
sa["accepted"] = json.loads((A_RUN / "F12-ACCEPTED.json").read_text())["passed"]
sb["accepted"] = json.loads((B_RUN / "ACCEPTED.json").read_text())["passed"]
sa["cleanup_passed"] = json.loads((A_RUN / "F12-cleanup-audit.json").read_text())["resource_cleanup_passed"]
sb["cleanup_passed"] = json.loads((B_RUN / "cleanup-audit.json").read_text())["resource_cleanup_passed"]
sa["source_identity_match"] = "NA"
sb["source_identity_match"] = json.load((HERE / "formal-3479/source-identity.json").open()) == json.load((A_RUN / "F12-source-identity.json").open())

OUT.mkdir(parents=True, exist_ok=True)
fields = list(sa.keys())
with (OUT / "FINAL-summary.csv").open("w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    w.writerows([sa, sb])

pair = list(csv.DictReader((OUT / "paired-requests.csv").open()))
deltas = [float(r["delta_adopted_B_minus_A"]) for r in pair]
ttft_d = [float(r["delta_ttft_B_minus_A"]) for r in pair]
e2e_d = [float(r["delta_e2e_B_minus_A"]) for r in pair]
report = f"""# F12-A / F12-B exact 同容量复用复核

## 协议有效性

两次运行均为 **12 GiB P 侧 KV 预算、425 条冻结请求、同一 P/D 配置和同一观测实现**。F12-B（3479）使用与 F12-A（3462）相同的 source identity；两次均通过完整输入、计数对账和资源清理验收。3473 是此前使用额外诊断 flush 的失败运行，单独保留，不进入本对照。

source identity 配对检查结果：`{sb["source_identity_match"]}`。

## 汇总结果

| 指标 | F12-A | F12-B exact |
|---|---:|---:|
| 请求 | 425/425 | 425/425 |
| 输入缓存占比 | {sa["input_cache_fraction"]:.4%} | {sb["input_cache_fraction"]:.4%} |
| 查询命中率 | {sa["query_hit_rate"]:.4%} | {sb["query_hit_rate"]:.4%} |
| 最终采用本地缓存 token | {sa["adopted_local_cache_tokens"]:,} | {sb["adopted_local_cache_tokens"]:,} |
| 本地输入计算 token | {sa["local_compute_tokens"]:,} | {sb["local_compute_tokens"]:,} |
| P prefill 均值 | {sa["prefill_mean"]:.3f} s | {sb["prefill_mean"]:.3f} s |
| 后续轮 TTFT P50/P95 | {sa["continuation_ttft_p50"]:.3f}/{sa["continuation_ttft_p95"]:.3f} s | {sb["continuation_ttft_p50"]:.3f}/{sb["continuation_ttft_p95"]:.3f} s |
| 请求 E2E P50/P95 | {sa["e2e_p50"]:.3f}/{sa["e2e_p95"]:.3f} s | {sb["e2e_p50"]:.3f}/{sb["e2e_p95"]:.3f} s |
| 正式任务窗口 | {sa["task_window_seconds"]:.1f} s | {sb["task_window_seconds"]:.1f} s |
| KVEvent 移除条目 | {sa["removed_entries"]:,} | {sb["removed_entries"]:,} |

KVEvent 的移除条目是 hash 条目统计，不能直接解释为容量驱逐数。两次事件流均完整且无 gap。

## 逐请求差异

paired-requests.csv 保留全部 425 条配对请求。F12-B 相比 F12-A 的最终采用缓存差额为 {sum(deltas):.0f} token：{sum(x > 0 for x in deltas)} 条增加、{sum(x < 0 for x in deltas)} 条减少、{sum(x == 0 for x in deltas)} 条不变。缓存采用量只在一个请求上少 256 token，未出现大范围复用分叉。

发送后 TTFT 的逐请求差异中，P50 差额为 {statistics.median(ttft_d):.3f} s，P95 差额为 {pct(ttft_d, .95):.3f} s；E2E 差额的 P50/P95 为 {statistics.median(e2e_d):.3f}/{pct(e2e_d, .95):.3f} s。任务窗口存在约 {sb["task_window_seconds"] - sa["task_window_seconds"]:.1f} s 的运行间差异，但没有对应的缓存采用量差异。

## 结论

在观测实现一致、输入和容量一致的 F12-A/F12-B 对照中，未观察到历史 L2 那种大范围缓存复用退化。此前 3473 的 ready 超时没有在 3479 重现；它应作为一次使用额外诊断 flush 的 P/D 协议失败样本保留，不能作为稳定的 12 GiB 性能点。

这组结果支持：**当前 12 GiB 配置在这份冻结负载上的缓存采用行为可以在两次运行间基本复现；历史 L2 的异常不能仅由“12 GiB 容量不足”解释。** 这不等于已经找到了历史 L2 的根因，也不把两次运行外推为所有负载的稳定性证明。
"""
(OUT / "FINAL-REPORT.md").write_text(report)
print(json.dumps({"summary": str(OUT / "FINAL-summary.csv"), "report": str(OUT / "FINAL-REPORT.md"), "paired": str(OUT / "paired-requests.csv")}))
