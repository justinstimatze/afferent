"""Reads keyboard press timing via evdev and republishes to MQTT.

Off by default (``keystroke.enabled`` in config.yaml) -- unlike the CO2 and
Polar pollers, which are inert without their hardware plugged in, this reads
every key-press event on every physical keyboard system-wide (any window,
any app) for as long as it runs.

The non-negotiable privacy boundary: a raw evdev ``EV_KEY`` event necessarily
carries the actual keycode -- that's unavoidable at the read layer. This
module reduces every event to ``{is_backspace, dt_ms}`` in ``_reduce_event``,
*before* it ever reaches ``client.publish`` or a log line. No keycode for any
non-backspace key is allowed to cross that boundary -- ``log.debug`` below
logs the reduced dict, never the raw event, so even ``--verbose`` can't leak
one. See ambient-context-design.md's privacy design and "Live attention/load"
section for why this signal exists (backspace-burst rate as a fast,
real-time frustration/flow proxy) and README.md for where it sits on the
privacy gradient.

Device discovery reuses flock's (a public sibling project -- a small Go
program that honks a sound on every keypress system-wide) already-working
approach rather than reinventing it: check every ``/dev/input/event*``
node's ``EV_KEY`` capability bits for the alphabetic block plus spacebar
(``KEY_A``..``KEY_Z``, ``KEY_SPACE``), not a fixed path or a by-id name
filter. This rejects lid switches, power buttons, and plain hotkey devices
with only a handful of key codes -- but it is not foolproof: checked
directly on this host, a gaming mouse's auxiliary button interface still
passes (some HID composite devices advertise the full keyboard capability
range even though the physical device can never send most of those codes).
Harmless here -- an extra idle file descriptor that never actually emits a
backspace, not a double-count -- but worth stating plainly rather than
claiming a guarantee the check doesn't actually give. The same approach also
naturally supports more than one real keyboard plugged in at once:
``selectors`` (stdlib) multiplexes reads across however many devices pass the
check, mirroring flock's one-goroutine-per-device design without pulling
asyncio into an otherwise synchronous poller.
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
    spacebar -- this rejects lid switches, power buttons, and plain hotkey
    pseudo-devices, though not every non-keyboard HID interface (see this
    module's docstring on the false positive checked on this host). Same
    heuristic as flock's isKeyboard, ported from its EVIOCGBIT bit-check to
    evdev's own capabilities().
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
    """Block until at least one keyboard is found, matching co2_poller's
    ``_open_serial``/polar_poller's ``_find_device`` found/lost logging so
    a machine with no keyboard plugged in (unlikely, but same discipline)
    doesn't turn into a log flood.
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
    """Reduce one evdev event to the only two things this project ever
    publishes about a keystroke. Returns None for anything that isn't a
    key-press (key-up and auto-repeat are dropped, not just ignored
    downstream, so they can never accidentally reach a publish call).
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
        "reading /dev/input directly -- this account's `input` group "
        "membership grants raw keyboard read to every process it runs, not "
        "just this one; see SECURITY.md"
    )
    run(config)


if __name__ == "__main__":
    main()
