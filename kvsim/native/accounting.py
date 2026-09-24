"""Completed local input positions; independent of cache query statistics."""


def scheduled_input_interval(post_schedule_tokens: int, scheduled_tokens: int,
                             input_tokens: int) -> tuple[int, int]:
    # Pinned Scheduler._update_after_schedule has already advanced the cursor.
    start = post_schedule_tokens - scheduled_tokens
    if start < 0:
        raise ValueError("native post-schedule cursor precedes scheduled batch")
    return min(start, input_tokens), min(post_schedule_tokens, input_tokens)


def completed_input_totals(intervals: list[dict]) -> dict:
    total = sum(item["end"] - item["start"] for item in intervals)
    union = 0
    boundary = 0
    for item in sorted(intervals, key=lambda row: (row["start"], row["end"])):
        union += max(0, item["end"] - max(boundary, item["start"]))
        boundary = max(boundary, item["end"])
    return {"cumulative_input_processing_tokens": total,
            "unique_local_input_tokens": union,
            "repeated_local_input_tokens": total - union}
