from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass
class SessionState:
    """Merged user state surfaced to the agent.

    Fields are intentionally flat and string-y — easy for an LLM tool call to
    consume without further parsing.
    """
    timestamp: str
    session_minutes: float
    hr_bpm: float | None
    hrv_rmssd_ms: float | None
    hrv_bucket: str           # insufficient data|warming|at baseline|below baseline
    co2_ppm: int | None
    co2_bucket: str           # unknown|normal|approaching|high
    focus_label: str          # warming|focused|scattered|fatigued|unknown
    posture_label: str        # upright|drifting|slumped|absent|unknown
    activity_label: str       # "typing" | "talking" | "idle" | "away" | "unknown"
    suggested_intervention: str | None  # null if none
    factors: list[str]        # which primitives contributed to the buckets/label
                              # above -- e.g. ["co2_high", "hrv_below_baseline"] --
                              # so a consumer can see *why*, not just the verdict.
                              # Independently derived from the same primitives as
                              # focus_label/co2_bucket/hrv_bucket, never from them.

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def snapshot_path() -> Path:
    """Where the aggregator writes its derived-state snapshot.

    XDG_STATE_HOME-aware so both the aggregator (writer) and mcp_server
    (reader) -- and, outside this repo, the `headrace` hook tool's sensor
    signal -- agree on one location without importing from each other.
    """
    state_home = os.environ.get("XDG_STATE_HOME")
    base = Path(state_home) if state_home else Path.home() / ".local" / "state"
    return base / "afferent" / "state.json"
