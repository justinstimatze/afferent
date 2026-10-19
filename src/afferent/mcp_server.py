"""MCP server exposing live session state to Claude Code (or any MCP client).

Reads the aggregator's on-disk JSON snapshot (state.py's ``snapshot_path()``,
written by ``aggregator.py``) rather than holding its own MQTT subscription --
this gives the MCP server and any external reader (such as a prompt hook) one
shared freshness contract, and a local file read is fast enough that a live
subscription would add nothing.

The tool surface here is the contract -- pollers/aggregator can be swapped
out without changing what the agent sees. Policy (gating, bucketing, fusion
rules) lives in aggregator.py; this module only loads the already-derived
state and shapes it into the three tool responses.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import yaml
from fastmcp import FastMCP

from .state import snapshot_path

log = logging.getLogger("afferent.mcp_server")

mcp = FastMCP("afferent")

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.yaml"
_RAW_BIOMETRIC_FIELDS = ("hr_bpm", "hrv_rmssd_ms")

_NO_DATA = (
    None,
    "no data yet (aggregator not running or has not published)",
    False,
)


def _load_config() -> dict[str, Any]:
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        return cast(dict[str, Any], yaml.safe_load(f))


def _read_state() -> tuple[dict[str, Any] | None, str, bool]:
    """Returns (state-or-None, data_source marker, is_fresh).

    Any failure beyond a simply-missing snapshot (corrupt JSON, an
    unreadable file, a malformed timestamp, a broken config.yaml) is
    reported the same as "no data yet" -- the detail is logged locally
    rather than returned, since fastmcp's default (mask_error_details=False)
    would otherwise pass raw exception text -- including local paths --
    straight through to whatever calls this tool.
    """
    try:
        raw = snapshot_path().read_text(encoding="utf-8")
    except FileNotFoundError:
        return _NO_DATA
    except OSError as e:
        log.warning("could not read state snapshot: %s", e)
        return _NO_DATA
    try:
        payload: dict[str, Any] = json.loads(raw)
        stale_after_s = _load_config()["aggregator"]["stale_after_seconds"]
        ts = datetime.fromisoformat(payload["timestamp"])
    except (json.JSONDecodeError, KeyError, ValueError, OSError) as e:
        log.warning("could not parse state snapshot or config: %s", e)
        return _NO_DATA
    age_s = (datetime.now(UTC) - ts).total_seconds()
    if age_s > stale_after_s:
        return payload, f"stale (aggregator last seen {age_s:.0f}s ago)", False
    return payload, "live (aggregator)", True


def _apply_biometric_policy(
    state: dict[str, Any], expose_raw_biometrics: bool
) -> dict[str, Any]:
    """Strips the raw ``hr_bpm``/``hrv_rmssd_ms`` fields when the config says
    not to expose them (``mcp.expose_raw_biometrics: false``). Pure, so this
    is table-tested directly rather than through the MCP tool wrapper.
    """
    if expose_raw_biometrics:
        return state
    return {k: v for k, v in state.items() if k not in _RAW_BIOMETRIC_FIELDS}


@mcp.tool()
def get_session_state() -> dict[str, Any]:
    """Current merged user state: HRV, posture, focus, activity, session minutes.

    Returns a flat dict the agent can use directly. Use this before deciding
    whether to escalate, fan out subagents, or suggest a break. Includes
    ``factors`` -- the short tags (e.g. "co2_high", "hrv_below_baseline",
    "hrv_low_confidence", "backspace_elevated") that actually contributed to
    the buckets/label above, so you can see *why* rather than only trusting
    the verdict. ``keystroke_bucket``/``backspace_rate_per_min`` are the fast
    counterpart to HRV's slow signal -- "unknown" until the keystroke poller
    is running and has recent data.

    ``hr_bpm``/``hrv_rmssd_ms`` (the raw figures behind ``hrv_bucket``) are
    included unless ``config.yaml``'s ``mcp.expose_raw_biometrics`` is set to
    false, in which case only the buckets are returned.
    """
    state, data_source, _ = _read_state()
    if state is None:
        return {"data_source": data_source}
    expose_raw = _load_config()["mcp"]["expose_raw_biometrics"]
    return {**_apply_biometric_policy(state, expose_raw), "data_source": data_source}


@mcp.tool()
def get_focus_window() -> dict[str, Any]:
    """Estimate of how much longer HRV is likely to stay near this daypart's
    baseline before the fatigue threshold, given the current trend.

    This is an HRV-recovery estimate, not a measure of attention -- "focused"
    means only "RMSSD not below baseline right now," so a high number here is
    not evidence the person is engaged with the task, only that their nervous
    system isn't showing the specific stress signature this metric tracks.
    Returns minutes remaining and confidence. Useful as one input (not the
    only one) when sizing subagent fanouts or deciding whether a long task is
    worth starting now.
    """
    state, data_source, is_fresh = _read_state()
    if state is None:
        return {
            "minutes_remaining": None,
            "confidence": "none (no data yet)",
            "current_focus_label": "unknown",
            "data_source": data_source,
        }
    focus_label = state["focus_label"]
    session_minutes = state["session_minutes"]
    if focus_label == "focused":
        remaining = max(0.0, 90 - session_minutes)
    elif focus_label == "warming":
        remaining = 75.0
    else:
        remaining = 0.0
    return {
        "minutes_remaining": round(remaining, 1),
        "confidence": "moderate" if is_fresh else "low (stale)",
        "current_focus_label": focus_label,
        "data_source": data_source,
    }


@mcp.tool()
def suggest_intervention() -> dict[str, Any]:
    """Return the current recommended intervention, if any. Use sparingly --
    the user does not want to be nagged. Only surface this when the user asks
    'how am I doing' or when state is clearly degraded.
    """
    state, data_source, _ = _read_state()
    if state is None:
        return {
            "intervention": None,
            "reason": "no data yet",
            "data_source": data_source,
        }
    minutes = round(state["session_minutes"], 1)
    return {
        "intervention": state["suggested_intervention"],
        "reason": (
            f"focus={state['focus_label']}, co2={state['co2_ppm']}, minutes={minutes}"
        ),
        "data_source": data_source,
    }


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    mcp.run()


if __name__ == "__main__":
    main()
