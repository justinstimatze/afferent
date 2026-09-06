from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
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
    focus_label: str          # warming|focused|scattered|fatigued|unknown
    posture_label: str        # upright|drifting|slumped|absent|unknown
    activity_label: str       # "typing" | "talking" | "idle" | "away" | "unknown"
    suggested_intervention: str | None  # null if none

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()
