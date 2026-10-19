"""Reads key-press timing via evdev and republishes it to MQTT.

Gated by ``keystroke.enabled`` in config.yaml. Unlike the CO2 and Polar
pollers, which are inert without their hardware, this reads every key-press
event on every keyboard system-wide (any window, any app) for as long as it
runs. It can only do so if the running account is in the ``input`` group.

Privacy boundary: a raw evdev ``EV_KEY`` event carries the keycode, so the
read layer cannot avoid seeing it. ``_reduce_event`` reduces every event to
``{is_backspace, dt_ms, ts}`` before anything reaches ``client.publish`` or a
log line. No keycode for any other key crosses that boundary, and
``log.debug`` logs only the reduced dict, so ``--verbose`` cannot leak one.
Inter-key timing (``dt_ms``) is published for every key press, though, and
timing alone can carry some information about what was typed; see
SECURITY.md. ambient-context-design.md covers why this signal exists
(backspace-burst rate as a fast frustration/flow proxy).

Device discovery checks every ``/dev/input/event*`` node's ``EV_KEY``
capability bits for the alphabetic block plus spacebar (``KEY_A``..``KEY_Z``,
``KEY_SPACE``) instead of using a fixed path or device name. This rejects
lid switches, power buttons and plain hotkey devices, but not every HID
composite device: some mice advertise the full keyboard range. Such a device
is an extra idle file descriptor that never emits a backspace, so it does no
harm. ``selectors`` multiplexes reads across however many devices pass the
check, which keeps the poller synchronous.
"""
from __future__ import annotations

import argparse
import glob
import json
import logging
import selectors
import time
from pathlib import Path
from typing import Any, cast

import paho.mqtt.client as mqtt
import yaml
from evdev import InputDevice, categorize, ecodes
from evdev.events import KeyEvent
from paho.mqtt.enums import CallbackAPIVersion

from .state import now_iso

log = logging.getLogger("afferent.keystroke_poller")

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.yaml"
_RECONNECT_WAIT_S = 5
_EVENT_GLOB = "/dev/input/event*"
_KEYBOARD_CAPS = (ecodes.KEY_A, ecodes.KEY_Z, ecodes.KEY_SPACE)


def _load_config() -> dict[str, Any]:
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        return cast(dict[str, Any], yaml.safe_load(f))


def _is_keyboard(device: InputDevice[str]) -> bool:
    """A real typing keyboard exposes the alphabetic block and the
    spacebar. This rejects lid switches, power buttons and plain hotkey
    pseudo-devices, though not every non-keyboard HID interface (see the
    module docstring).
    """
    key_caps = device.capabilities().get(ecodes.EV_KEY, [])
    return all(code in key_caps for code in _KEYBOARD_CAPS)


def _discover_keyboards() -> dict[str, InputDevice[str]]:
    found: dict[str, InputDevice[str]] = {}
    for path in sorted(glob.glob(_EVENT_GLOB)):
        try:
            device = InputDevice(path)
        except OSError:
            continue
        if _is_keyboard(device):
            found[path] = device
        else:
            device.close()
    return found


def _wait_for_keyboards() -> dict[str, InputDevice[str]]:
    """Block until at least one keyboard is found, logging once per outage
    (like co2_poller and polar_poller) so a missing keyboard does not flood
    the log.
    """
    warned = False
    while True:
        found = _discover_keyboards()
        if found:
            if warned:
                log.info("keyboard(s) reappeared: %s", sorted(found))
            return found
        if not warned:
            log.warning("no keyboard found on %s -- waiting", _EVENT_GLOB)
            warned = True
        time.sleep(_RECONNECT_WAIT_S)


def _reduce_event(event: Any, dt_ms: float | None) -> dict[str, Any] | None:
    """Reduce one evdev event to the only things this project ever publishes
    about a keystroke: whether it was backspace, the gap since the previous
    press, and a timestamp. Returns None for anything that is not a key
    press; key-up and auto-repeat are dropped here so they can never reach
    a publish call.
    """
    if event.type != ecodes.EV_KEY:
        return None
    key_event = categorize(event)
    if not isinstance(key_event, KeyEvent) or key_event.keystate != KeyEvent.key_down:
        return None
    return {
        "is_backspace": key_event.scancode == ecodes.KEY_BACKSPACE,
        "dt_ms": dt_ms,
        "ts": now_iso(),
    }


def run(config: dict[str, Any]) -> None:
    topic = config["topics"]["keystroke"]
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
            time.sleep(_RECONNECT_WAIT_S)
    client.loop_start()

    last_press_monotonic: float | None = None
    try:
        while True:
            keyboards = _wait_for_keyboards()
            selector = selectors.DefaultSelector()
            for device in keyboards.values():
                selector.register(device, selectors.EVENT_READ)
            last_press_monotonic = None  # a (re)discovery breaks the dt_ms chain

            lost = False
            while not lost:
                for key, _mask in selector.select():
                    device = cast("InputDevice[str]", key.fileobj)
                    try:
                        events = list(device.read())
                    except OSError:
                        log.warning(
                            "lost connection to keyboard %s, rediscovering",
                            device.path,
                        )
                        lost = True
                        break
                    for event in events:
                        now_m = time.monotonic()
                        dt_ms: float | None = (
                            (now_m - last_press_monotonic) * 1000
                            if last_press_monotonic is not None
                            else None
                        )
                        reduced = _reduce_event(event, dt_ms)
                        if reduced is None:
                            continue
                        last_press_monotonic = now_m
                        client.publish(topic, json.dumps(reduced), qos=0)
                        log.debug("published %s", reduced)
            selector.close()
            for device in keyboards.values():
                device.close()
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
    config = _load_config()
    if not config["keystroke"]["enabled"]:
        log.info("keystroke signal disabled (keystroke.enabled: false) -- exiting")
        return
    log.warning(
        "reading /dev/input directly: this account's `input` group "
        "membership grants raw keyboard read to every process it runs, not "
        "just this one; see SECURITY.md"
    )
    run(config)


if __name__ == "__main__":
    main()
