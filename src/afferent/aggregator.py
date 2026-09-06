"""Turns raw sensor MQTT streams into a single derived SessionState.

Subscribes to ``sensors/co2``, ``sensors/polar/hr`` and ``sensors/polar/hrv``,
maintains rolling buffers, and on a fixed tick computes and republishes a
merged, privacy-respecting SessionState -- the ingredient the MCP server
(pull) and headrace's sensor signal (push, outside this repo) both read,
per ambient-context-design.md's dual-sink design.

Muse/webcam are not wired in yet (deferred), so ``posture_label`` and
``activity_label`` always report "unknown" here -- never fabricated.

Fusion note (see ambient-context-design.md "Fuse for confidence"): HR and HRV
are not independent channels -- both come off the same PPI stream -- so the
two-channel-agreement rule for escalating to an intervention has no real
instance yet with only these two sensors live. CO2 is treated as a
single-channel exception because the design doc itself calls it uniquely
low-noise and actionable ("CO2 1400, crack a window"); HRV/posture-driven
interventions stay ``None`` until a second independent channel (webcam)
exists.

The HRV baseline is a per-process-run simplification, not a persisted
long-term baseline: the first clean RMSSD window at or after
``hrv_baseline_minutes`` becomes ``_baseline_rmssd`` for the rest of that run.
A restart forgets it, and a bad first few minutes (already-stressed start)
skews every later comparison for that run. A real fix needs a persisted,
multi-day baseline, which is out of scope here.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, cast

import numpy as np
import paho.mqtt.client as mqtt
import yaml
from paho.mqtt.enums import CallbackAPIVersion

from .state import SessionState, now_iso, snapshot_path

log = logging.getLogger("afferent.aggregator")

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.yaml"
_RECONNECT_WAIT_S = 5

# Plausible-range bounds for untrusted MQTT payloads. The broker is
# loopback-only but allow_anonymous -- any local process that reaches it can
# publish to sensors/*, and an out-of-range or wrong-type value must be
# dropped rather than crash tick() (a TypeError/KeyError here previously
# could kill the whole aggregator process from one bad message).
_CO2_MIN, _CO2_MAX = 200, 10000
_HR_MIN, _HR_MAX = 20, 250
_PPI_MIN, _PPI_MAX = 200, 2500

_last_validation_warning = 0.0
_VALIDATION_WARNING_INTERVAL_S = 5.0


def _validation_warning(msg: str, *args: Any) -> None:
    """Throttled like co2_poller's own parse-warning: a flood of bad
    payloads must not become a log-flood in its own right."""
    global _last_validation_warning
    now = time.monotonic()
    if now - _last_validation_warning >= _VALIDATION_WARNING_INTERVAL_S:
        log.warning(msg, *args)
        _last_validation_warning = now


def _plausible(value: Any, lo: float, hi: float) -> bool:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    return lo <= value <= hi


def _load_config() -> dict[str, Any]:
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        return cast(dict[str, Any], yaml.safe_load(f))


def _write_snapshot(path: Path, payload: dict[str, Any]) -> None:
    """Write-to-tmp-then-replace so no reader ever observes a torn write.

    Directory and file are locked owner-only (0700/0600) on every write, not
    just at creation -- this snapshot carries derived biometric/environmental
    state and must not be group- or world-readable on a multi-user host. The
    chmod runs unconditionally (not just when the directory is newly created)
    so a pre-existing directory with looser permissions gets tightened too.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def _gate_ppi_sample(sample: dict[str, Any]) -> bool:
    """True if a PPI sample is clean enough to feed RMSSD.

    Drops (never imputes) any sample flagged invalid or lacking skin
    contact -- sensor-hardware.md: a single bad interval dominates RMSSD
    more than the ordinary per-sample jitter does.
    """
    return not sample.get("invalid", True) and bool(sample.get("skin_contact", False))


def _rmssd(
    clean_ppi_ms: list[float], gated_count: int, max_gated_fraction: float
) -> float | None:
    """RMSSD over already-gated, time-windowed PPI intervals.

    None if too large a fraction of the raw window was gated out
    (sensor-hardware.md: discard such windows rather than compute on them),
    or if fewer than 2 clean intervals survive to difference.
    """
    total = len(clean_ppi_ms) + gated_count
    if total > 0 and gated_count / total > max_gated_fraction:
        return None
    if len(clean_ppi_ms) < 2:
        return None
    diffs = np.diff(np.array(clean_ppi_ms, dtype=float))
    return float(np.sqrt(np.mean(diffs**2)))


def _co2_bucket(ppm: int, elevated: int, high: int) -> str:
    if ppm >= high:
        return "high"
    if ppm >= elevated:
        return "approaching"
    return "normal"


def _hrv_bucket(rmssd: float | None, baseline: float | None, drop_pct: float) -> str:
    if baseline is None:
        return "warming"
    if rmssd is None or baseline <= 0:
        return "insufficient data"
    drop = (baseline - rmssd) / baseline * 100
    return "below baseline" if drop >= drop_pct else "at baseline"


def _focus_label(
    hrv_bucket: str, session_minutes: float, fatigue_minutes: float
) -> str:
    if hrv_bucket == "warming":
        return "warming"
    if hrv_bucket == "insufficient data":
        return "unknown"
    if hrv_bucket == "below baseline":
        return "fatigued" if session_minutes >= fatigue_minutes else "scattered"
    return "focused"


def _intervention_for(co2_ppm: int | None, elevated: int, high: int) -> str | None:
    if co2_ppm is not None and _co2_bucket(co2_ppm, elevated, high) == "high":
        return "crack a window"
    return None


def _factors(
    co2_bucket: str,
    hrv_bucket: str,
    session_minutes: float,
    fatigue_minutes: float,
    gated_fraction: float | None,
    low_confidence_gated_fraction: float,
) -> list[str]:
    """Which primitives contributed to this tick's buckets/label, as short
    machine-readable tags -- e.g. so a consumer can see *why* focus_label is
    "fatigued" instead of only trusting the label. Derived independently from
    the same primitives _focus_label/_co2_bucket/_hrv_bucket already use, so
    the two can never silently disagree.

    hrv_low_confidence fires below the hard RMSSD-discard cutoff
    (rmssd_max_gated_fraction) -- it flags the warning zone where RMSSD is
    still computed but built on a large-ish gated fraction, so a consumer can
    discount a "below baseline" reading that's actually thin data.
    """
    factors: list[str] = []
    if co2_bucket == "approaching":
        factors.append("co2_approaching")
    elif co2_bucket == "high":
        factors.append("co2_high")
    if hrv_bucket == "below baseline":
        factors.append("hrv_below_baseline")
    elif hrv_bucket == "warming":
        factors.append("hrv_warming")
    if session_minutes >= fatigue_minutes:
        factors.append("session_over_fatigue_threshold")
    if gated_fraction is not None and gated_fraction >= low_confidence_gated_fraction:
        factors.append("hrv_low_confidence")
    return factors


def _session_minutes(start_monotonic: float, now_monotonic: float) -> float:
    return (now_monotonic - start_monotonic) / 60


class _Aggregator:
    """Holds the rolling buffers between MQTT callbacks and tick() calls."""

    def __init__(self, config: dict[str, Any]) -> None:
        self._topics: dict[str, str] = config["topics"]
        self._thresholds: dict[str, Any] = config["thresholds"]
        self._agg_cfg: dict[str, Any] = config["aggregator"]
        self._session_cfg: dict[str, Any] = config["session"]

        self._start_monotonic = time.monotonic()
        self._baseline_deadline = (
            self._start_monotonic + self._agg_cfg["hrv_baseline_minutes"] * 60
        )
        self._baseline_rmssd: float | None = None

        self._latest_co2: int | None = None
        self._latest_hr: float | None = None
        # (monotonic_ts, ppi_ms) for clean samples, (monotonic_ts, None) for
        # gated ones -- keeping both in one time-pruned buffer lets the
        # gated-fraction check apply to the same rolling window as RMSSD.
        self._ppi_events: list[tuple[float, float | None]] = []

    def on_message(
        self, _client: mqtt.Client, _userdata: Any, msg: mqtt.MQTTMessage
    ) -> None:
        try:
            payload = json.loads(msg.payload)
        except json.JSONDecodeError:
            log.warning("unparsable MQTT payload on %s, dropping", msg.topic)
            return
        if msg.topic == self._topics["co2"]:
            co2 = payload.get("co2")
            if _plausible(co2, _CO2_MIN, _CO2_MAX):
                self._latest_co2 = int(co2)
            else:
                _validation_warning("dropping implausible co2 payload: %r", payload)
        elif msg.topic == self._topics["polar_hr"]:
            hr = payload.get("hr_bpm")
            if _plausible(hr, _HR_MIN, _HR_MAX):
                self._latest_hr = float(hr)
            else:
                _validation_warning("dropping implausible hr payload: %r", payload)
        elif msg.topic == self._topics["polar_hrv"]:
            ts = time.monotonic()
            ppi = payload.get("ppi_ms")
            if _gate_ppi_sample(payload) and _plausible(ppi, _PPI_MIN, _PPI_MAX):
                self._ppi_events.append((ts, float(ppi)))
            else:
                if _gate_ppi_sample(payload):
                    _validation_warning("dropping implausible ppi payload: %r", payload)
                self._ppi_events.append((ts, None))

    def _prune_ppi(self, window_s: float) -> None:
        cutoff = time.monotonic() - window_s
        self._ppi_events = [(t, v) for t, v in self._ppi_events if t >= cutoff]

    def tick(self) -> SessionState:
        window_s = self._agg_cfg["rmssd_window_minutes"] * 60
        self._prune_ppi(window_s)
        clean = [v for _, v in self._ppi_events if v is not None]
        gated = sum(1 for _, v in self._ppi_events if v is None)
        rmssd = _rmssd(clean, gated, self._agg_cfg["rmssd_max_gated_fraction"])

        now_m = time.monotonic()
        if (
            self._baseline_rmssd is None
            and now_m >= self._baseline_deadline
            and rmssd is not None
        ):
            self._baseline_rmssd = rmssd
            log.info("HRV baseline established: %.1fms", rmssd)

        drop_pct = self._thresholds["hrv_scattered_rmssd_drop_pct"]
        hrv_bucket = _hrv_bucket(rmssd, self._baseline_rmssd, drop_pct)
        session_minutes = _session_minutes(self._start_monotonic, now_m)
        focus_label = _focus_label(
            hrv_bucket, session_minutes, self._session_cfg["fatigue_minutes"]
        )
        co2_elevated = self._thresholds["co2_ppm_elevated"]
        co2_high = self._thresholds["co2_ppm_high"]
        co2_bucket = (
            _co2_bucket(self._latest_co2, co2_elevated, co2_high)
            if self._latest_co2 is not None
            else "unknown"
        )
        intervention = _intervention_for(self._latest_co2, co2_elevated, co2_high)

        total_ppi = len(clean) + gated
        gated_fraction = gated / total_ppi if total_ppi > 0 else None
        factors = _factors(
            co2_bucket,
            hrv_bucket,
            session_minutes,
            self._session_cfg["fatigue_minutes"],
            gated_fraction,
            self._thresholds["hrv_low_confidence_gated_fraction"],
        )

        return SessionState(
            timestamp=now_iso(),
            session_minutes=round(session_minutes, 2),
            hr_bpm=self._latest_hr,
            hrv_rmssd_ms=rmssd,
            hrv_bucket=hrv_bucket,
            co2_ppm=self._latest_co2,
            co2_bucket=co2_bucket,
            focus_label=focus_label,
            posture_label="unknown",
            activity_label="unknown",
            suggested_intervention=intervention,
            factors=factors,
        )


def run(config: dict[str, Any]) -> None:
    agg_cfg = config["aggregator"]
    topics = config["topics"]
    broker = config["broker"]
    aggregator = _Aggregator(config)

    client = mqtt.Client(CallbackAPIVersion.VERSION2)
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    client.on_message = aggregator.on_message
    while True:
        try:
            client.connect(broker["host"], broker["port"])
            break
        except OSError:
            log.warning(
                "MQTT broker unreachable at %s:%s, retrying",
                broker["host"], broker["port"],
            )
            time.sleep(_RECONNECT_WAIT_S)
    for topic in (topics["co2"], topics["polar_hr"], topics["polar_hrv"]):
        client.subscribe(topic)
    client.loop_start()

    snap_path = snapshot_path()
    tick_s = agg_cfg["tick_seconds"]
    try:
        while True:
            time.sleep(tick_s)
            state = aggregator.tick()
            payload = {**state.to_dict(), "tick_seconds": tick_s}
            client.publish(
                topics["state_current"], json.dumps(payload), qos=0, retain=True
            )
            _write_snapshot(snap_path, payload)
            log.debug("published state %s", payload)
    finally:
        client.disconnect()
        client.loop_stop()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    run(_load_config())


if __name__ == "__main__":
    main()
