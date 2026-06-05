"""Pure statistical helpers for class performance analytics."""
from __future__ import annotations

import statistics
from datetime import datetime
from typing import Iterable, Optional


def _safe_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def coerce_percentages(values: Iterable) -> list[float]:
    """Coerce a heterogenous iterable of score/percentage strings to floats."""
    out: list[float] = []
    for v in values:
        f = _safe_float(v)
        if f is not None:
            out.append(f)
    return out


def compute_assignment_stats(percentages: list[float]) -> dict:
    """Mean, median, stdev, quartiles, min/max, count. All None-safe for empty input."""
    n = len(percentages)
    if n == 0:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "stdev": None,
            "q1": None,
            "q3": None,
            "min": None,
            "max": None,
        }
    sorted_vals = sorted(percentages)
    mean = statistics.fmean(sorted_vals)
    median = statistics.median(sorted_vals)
    stdev = statistics.pstdev(sorted_vals) if n > 1 else 0.0
    if n >= 4:
        q1, _, q3 = statistics.quantiles(sorted_vals, n=4, method="inclusive")
    else:
        q1 = sorted_vals[0]
        q3 = sorted_vals[-1]
    return {
        "count": n,
        "mean": round(mean, 2),
        "median": round(median, 2),
        "stdev": round(stdev, 2),
        "q1": round(q1, 2),
        "q3": round(q3, 2),
        "min": round(sorted_vals[0], 2),
        "max": round(sorted_vals[-1], 2),
    }


def compute_histogram(
    percentages: list[float], bin_size: int = 10, max_value: float = 100.0
) -> list[dict]:
    """Bucket percentages into [0-10), [10-20), ..., [90-100] inclusive of the upper edge."""
    if bin_size <= 0:
        bin_size = 10
    bucket_count = int(max_value // bin_size)
    counts = [0] * bucket_count
    for p in percentages:
        if p is None:
            continue
        idx = int(p // bin_size)
        if idx >= bucket_count:
            idx = bucket_count - 1
        if idx < 0:
            idx = 0
        counts[idx] += 1
    buckets = []
    for i, c in enumerate(counts):
        low = i * bin_size
        high = (i + 1) * bin_size
        buckets.append({"bucket": f"{low}-{high}", "count": c})
    return buckets


def compute_submission_rates(
    submitted_count: int,
    on_time_count: int,
    enrolled_count: int,
) -> tuple[float, float]:
    """Return (submission_rate, on_time_rate) as percentages 0-100."""
    if enrolled_count <= 0:
        return 0.0, 0.0
    sub = round(100.0 * submitted_count / enrolled_count, 2)
    on_time = round(100.0 * on_time_count / enrolled_count, 2)
    return sub, on_time


def is_on_time(submitted_at: Optional[datetime], due_date: Optional[datetime]) -> bool:
    """A submission is on-time if there is no due_date, or submitted_at <= due_date."""
    if submitted_at is None:
        return False
    if due_date is None:
        return True
    return submitted_at <= due_date


def normalize_weightages(
    weightages: dict, assignment_ids: list[str]
) -> dict[str, float]:
    """Normalize provided weightages over the selected assignment IDs so values sum to 1.0.

    Missing/invalid weights default to equal share of the remainder.
    """
    cleaned: dict[str, float] = {}
    for aid in assignment_ids:
        w = _safe_float(weightages.get(aid)) if isinstance(weightages, dict) else None
        if w is None or w < 0:
            w = 0.0
        cleaned[aid] = w
    total = sum(cleaned.values())
    if total <= 0:
        if not assignment_ids:
            return {}
        equal = 1.0 / len(assignment_ids)
        return {aid: equal for aid in assignment_ids}
    return {aid: w / total for aid, w in cleaned.items()}


def compute_weighted_totals(
    students: list[dict], weightages: dict[str, float]
) -> list[float]:
    """For each student dict {user_id, scores:{aid: pct|None}}, compute weighted sum.

    Missing scores are treated as 0. Returns list of percentages (0-100 scale).
    """
    totals: list[float] = []
    for s in students:
        scores = s.get("scores") or {}
        total = 0.0
        for aid, w in weightages.items():
            v = _safe_float(scores.get(aid))
            if v is None:
                v = 0.0
            total += v * w
        totals.append(round(total, 2))
    return totals
