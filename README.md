# afferent

afferent is a local-first sensor pipeline that exposes your physiological and
environmental state — HRV, CO2, keystroke dynamics — to a Claude Code agent
over MCP (the Model Context Protocol). An agent that can call
`get_session_state` can condition its behavior on how you're actually doing,
not just on what you typed.

Everything runs on your machine. Nothing leaves it.

This README covers setup and the state model. Two other docs go deeper:
`ambient-context-design.md` (design rationale, sensor inventory, the CO2
build spec, privacy) and `sensor-hardware.md` (HR/HRV device selection and
the PPI-vs-RR tradeoffs mentioned below). `SECURITY.md` covers the keystroke
poller's privacy model specifically.

## Quickstart

You need Python 3.13, Docker, and `uv`. Clone this repo and run every
command below from its root.

Steps 3 through 5 start long-running processes, not one-shot commands — run
each in its own terminal (or background it yourself), not one after another
in the same shell. Step 3 will sit there reporting "no data yet" until step
5 is also running; that's expected, not a hang.

**1. Install dependencies.**

```bash
uv sync
```

Use `uv sync`, not `pip install -e .`. Two of this project's dependencies
(`bleak`, `polar-python`) parse untrusted binary protocol data off the wire —
`uv.lock`'s pinned, hash-verified versions are a supply-chain requirement
here, not a reproducibility nicety.

**2. Start the broker.**

```bash
docker compose up -d
```

This starts an MQTT broker (Mosquitto) bound to `127.0.0.1` only —
`docker-compose.yml` enforces that at the port-mapping layer, since
`mosquitto.conf` has no authentication of its own. No sudo needed once Docker
itself is set up.

**3. Start the MCP server.**

```bash
uv run python -m afferent.mcp_server
```

It reads state the aggregator publishes (step 5) and reports `"no data
yet"` honestly until that's running.

Then, so Claude Code can find it:

```bash
cp .mcp.example.json .mcp.json
```

Claude Code reads project-scoped MCP config from `.mcp.json`; `cwd: "."`
inside it resolves relative to wherever `.mcp.json` itself sits, so keep the
two files together.

**4. Run whichever pollers match the hardware you have.**

Each poller is a standalone process that finds its device by identity (USB
vendor:product ID, BLE advertised name), not a fixed path, so plug-in order
never matters.

```bash
# CO2 (Sensirion SCD-41 over USB serial -- see sensor-hardware.md for the build)
uv run python -m afferent.co2_poller

# Polar Verity Sense (BLE heart rate + PPI)
uv run python -m afferent.polar_poller

# Keystroke dynamics (backspace-burst rate over evdev)
uv run python -m afferent.keystroke_poller
```

The Polar Verity Sense needs a one-time BLE bond before it stays connected —
see "Pairing the Verity Sense" below. The keystroke poller reads every
keypress system-wide (timing and a backspace flag only, never key identity)
and needs the `input` group, which is a real, permanent grant on whatever
account runs it — read SECURITY.md before enabling it, and consider the
dedicated-account setup a few sections down.

**5. Run the aggregator.**

```bash
uv run python -m afferent.aggregator
```

This is what turns raw sensor streams into the state the MCP server actually
serves. It degrades gracefully with sensors missing — `hr_bpm` and
`hrv_rmssd_ms` stay `null`, `focus_label` reports `"unknown"`, and nothing is
ever fabricated to fill a gap.

You're done. Any MCP client that calls `get_session_state` now sees your
current derived state.

## How it works

```
[Polar Verity Sense] ─BLE──┐
[CO2 (SCD-41)] ──USB──┤
[keyboard] ──evdev────┤
[webcam]       ──v4l2─┤   pollers ──MQTT──> aggregator ──snapshot──> mcp_server ──> Claude Code
[Muse 2 (offline)]    ┘                        │                                  (or any MCP client)
[eye-tracking, future]                         └─MQTT (retained)──> other subscribers
```

Three kinds of process, three responsibilities:

- **Pollers** are small, single-purpose processes. Each one talks to exactly
  one sensor and publishes raw events to an MQTT topic. Posture and activity
  stay `"unknown"` until the webcam poller (v2) lands — nothing here
  fabricates a signal it doesn't have.
- **The aggregator** subscribes to every topic, computes derived state (an
  HRV bucket relative to your own baseline, a CO2 bucket, a keystroke
  bucket, an intervention rule), and republishes it retained to MQTT
  `state/session/current` — and, in parallel, writes the same JSON to an
  on-disk snapshot at `$XDG_STATE_HOME/afferent/state.json` (falls back to
  `~/.local/state/afferent/state.json` if that variable isn't set).
- **The MCP server** reads that snapshot and exposes it as three tools:
  `get_session_state`, `get_focus_window`, `suggest_intervention`.

The broker runs on localhost for now. Moving it to a dedicated sensor host
later is one line in `config.yaml`.

**Why MQTT and not just JSON files:**

- Decoupled processes — kill any one, the others keep running.
- Per-topic retention (the broker remembers the last value), so the MCP
  server answers instantly without polling sensors itself.
- Trivial to factor across machines later (Tailscale plus a remote broker).
- Standard tooling to debug with — `mosquitto_sub`, MQTT Explorer.

```bash
# watch raw readings land on the broker directly
docker exec afferent-mosquitto mosquitto_sub -t 'sensors/#' -v
```

## Signals

**CO2.** `co2_bucket` is `"normal"`, `"approaching"`, or `"high"` against the
thresholds in `config.yaml` (`co2_ppm_elevated`, `co2_ppm_high`). CO2 is the
one signal treated as trustworthy on its own — see "The intervention rule"
below for why.

**HRV.** `hrv_bucket` compares your current RMSSD to your own baseline, never
to a population norm (see sensor-hardware.md for why PPI from a Polar Verity
Sense can't support that comparison). The baseline itself persists across
restarts: `hrv_baseline_store.py` keeps a rolling average per 3-hour daypart
in `$XDG_STATE_HOME/afferent/hrv_baseline.json` (same fallback path pattern
as `state.json` above), so a fresh session picks up
an immediate provisional baseline from past sessions at the same time of day
instead of reporting `"warming"` for its first `hrv_baseline_minutes` every
single restart. Your own fresh baseline, once established this run, always
supersedes the provisional one and updates the store in turn.

**Keystroke dynamics.** `keystroke_bucket` is a rolling backspace rate over a
much shorter window than HRV can ever run at (`keystroke_window_minutes`,
minutes rather than HRV's fixed 5-minute floor — see sensor-hardware.md on
why HRV can't go faster no matter what's built on top of it). It stays
`"unknown"` until the poller is enabled and has recent data. Enabled by
default in `config.yaml`; read SECURITY.md before you rely on that — it
covers exactly what this poller does and doesn't do with your keystrokes,
and how to run it under a dedicated account instead of your own login.

**Factors.** Every state snapshot carries `factors`: short tags (`"co2_high"`,
`"hrv_below_baseline"`, `"hrv_low_confidence"`, `"backspace_elevated"`) naming
which primitives actually contributed to the buckets above, derived
independently from the same inputs so a factor can never silently disagree
with the bucket it explains. `hrv_low_confidence` flags a "below baseline"
reading built on a large-ish gated-sample fraction — still computed, but thin
data.

**The intervention rule.** `suggest_intervention` is deliberately
conservative. A sustained high-CO2 reading fires `"crack a window"` on its
own — CO2 is the stated single-channel exception. Every other intervention
needs two physically independent channels to agree first: HR and HRV don't
qualify on their own (both ride the same PPI stream), but HRV below baseline
together with an elevated backspace rate fires `"take a break"`; either
alone stays `null`. Posture- and activity-driven interventions stay `null`
until the webcam poller (v2) lands. See ambient-context-design.md's "Fuse for
confidence" for the reasoning behind requiring agreement at all.

## Pairing the Verity Sense

The armband needs a one-time BLE bond, or BlueZ drops the link a couple
seconds in (no pairing agent registered → `device_confirm_passkey:
Operation not permitted` in `journalctl -u bluetooth`; see
sensor-hardware.md). Pair once with the armband awake and worn:

`bluetoothctl` below is an interactive shell, not a script — run it directly
in a terminal you're typing into, not piped or automated. `<mac-address>` is
not a placeholder to fill in ahead of time: it's the address `scan on`
prints live once your armband is discovered, so you have to watch its output
and copy the real value from there.

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

## Running keystroke dynamics under a dedicated account

The `input` group grants raw keyboard read to every process the member
account runs — not just this poller. `scripts/setup-keystroke-service-account.sh`
creates a dedicated, login-less `raw-input` system account, scopes the
`input` grant to it alone, and installs
`systemd/afferent-keystroke.service.template` to run the poller under that
account instead of your own login. Both commands need `sudo` and may prompt
for your password interactively:

```bash
sudo ./scripts/setup-keystroke-service-account.sh
sudo systemctl enable --now afferent-keystroke.service
```

Read SECURITY.md first — it covers exactly what this poller reads, what it
never reads, and how to revoke the `input` grant entirely if you decide
against enabling it.

## Configuration

`config.yaml` controls topics, thresholds, session timing, and the MCP
server's exposure policy. One setting worth knowing up front:
`mcp.expose_raw_biometrics` (default `true`) controls whether
`get_session_state` returns raw `hr_bpm`/`hrv_rmssd_ms` alongside the derived
buckets. This is a pull tool — the agent asks for it deliberately — which is
why it's allowed to return more than the ambient push surface described
below ever does. Set it `false` to restrict every MCP response to buckets
only.

## Beyond this repo

The on-disk snapshot this repo writes (`$XDG_STATE_HOME/afferent/state.json`)
is the integration point for a separate, private sibling project: a
`UserPromptSubmit` hook that reads that snapshot and injects ambient state
into Claude Code prompts directly, threshold-gated with a decay/re-remind
timer rather than on every turn. It never carries a raw HRV figure, only the
bucket this repo already computed — see ambient-context-design.md's "Push
discipline" for the full rationale. This repo only computes and publishes
the snapshot; it has no opinion on what reads it.

## Roadmap

See ambient-context-design.md for the full design capture — surfaces,
gating, sensor inventory, the CO2 build spec, privacy, prior art.

- [x] v0: project skeleton, MCP server with mock state
- [x] CO2 poller: SCD-41 over USB serial → MQTT `sensors/co2`
- [x] v1: Polar Verity Sense BLE poller (PPI, not R-R — see
      sensor-hardware.md for why that's good enough here but not comparable
      across devices) → MQTT `sensors/polar/hr`, `sensors/polar/hrv`
- [x] v3: aggregator — derived state, CO2-only intervention rule
- [x] v3.1: keystroke dynamics — backspace-burst rate via evdev
- [x] v3.2: persisted, time-of-day-aware HRV baseline
- [x] v3.3: keystroke dynamics wired into the two-channel intervention rule
- [x] the ambient-push sibling project described above, shipped
- [ ] v2: MediaPipe webcam poller (posture, hands, activity, gaze/presence)
- [ ] v4: durable per-session protocol the agent can read and conditionally
      apply against state
- [ ] v5: eye-tracking input channel (when hardware lands)
- [ ] vN: factor sensors out to a dedicated RPi host
