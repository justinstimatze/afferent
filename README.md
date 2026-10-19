# afferent

afferent reads a few sensors at your desk (a CO2 monitor, a heart-rate armband, and the timing of your typing) and turns them into a small status report that an AI coding assistant can ask for. The assistant is [Claude Code](https://claude.com/claude-code), Anthropic's terminal coding agent, and it asks through [MCP](https://modelcontextprotocol.io) (the Model Context Protocol, a standard way for an assistant to call tools that a local program provides).

The idea is to give the assistant context that a text conversation does not carry: the air in the room has gone stale, or a long session has run on with no break. It is a research toy for seeing whether that context is useful, and nothing here is validated.

## What the assistant gets

The MCP server offers three tools: `get_session_state`, `get_focus_window` and `suggest_intervention`. `get_session_state` returns the whole snapshot as flat JSON. This is the shape, from `SessionState` in `src/afferent/state.py` (the values are made up; `data_source` is added by `src/afferent/mcp_server.py`):

```json
{
  "timestamp": "2026-10-18T20:14:03.512104+00:00",
  "session_minutes": 97.4,
  "hr_bpm": 71.0,
  "hrv_rmssd_ms": 31.2,
  "hrv_bucket": "below baseline",
  "hrv_gated_fraction": 0.04,
  "co2_ppm": 1240,
  "co2_bucket": "high",
  "backspace_rate_per_min": 18.5,
  "keystroke_bucket": "elevated",
  "focus_label": "fatigued",
  "posture_label": "unknown",
  "activity_label": "unknown",
  "suggested_intervention": "crack a window",
  "factors": ["co2_high", "hrv_below_baseline", "session_over_fatigue_threshold", "backspace_elevated"],
  "tick_seconds": 15,
  "data_source": "live (aggregator)"
}
```

Terms used above:

- **HR** is heart rate in beats per minute. **HRV** (heart rate variability) describes how much the gaps between heartbeats vary. `hrv_rmssd_ms` is one common HRV number, RMSSD, in milliseconds. `hrv_bucket` compares it to your own recent baseline (`"insufficient data"`, `"warming"`, `"at baseline"` or `"below baseline"`), never to a population norm.
- **CO2** is carbon dioxide concentration in parts per million. `co2_bucket` is `"unknown"`, `"normal"`, `"approaching"` or `"high"`, using `co2_ppm_elevated` (1000) and `co2_ppm_high` (1200) in `config.yaml`.
- **Keystroke dynamics** is the timing of your typing, with no record of which keys. `backspace_rate_per_min` is how often you hit backspace over a short window, used as a rough proxy for typing trouble.
- `focus_label` (`warming`, `focused`, `scattered`, `fatigued`, `unknown`) is a label derived from the HRV bucket and session length. `"focused"` means only that HRV is at baseline. It says nothing about attention.
- `factors` lists the tags that contributed to the buckets, so the assistant can see why.
- `posture_label` and `activity_label` are always `"unknown"` for now; the webcam poller that would fill them is not built.
- `suggested_intervention` is `null` unless a rule fires. Sustained high CO2 alone gives `"crack a window"`. Any other suggestion needs two independent signals to agree: HRV below baseline plus an elevated backspace rate gives `"take a break"`. Heart rate and HRV count as one signal because they come from the same sensor stream.

With `mcp.expose_raw_biometrics: false` in `config.yaml`, `hr_bpm` and `hrv_rmssd_ms` are removed from the response and only the buckets remain. If the aggregator is not running, the response is `{"data_source": "no data yet (aggregator not running or has not published)"}`. If the snapshot is older than `stale_after_seconds` (60), `data_source` says `stale`.

## Status

This is experimental software built for one person's desk and one set of hardware. It has no releases (version 0.0.1), runs on Linux only, and has been tested against exactly the devices listed below. It is not a medical device. It makes no health claims, and the buckets are rough heuristics about one wearer's trend. Thresholds are first guesses and mostly untuned.

## Hardware

Every signal is optional. The aggregator reports `null` or `"unknown"` for anything it has no data for and does not fill gaps.

| Signal | Hardware | Notes |
| --- | --- | --- |
| CO2 | Sensirion SCD-41 sensor on an Adafruit QT Py ESP32 Pico, connected by USB serial | MicroPython firmware in `firmware/`. Found by USB vendor:product ID from `config.yaml`. Parts and build notes: [ambient-context-design.md](ambient-context-design.md). |
| HR and HRV | Polar Verity Sense optical armband, over Bluetooth Low Energy (BLE) | Found by its advertised name (`Polar Sense`). Trade-offs against a chest strap: [sensor-hardware.md](sensor-hardware.md). |
| Keystroke dynamics | Any keyboard | Read through Linux evdev. Needs `input` group access, see Privacy. |

## Setup and run

You need Linux, Python 3.11 or newer, Docker, and [uv](https://docs.astral.sh/uv/). Run everything from the repo root. Steps 3 and 4 start long-running processes, so use a separate terminal for each.

1. Install dependencies. Use `uv sync` rather than `pip install -e .`, because `uv.lock` pins hash-verified versions of the Bluetooth libraries that parse data from the radio.

   ```bash
   uv sync
   ```

2. Start the MQTT broker. MQTT is a lightweight publish/subscribe messaging protocol; the pollers publish readings to the broker and the aggregator subscribes. This starts Mosquitto, an open-source broker, in Docker, bound to `127.0.0.1`.

   ```bash
   make broker-up
   ```

3. Start the pollers that match your hardware, one per sensor:

   ```bash
   uv run python -m afferent.co2_poller
   uv run python -m afferent.polar_poller
   uv run python -m afferent.keystroke_poller
   ```

   `make run-co2` and `make run-polar` start the first two in the background with a log and pid file under `logs/` (`make stop-*` and `make tail-*` exist for each; add `VERBOSE=1` for debug logging, which includes raw per-beat heart data). The Verity Sense must be bonded over Bluetooth once first; see below. Read [SECURITY.md](SECURITY.md) before running the keystroke poller.

4. Start the aggregator, which computes the buckets and writes the snapshot (`make run-aggregator` runs it in the background):

   ```bash
   uv run python -m afferent.aggregator
   ```

5. Register the MCP server with Claude Code. Copy the example config, keeping the copy in the repo root because `"cwd": "."` resolves relative to that file:

   ```bash
   cp .mcp.example.json .mcp.json
   ```

   Claude Code then launches `uv run python -m afferent.mcp_server` itself, over stdio, so the server opens no network port.

To watch raw readings on the broker:

```bash
docker exec afferent-mosquitto mosquitto_sub -t 'sensors/#' -v
```

### Pairing the Verity Sense

The armband needs a one-time Bluetooth bond, or BlueZ (the Linux Bluetooth stack) drops the connection after a couple of seconds. `bluetoothctl` is interactive, so type these yourself with the armband awake and worn. `<mac-address>` is what `scan on` prints once the armband appears.

```
bluetoothctl
> agent NoInputNoOutput
> default-agent
> scan on
> pair <mac-address>
> trust <mac-address>
> quit
```

### Flashing the CO2 board

The firmware is two MicroPython files, `firmware/main.py` and `firmware/scd41.py`. `pyproject.toml` has a `firmware` extra (`uv sync --extra firmware`) that installs `esptool` and `mpremote` for this. The exact flashing steps are not scripted here; the design notes describe the board setup.

## Privacy

- **Keystrokes.** `src/afferent/keystroke_poller.py` sees the raw key event, because the operating system gives it that, and reduces it to `{is_backspace, dt_ms, ts}` before anything is published or logged: whether the key was backspace, milliseconds since the previous key press, and a timestamp. No other key identity leaves that function. Key-up and auto-repeat events are dropped. Timing alone can carry some information about what was typed, which is the basis of keystroke-dynamics research, so the timing stream is not anonymous.
- **Shipped default: off.** `config.yaml` has `keystroke.enabled: false`, so the poller exits at startup. To turn it on, set it to `true`, add the poller's account to the Linux `input` group, and start it. Setting it back to `false` does not revoke an existing `input` membership.
- **The `input` group is broad.** Membership gives every process that account runs read access to all input devices, which includes raw keystrokes system-wide. `scripts/setup-keystroke-service-account.sh` (run with `sudo`) creates a login-less account for the poller and installs a hardened systemd unit from `systemd/afferent-keystroke.service.template`. [SECURITY.md](SECURITY.md) explains this and how to revoke the grant.
- **The broker is local and unauthenticated.** `mosquitto.conf` sets `allow_anonymous true` with no TLS. `docker-compose.yml` publishes the port as `127.0.0.1:1883`, so only the local machine can reach it, but any local user or process can read and publish sensor topics. On a shared machine, add authentication first.
- **Where data is stored.** The aggregator writes `state.json` and `hrv_baseline.json` under `$XDG_STATE_HOME/afferent/` (default `~/.local/state/afferent/`), directory mode `0700` and file mode `0600`. The baseline is a rolling average of past HRV by time of day. Logs from `make run-*` go to `logs/` with the same modes. The keystroke poller writes no files.
- **Leaving the machine.** afferent itself makes no connection beyond the local broker, the Bluetooth device and the serial port. The MCP server's output goes to whichever AI model your assistant uses, so with a hosted model the snapshot reaches that provider. Set `mcp.expose_raw_biometrics: false` to send buckets only.

## More documentation

- [SECURITY.md](SECURITY.md): reporting vulnerabilities, exactly what the keystroke poller does, the `input` group.
- [ambient-context-design.md](ambient-context-design.md): design rationale, the CO2 sensor build, open questions, and the not-yet-built pieces (webcam poller, eye tracking).
- [sensor-hardware.md](sensor-hardware.md): why the Verity Sense, and how it compares with a chest strap.
- [CLAUDE.md](CLAUDE.md): instructions for coding agents working in this repo.

## Development

```bash
make check    # mypy --strict, ruff, pytest
```

CI runs the same command.

## Related

[efferent](https://github.com/justinstimatze/efferent) is the output side: a haptic vest, lights and MIDI controllers. afferent is the sensor side.

## License

MIT; see [LICENSE](LICENSE). Contact: justin@justinstimatze.com.
