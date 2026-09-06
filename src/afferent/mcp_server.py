"""MCP server exposing live session state to Claude Code (or any MCP client).

v0: mock mode only. Real MQTT subscriptions land in v3 once the aggregator is
shipped. The tool surface here is the contract — pollers/aggregator can be
swapped out without changing what the agent sees.
"""
from __future__ import annotations

import random
from typing import Any

from fastmcp import FastMCP

from .state import SessionState, now_iso

mcp = FastMCP("afferent")

# v0 has no real sensor wired to this server yet -- every number below is
# random.uniform, not a measurement. Every tool return carries this marker
# explicitly in the payload (not just a docstring) so the agent can't mistake
# fabricated vitals for a real reading. Drop this once v3's real pollers +
# aggregator are wired in.
_DATA_SOURCE = "mock (v0, no real sensors wired yet)"

_MOCK_FOCUS = ["warming", "focused", "focused", "scattered", "fatigued"]
_MOCK_POSTURE = ["upright", "upright", "drifting", "slumped", "absent"]
_MOCK_ACTIVITY = ["typing", "typing", "talking", "idle", "away"]


def _mock_state() -> SessionState:
    return SessionState(
        timestamp=now_iso(),
        session_minutes=random.uniform(0, 120),
        hr_bpm=random.uniform(58, 82),
        hrv_rmssd_ms=random.uniform(20, 70),
        focus_label=random.choice(_MOCK_FOCUS),
        posture_label=random.choice(_MOCK_POSTURE),
        activity_label=random.choice(_MOCK_ACTIVITY),
        suggested_intervention=None,
    )


def _intervention_for(state: SessionState) -> str | None:
    if state.posture_label == "slumped" and state.session_minutes > 15:
        return "stand and reset posture for 60 seconds"
    if state.focus_label == "fatigued" and state.session_minutes > 90:
        return "take a 10 minute break out of headset"
    if state.focus_label == "scattered" and state.activity_label == "idle":
        return "surface queued work or context-switch deliberately"
    return None


@mcp.tool()
def get_session_state() -> dict[str, Any]:
    """Current merged user state: HRV, posture, focus, activity, session minutes.

    Returns a flat dict the agent can use directly. Use this before deciding
    whether to escalate, fan out subagents, or suggest a break.
    """
    state = _mock_state()
    state.suggested_intervention = _intervention_for(state)
    return {**state.to_dict(), "data_source": _DATA_SOURCE}


@mcp.tool()
def get_focus_window() -> dict[str, Any]:
    """Estimate of how much focused-work time is likely remaining in this session.

    Returns minutes remaining and confidence. Use this to size subagent fanouts
    and to decide whether a long task is worth starting now.
    """
    state = _mock_state()
    if state.focus_label == "focused":
        remaining = max(0, 90 - state.session_minutes)
    elif state.focus_label == "warming":
        remaining = 75
    else:
        remaining = 0
    return {
        "minutes_remaining": round(remaining, 1),
        "confidence": "low (mock)",
        "current_focus_label": state.focus_label,
        "data_source": _DATA_SOURCE,
    }


@mcp.tool()
def suggest_intervention() -> dict[str, Any]:
    """Return the current recommended intervention, if any. Use sparingly —
    the user does not want to be nagged. Only surface this when the user asks
    'how am I doing' or when state is clearly degraded.
    """
    state = _mock_state()
    intervention = _intervention_for(state)
    minutes = round(state.session_minutes, 1)
    return {
        "intervention": intervention,
        "reason": (
            f"focus={state.focus_label}, posture={state.posture_label}, "
            f"minutes={minutes}"
        ),
        "data_source": _DATA_SOURCE,
    }


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
