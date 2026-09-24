"""Derive scheduler activity counters from recorded requests and logical steps."""

from __future__ import annotations


def activity_by_p(rows: list[dict], steps: list[dict], domains: list[str]) -> dict[str, dict]:
    result = {}
    for domain in domains:
        members = [row for row in rows if row.get("p_domain", "p0") == domain]
        domain_steps = [row for row in steps if row.get("p_domain", "p0") == domain]
        result[domain] = {
            "waiting_request_steps": sum(row["waiting_before"] for row in domain_steps),
            "waiting_peak": max((row["waiting_before"] for row in domain_steps), default=0),
            "running_peak": max((len(row["running_after_schedule"]) for row in domain_steps), default=0),
            "preemptions": sum(row["preemptions"] for row in members),
            "resumes": sum(len(row["resume_steps"]) for row in members),
        }
    return result
