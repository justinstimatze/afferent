# afferent — closed-loop biofeedback sensor pipeline

Local-first sensor pipeline that exposes user state (HRV, posture, session
window) to a Claude Code agent via MCP, so the agent can condition behavior on
your actual cognitive/physiological state rather than just the prompt.

## Architecture

```
[Polar Verity Sense] ─BLE──┐
[CO2 (SCD-41)] ──USB──┤
[webcam]       ──v4l2─┤   pollers ──MQTT──> aggregator ──MQTT──> mcp_server ──> Claude Code
[Muse 2 (offline)]    ┘                                                          (or any MCP client)
[eye-tracking, future]
```

- Each sensor is a small process that publishes raw events to an MQTT topic.
- The aggregator subscribes, computes derived state (rolling HRV stats,
  posture-drift summary, focus-window estimate), republishes to `state/*`.
- The MCP server exposes `get_session_state`, `get_focus_window`,
  `suggest_intervention` as tools the agent can call.

Localhost broker for v0. When you add an RPi as a dedicated sensor host,
change one line in `config.yaml`.

## Why MQTT and not just JSON files

- Decoupled processes — kill any one, the others keep running
- Per-topic retention (broker remembers last value) so the MCP server can
  answer instantly without polling sensors
- Trivial to factor across machines later (Tailscale + remote broker)
- Standard tooling (`mosquitto_sub` to debug, MQTT Explorer GUI)

## Running v0

```bash
# install
uv sync   # or: pip install -e .

# start a local broker (one-time; no sudo needed if docker is set up).
# Binds loopback only -- see mosquitto.conf, this has no auth.
docker run -d --rm --name afferent-mosquitto -p 127.0.0.1:1883:1883 \
  -v "$(pwd)/mosquitto.conf:/mosquitto/config/mosquitto.conf:ro" eclipse-mosquitto

# run the MCP server with mocked state (no real sensors wired in yet -- v0)
uv run python -m afferent.mcp_server

# point Claude Code at it via .mcp.json (see below)
```

## Running the pollers

Each poller is a standalone process; run whichever sensors you have on hand.
Both need the broker above running first, and both find their device by
identity (USB vendor:product ID, BLE advertised name) rather than a fixed
path, so plug-in order doesn't matter.

```bash
# CO2 (SCD-41 over USB serial -- see sensor-hardware.md for the build)
uv run python -m afferent.co2_poller

# Polar Verity Sense (BLE HR + PPI)
uv run python -m afferent.polar_poller
```

The Verity Sense needs a one-time BLE bond before its first connection, or
BlueZ drops the link a couple seconds in (no pairing agent registered ->
`device_confirm_passkey: Operation not permitted` in `journalctl -u
bluetooth` -- see sensor-hardware.md). Pair once with the armband awake and
worn:

```bash
bluetoothctl
> agent NoInputNoOutput
> default-agent
> scan on            # wait for "Polar Sense ..." to appear, then:
> pair <mac-address>
> trust <mac-address>
> quit
```

BlueZ remembers the bond after that; `polar_poller` won't need this again
unless the device gets unpaired or the host's Bluetooth state is reset.

Neither poller feeds `get_session_state` yet -- that's the aggregator (v3),
still mock-only. Watch raw readings land on the broker directly:

```bash
docker exec afferent-mosquitto mosquitto_sub -t 'sensors/#' -v
```

## Wiring into Claude Code

Copy `.mcp.example.json` to `.mcp.json` in this directory (Claude Code reads
project-scoped MCP config from there; `cwd: "."` in the file resolves
relative to wherever `.mcp.json` itself sits, so keep the two together).

Then in a Claude Code session, the agent can call `get_session_state` and
condition responses on it.

## Roadmap

See `ambient-context-design.md` for the full design capture (surfaces, gating,
sensor inventory, CO₂ build spec, privacy, prior art).

- [x] v0: project skeleton, MCP server with mock state (no MQTT yet — that
        lands with the aggregator in v3)
- [x] CO₂ poller: SCD-41 over USB serial → MQTT `sensors/co2`
- [x] v1: Polar Verity Sense BLE poller (PPI, not R-R — see
        sensor-hardware.md for why that's good enough here but not
        comparable across devices) → MQTT `sensors/polar/hr`,
        `sensors/polar/hrv`
- [ ] v2: MediaPipe webcam poller (posture, hands, activity, gaze/presence)
- [ ] v3: aggregator — derived state, intervention rules, two-channel fusion
- [ ] v4: durable per-session protocol the agent can read and conditionally
        apply against state
- [ ] v5: eye-tracking input channel (when hardware lands)
- [ ] later: feed a `UserPromptSubmit`-hook ambient-injection surface from
        `state/*`, complementing this MCP-pull server. Threshold-gated with
        a decay/re-remind timer, not per-turn — see ambient-context-design.md
        "Push discipline".
- [ ] vN: factor sensors out to a dedicated RPi host
