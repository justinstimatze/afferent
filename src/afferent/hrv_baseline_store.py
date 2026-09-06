"""Persisted, time-of-day-aware HRV baseline, surviving a restart.

aggregator.py's own in-run baseline (the first clean RMSSD window at or
after ``hrv_baseline_minutes``) is a per-process-run simplification: a
restart forgets it, and a session runs baseline-less (``hrv_bucket`` stuck
at "warming") for its first few minutes every time. This module gives a
fresh session an immediate *provisional* baseline instead, drawn from past
sessions at the same time of day -- HRV has a real circadian rhythm, so
"the wearer's own baseline" implicitly means "at this time of day", not one
number for the whole day (see sensor-hardware.md on why HRV can only ever
be compared to the wearer's own baseline, never a population norm).

The provisional baseline is always superseded by the session's own fresh
one once established (aggregator.py's existing logic, untouched) -- this
module only fills the gap before that happens and updates the persisted
store afterward, so the store slowly tracks reality across days rather
than freezing on day one.

Bucketing is 3-hour dayparts (8 buckets covering a full day), not exact
hours: coarse enough to accumulate real samples within days rather than
waiting weeks for one exact hour to refill, while still capturing the main
circadian shape. Each bucket keeps only the most recent ``_MAX_SAMPLES``
sessions' baselines (a plain mean, not a weighted one) -- old enough data
ages out on its own, no separate expiry logic needed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import cast

_MAX_SAMPLES_PER_BUCKET = 14


def daypart_bucket(hour: int) -> str:
    """3-hour daypart label for an hour 0-23, e.g. 14 -> "12-15"."""
    start = (hour // 3) * 3
    return f"{start:02d}-{start + 3:02d}"


def update_baseline(
    store: dict[str, list[float]], bucket: str, rmssd: float
) -> dict[str, list[float]]:
    """Returns a new store with rmssd appended to bucket, capped to the
    most recent _MAX_SAMPLES_PER_BUCKET. Pure -- does not mutate store."""
    updated = dict(store)
    samples = [*updated.get(bucket, []), rmssd]
    updated[bucket] = samples[-_MAX_SAMPLES_PER_BUCKET:]
    return updated


def baseline_for_bucket(store: dict[str, list[float]], bucket: str) -> float | None:
    """Mean of bucket's stored samples, or None if the bucket has none yet."""
    samples = store.get(bucket)
    if not samples:
        return None
    return sum(samples) / len(samples)


def load_store(path: Path) -> dict[str, list[float]]:
    """A missing or corrupt file yields an empty store -- same "degrade
    gracefully, never fabricate" discipline as every other reader here."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return cast(dict[str, list[float]], raw)


def save_store(path: Path, store: dict[str, list[float]]) -> None:
    """Write-to-tmp-then-replace, same pattern and same owner-only
    permissions as aggregator.py's _write_snapshot -- this file carries
    derived biometric data too."""
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(store), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
