"""Streams the Polar Verity Sense's HR + PPI over BLE and republishes to MQTT.

Uses the third-party ``polar-python`` library (bleak-based) for the BLE
connection and PMD protocol parsing, rather than reimplementing Polar's
proprietary binary framing here.

Two topics, matching the raw-event-per-sensor pattern the CO2 poller uses:

- ``topics.polar_hr`` -- standard Bluetooth HR service readings (bpm + RR).
- ``topics.polar_hrv`` -- raw PPI samples (interval, error estimate, skin
  contact / blocker flags) -- the ingredient the aggregator will turn into an
  RMSSD statistic (v3), not a computed HRV number itself. Gate on
  ``invalid`` and ``skin_contact`` downstream rather than trusting every
  sample -- see sensor-hardware.md on why a single bad interval costs more
  than per-sample jitter.

The device is found by a BLE advertised-name filter, not a fixed MAC
address, matching the CO2 poller's find-by-identity-not-by-path approach.
The filter must match only the Verity Sense ("Polar Sense ..."), never the
H10 ("Polar H10 ...") that a sibling project already owns exclusively -- see
sensor-hardware.md on why two pollers must never both hold a direct
connection to the same strap.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path
from typing import Any, cast

import paho.mqtt.client as mqtt
import yaml
from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from paho.mqtt.enums import CallbackAPIVersion
from polar_python import PolarDevice
from polar_python.exceptions import PolarPythonError
from polar_python.models import HRData, PPIData

from .state import now_iso

log = logging.getLogger("afferent.polar_poller")

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.yaml"
_SCAN_TIMEOUT_S = 10
_RECONNECT_WAIT_S = 5
_LIVENESS_POLL_S = 5


def _load_config() -> dict[str, Any]:
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        return cast(dict[str, Any], yaml.safe_load(f))


def _hr_reading(data: HRData) -> dict[str, Any]:
    return {
        "hr_bpm": data.heartrate,
        "rr_intervals_ms": data.rr_intervals,
        "ts": now_iso(),
    }


def _ppi_readings(data: PPIData) -> list[dict[str, Any]]:
    return [
        {
            "ppi_ms": sample.ppi,
            "error_estimate_ms": sample.error_estimate,
            "hr_bpm": sample.hr,
            "invalid": sample.invalid_ppi,
            "skin_contact": sample.skin_contact_status,
            "skin_contact_supported": sample.skin_contact_supported,
            "ts": now_iso(),
        }
        for sample in data.samples
    ]


async def _find_device(name_filter: str) -> BLEDevice:
    """Block until a device whose name contains ``name_filter`` is seen.

    Logs once per found/lost transition, not per scan attempt -- matches
    the CO2 poller's ``_open_serial`` so an unplugged/out-of-range sensor
    doesn't turn into a log flood.
    """
    warned = False
    while True:
        device = await BleakScanner.find_device_by_filter(
            lambda bd, _adv: bd.name is not None and name_filter in bd.name,
            timeout=_SCAN_TIMEOUT_S,
        )
        if device is not None:
            if warned:
                log.info("Polar Verity Sense reappeared as %s", device.name)
            return device
        if not warned:
            log.warning(
                "Polar Verity Sense not found (name contains %r) -- waiting",
                name_filter,
            )
            warned = True
        await asyncio.sleep(_RECONNECT_WAIT_S)


async def _stream_once(
    device: BLEDevice, client: mqtt.Client, topics: dict[str, str]
) -> None:
    async with PolarDevice(device) as polar:

        def hr_callback(data: HRData) -> None:
            client.publish(topics["polar_hr"], json.dumps(_hr_reading(data)), qos=0)
            log.debug("published hr %s", data)

        def ppi_callback(data: PPIData) -> None:
            for reading in _ppi_readings(data):
                client.publish(topics["polar_hrv"], json.dumps(reading), qos=0)
            log.debug("published %d ppi sample(s)", len(data.samples))

        await polar.start_hr_stream(hr_callback=hr_callback)
        await polar.start_ppi_stream(ppi_callback=ppi_callback)
        log.info("streaming from %s", device.name)

        # polar-python exposes no public disconnected-callback hook, so the
        # only way to notice a mid-stream drop is to poll the BleakClient it
        # wraps directly (that client's own is_connected is public bleak API,
        # even though PolarDevice stores it on a leading-underscore attr).
        while polar._client.is_connected:
            await asyncio.sleep(_LIVENESS_POLL_S)
    log.warning("lost BLE connection to Polar Verity Sense, reconnecting")


async def run_async(config: dict[str, Any]) -> None:
    name_filter = config["polar_sensor"]["device_name_filter"]
    topics = config["topics"]
    broker = config["broker"]

    client = mqtt.Client(CallbackAPIVersion.VERSION2)
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    while True:
        try:
            client.connect(broker["host"], broker["port"])
            break
        except OSError:
            log.warning(
                "MQTT broker unreachable at %s:%s, retrying",
                broker["host"], broker["port"],
            )
            await asyncio.sleep(_RECONNECT_WAIT_S)
    client.loop_start()

    try:
        while True:
            device = await _find_device(name_filter)
            try:
                await _stream_once(device, client, topics)
            except (BleakError, PolarPythonError, OSError, EOFError):
                log.warning(
                    "Polar stream dropped unexpectedly, reconnecting",
                    exc_info=True,
                )
    finally:
        client.disconnect()
        client.loop_stop()


def run(config: dict[str, Any]) -> None:
    asyncio.run(run_async(config))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # --verbose controls this module's own log level, not bleak's. Left
    # unset, bleak's DEBUG logging dumps every D-Bus property-changed
    # signal verbatim -- paired-device MACs, the adapter address, this
    # device's serial/model strings -- none of which --verbose here is
    # meant to opt into.
    logging.getLogger("bleak").setLevel(logging.INFO)
    run(_load_config())


if __name__ == "__main__":
    main()
