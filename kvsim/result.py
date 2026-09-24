"""Reporting only: no cache lookups, mutations or inference dependencies."""

import csv
import io
import json
from pathlib import Path


def csv_text(rows):
    if not rows:
        return ""
    fields = [k for k in rows[0] if k not in ("steps", "explanation")]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v for k, v in row.items() if k in fields})
    return buf.getvalue()


def export(result, directory):
    path = Path(directory)
    path.mkdir(parents=True, exist_ok=True)
    for name, value in (("scenario.json", result["scenario"]), ("resolved_config.json", result["profile"]), ("result.json", result)):
        (path / name).write_text(json.dumps(value, ensure_ascii=False, indent=2))
    (path / "requests.csv").write_text(csv_text(result["requests"]))
    (path / "summary.csv").write_text(csv_text(result["per_p"]))
    summary = result["summary"]
    report = ["# KV cache offline simulation", "", f"Status: **{result['status']}**", "",
              "Fixed execution events; virtual ticks are not hardware latency.", "",
              f"Completed: {summary['completed']}/{summary['planned']}",
              f"Adopted cache tokens: {summary['adopted_cached_tokens']:,}",
              f"Input compute tokens: {summary['input_compute_tokens']:,}", "",
              "## Assumptions", "", *["- " + a for a in result["scenario"]["assumptions"]], "",
              result["profile"]["scope"], "", "## Per-request explanations", ""]
    if result["failure"]:
        report += [json.dumps(result["failure"], ensure_ascii=False), ""]
    for r in result["requests"]:
        if r["explanation"]:
            report.append(f"- `{r['request_id']}`: " + json.dumps(r["explanation"], ensure_ascii=False))
    (path / "REPORT.md").write_text("\n".join(report))


def compare_observed(result, observed):
    """Only the report layer can receive observed cache/compute counters."""
    by_id = {r["request_id"]: r for r in observed}
    comparisons = []
    for row in result["requests"]:
        if row["request_id"] in by_id:
            other = by_id[row["request_id"]]
            comparisons.append(dict(request_id=row["request_id"],
                cached_difference=row["adopted_cached_tokens"] - int(other["adopted_cached_tokens"]),
                compute_difference=row["input_compute_tokens"] - int(other["input_compute_tokens"])))
    return comparisons

