"""Reads the SCD-41 CO2 sensor's USB-serial stream and republishes to MQTT.

The QT Py ESP32 Pico prints ``co2=NNN,temp=NN.N,rh=NN`` lines once it's
running the firmware in ``firmware/``. This process is the only
consumer of that serial stream (see ambient-context-design.md: read serial
once here, everything else -- the aggregator, the hook, the MCP server --
goes through MQTT ``sensors/co2`` instead).

The serial device is found by USB vendor:product ID rather than a fixed
path (``/dev/ttyACM1``, etc.) because that path is not stable: it depends on
what else is plugged in and the order things enumerated at boot.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import time
from pathlib import Path
from typing import Any, cast

import paho.mqtt.client as mqtt
import serial
import serial.tools.list_ports
import yaml
from paho.mqtt.enums import CallbackAPIVersion

from .state import now_iso

log = logging.getLogger("afferent.co2_poller")

# Assumes an editable install (`uv sync` / `pip install -e .`), where
# src/afferent/ sits inside a checkout that also has config.yaml at its
# root. config.yaml isn't packaged into the wheel, so a non-editable
# `pip install afferent` will not find it here.
_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.yaml"
_LINE_RE = re.compile(r"^co2=(\d+),temp=(-?\d+(?:\.\d+)?),rh=(\d+(?:\.\d+)?)$")
_RECONNECT_WAIT_S = 5


def _load_config() -> dict[str, Any]:
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        return cast(dict[str, Any], yaml.safe_load(f))


def _find_port(vid: int, pid: int) -> str | None:
    for port in serial.tools.list_ports.comports():
        if port.vid == vid and port.pid == pid:
            return port.device
    return None


def _open_serial(vid: int, pid: int, baud: int) -> serial.Serial:
    """Block until the sensor's serial port appears, then open it.

    Logs once per found/lost transition, not on every retry -- a device that
    stays unplugged for hours must not turn into a wall of repeated log lines
    that nobody reads, which is its own kind of silent failure.
    """
    warned = False
    while True:
        device = _find_port(vid, pid)
        if device is not None:
            if warned:
                log.info("CO2 sensor reappeared at %s", device)
            return serial.Serial(device, baud, timeout=2)
        if not warned:
            log.warning("CO2 sensor not found (usb %04x:%04x) -- waiting", vid, pid)
            warned = True
        time.sleep(_RECONNECT_WAIT_S)


_last_parse_warning = 0.0
_PARSE_WARNING_INTERVAL_S = 5.0


def _parse_line(line: str) -> dict[str, Any] | None:
    """Parse one sensor line, or return None and log a warning.

    Warnings are throttled rather than logged per-line: a firmware crash
    dumps a multi-line MicroPython traceback to the same serial stream, and
    without throttling that would flood the log exactly when the sensor
    already needs attention -- the same silent-flood failure _open_serial's
    found/lost throttling exists to avoid.
    """
    global _last_parse_warning
    match = _LINE_RE.match(line.strip())
    if match is None:
        if line.strip():
            now = time.monotonic()
            if now - _last_parse_warning >= _PARSE_WARNING_INTERVAL_S:
                log.warning("unparsable line from sensor, dropping: %r",
                            line.strip())
                _last_parse_warning = now
        return None
    co2, temp, rh = match.groups()
    return {"co2": int(co2), "temp": float(temp), "rh": float(rh), "ts": now_iso()}


def run(config: dict[str, Any]) -> None:
    sensor_cfg = config["co2_sensor"]
    vid, pid, baud = sensor_cfg["usb_vid"], sensor_cfg["usb_pid"], sensor_cfg["baud"]
    topic = config["topics"]["co2"]
    broker = config["broker"]

    client = mqtt.Client(CallbackAPIVersion.VERSION2)
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    # Blocking connect with our own retry, not connect_async(): readings
    # published before the async handshake completes are silently dropped
    # (paho only queues qos>0, and this publishes qos=0), so the broker must
    # actually be up before the read loop starts.
    while True:
        try:
            client.connect(broker["host"], broker["port"])
            break
        except OSError:
            log.warning("MQTT broker unreachable at %s:%s, retrying",
                        broker["host"], broker["port"])
            time.sleep(_RECONNECT_WAIT_S)
    client.loop_start()

    ser: serial.Serial | None = None
    try:
        while True:
            if ser is None:
                ser = _open_serial(vid, pid, baud)
            try:
                raw = ser.readline().decode("ascii", errors="replace")
            except (OSError, serial.SerialException):
                log.warning("lost serial connection to CO2 sensor, reopening")
                ser.close()
                ser = None
                continue
            reading = _parse_line(raw)
            if reading is not None:
                client.publish(topic, json.dumps(reading), qos=0)
                log.debug("published %s", reading)
    finally:
        client.disconnect()
        client.loop_stop()
        if ser is not None:
            ser.close()


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
