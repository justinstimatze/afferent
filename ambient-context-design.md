# ambient-context design

Design rationale for this project, covering the existing roadmap plus two
concrete increments: a **CO₂ sensor** and a **hook-push surface**. Written as
a reasoning trail rather than a finished spec — some sections describe
decisions already implemented, others are still open.

## What this is

Give the agent a sense of the ambient conditions of the working environment —
the invisible things (bad air, drained recovery, rising stress, a dirty git
tree, a nearly-full context window) that affect the work but that a
prompt-only agent is blind to. This project already models this as a
local-first sensor pipeline exposing user state to Claude Code over MCP.

The reframe worth keeping: the sensors are not surveillance of the user. They
are a readout of whether the agent is *helping or grinding the user down* —
the least-monitored channel, which is why it leaks the truth the text channel
hides. If stress spikes every time the agent emits a wall of text, that is
physiological ground-truth on verbosity, not self-report.

## Two output surfaces (the new increment)

afferent currently exposes state one way:

- **MCP pull** — `get_session_state`, `get_focus_window`, `suggest_intervention`.
  The agent asks when it thinks to. Already built.

Add a second, complementary surface:

- **Hook push** — a `UserPromptSubmit` hook injects ambient state into *every*
  prompt, so the agent doesn't have to remember to ask. This is the missing
  half: MCP-pull is on-demand, hook-push is ambient.

The hook-push surface is intentionally a separate standalone tool, not part of
this repo — it should work with no sensor hardware installed at all, on its
own zero-dependency time signal, and this project only *feeds* it (reading
this project's derived `state/*` when available, never the reverse). This
keeps one push mechanism instead of forking a second, and keeps a
broadly-useful utility out of a personal hardware rig.

They are the same state computed once (the aggregator), rendered two ways —
the dual-sink pattern. A third, human-facing sink already exists in Claude
Code: the **status line** (`Opus 4.8 · repo:branch* · ctx23%`), which renders
to the user's eyes for free and is invisible to the agent. Same data, three
consumers.

### Push discipline — gate hard, or it is wallpaper

Injected context costs tokens on every turn and, worse, currently
**accumulates in the transcript** instead of being ephemeral
(anthropics/claude-code#40216). So the hook must not fire every turn. Rules by
signal type:

- **Continuous → human only.** The status line is free; show everything there.
- **Ambient safety rails** (CO₂, RAM/disk, git-dirty, cost, context-fullness)
  → **threshold-gated**: inject only when a limit is near or a value crossed.
- **Orientation** (which project, session context) → **on transition**
  (session start, cwd change), never per-turn.
- **Elapsed/time** → **elapsed-gated** (only when a gap or daypart is notable).

Keep the whole injection to ~200–500 tokens (the community-agreed budget; the
model deprioritizes long injections anyway).

**Re-remind is session-aware, not a flat interval** (headrace `sensor.go`,
`earlySessionReRemindWindow`): because of #40216, an injection's true cost is
roughly its size times every turn *remaining* in the session, so the same
periodic re-remind is far more expensive fired early in a long session than
late in a short one. headrace's sensor re-remind (the one signal here with
unbounded wall-clock-periodic re-firing — git/time/context are all naturally
infrequent by construction) doubles its interval for a session's first ~30
minutes, then reverts to the configured cadence. `headrace quality` (see
headrace's README) measures the accumulated cost directly from real
sessions rather than leaving it a guess.

### The ctx% confabulation trap

If a raw string like `ctx23%` is injected, the agent will guess whether it
means used-vs-remaining and sometimes guess backwards, then narrate the guess
with false confidence. The model-facing renderer must be explicit where the
human HUD can be terse: emit `context: 23% used (77% free)`, not `ctx23%`.
Costs three words, removes a confident-wrong failure mode.

## Fuse for confidence, not just coverage

A single noisy scalar steering behavior is the failure mode (Muse "focus" is
confounded by blinks, jaw clench, movement; Garmin Body Battery is a black
box). The aggregator's derived state should require **two physically
independent channels to agree** before the closed loop acts — e.g. keystroke
slowdown *and* rising HR before concluding "fatiguing." Fusion buys
trustworthiness, not just richer data. And an explicit reading always yields
to the user's words: the signal is a weak prior, never an oracle or a veto.

## Sensor inventory by layer

Pick roughly one per layer; don't stack redundant sensors in the same layer.
Fuse the slow (recovery) with the fast (live load).

### Recovery / capacity (slow, daily-to-hourly)
- **Polar Verity Sense / HRV** — already the v1 poller. Slow day-budget: sets scope,
  don't propose the ambitious plan on a depleted morning.
- **CO₂ (new)** — see build spec below. Elevated indoor CO₂ measurably
  degrades cognition; actionable and nearly privacy-free ("CO₂ 1400, crack a
  window"). Highest value-per-dollar for knowledge work.
- (optional) CGM glucose — names the afternoon crash by its cause, not symptom.

### Live attention / load (fast, real-time)
- **Muse 2 EEG** — already in the architecture (offline today; wiring in
  progress). Local streaming (mind-monitor / muse-lsl over OSC/LSL on
  localhost → derived focus scalar). Neurosity Crown is the consumer product
  built for exactly this focus API if Muse proves too noisy.
- **Eye-tracking** — Beyond 2e is already roadmap v5. Pupillometry (pupil
  dilation) is one of the most validated cognitive-load measures; gaze also
  distinguishes reading-vs-scanning ("following this or lost"). Needs the
  hardware. Tobii-class is the gold standard if Beyond 2e doesn't deliver.
- **Keystroke dynamics** — free, in-stream, no hardware. Backspace-burst rate
  and pause structure are a live frustration/flow proxy; a delete spike right
  after the agent's output is a clean "that landed badly" signal.

### Presence / context (are you here, what are you doing)
- **Local webcam (MediaPipe)** — already roadmap v2. Best zero-hardware
  human-state sensor: gaze/presence (are you at the desk; reading vs staring
  past the screen), blink rate (fatigue), coarse facial affect
  (confusion/frustration), posture drift. Local OpenCV/MediaPipe → derived
  scalar, never a frame stored.
- **Window focus / alt-tabbing** — don't build it, reuse **ActivityWatch**
  (`aw-watcher-window` + `aw-watcher-afk`, local-first). On Wayland it needs
  compositor protocols (`ext-idle-notify-v1`, `wlr-foreign-toplevel`); use
  `aw-watcher-window-wayland` or the Rust `awatcher`. Note the known
  limitation: focused window ≠ looked-at window, which is exactly why webcam
  gaze complements it.
- **Machine state** — git branch+dirty (`*`), free RAM / disk / thermals,
  session cost + context-fullness. These come from the host, not a sensor, but
  belong in the same aggregator as ambient safety rails. The git-dirty flag is
  the commit-discipline tripwire; the cost/context gauge serves the
  compact-before-a-batch decision.

### Environment (the room, not the body)
- **CO₂** (recovery layer above), light (lux + color temp), noise (dB),
  temperature/humidity. Nearly privacy-free — the right place to start.

## CO₂ build spec (concrete)

### Decision: USB-serial tether, not WiFi/Ethernet
The room's WiFi is weak and the polling host sits on the same desk. So the
sensor tethers to the desktop over USB and publishes over serial — no network
link to be flaky, no antenna, no broker round-trip over bad WiFi. Board keeps
WiFi/BLE silicon for future relocation (option value), but runs USB day one.

### Parts (Adafruit, one order, ~$69, no soldering)
- **QT Py ESP32 Pico** — PID 5395 — $14.95 (WiFi+BLE, onboard antenna, STEMMA QT)
- **SCD-41 True CO₂ / NDIR breakout (STEMMA QT)** — PID 5190 — $49.95
  (true NDIR — NOT an eCO₂/VOC estimator, which is the buying trap)
- **STEMMA QT / Qwiic cable 100mm** — PID 4210 — $0.95
- **USB-A to USB-C data cable** — PID 4474 — ~$3.95 (must be data, not charge-only)

Powers off the desk USB hub (USB-A). SCD-41 sits at I²C 0x62.

### Firmware + wiring into afferent (as built)
- MicroPython, not CircuitPython: this board has no native USB (a
  USB-to-serial bridge chip instead), so there's no drag-and-drop
  `CIRCUITPY` drive to push CircuitPython's `adafruit_scd4x` onto. MicroPython
  transfers over the same USB-serial link the data rides on, no WiFi needed.
  `adafruit_scd4x` is CircuitPython-only, so `firmware/scd41.py` is a small
  hand-rolled driver instead, verified against Sensirion's real command set.
  A few-second loop prints `co2=NNN,temp=NN.N,rh=NN` to USB serial
  (`firmware/main.py`).
- The poller (`src/afferent/co2_poller.py`) finds the sensor by USB
  vendor:product ID, not a fixed `/dev/ttyACM0` — that path isn't stable
  across reboots or when other USB-serial devices are plugged in. It
  republishes to MQTT `sensors/co2`, matching the existing poller pattern
  (each sensor = small process → MQTT topic). Do NOT read serial directly in
  the hook — go through MQTT/aggregator like every other sensor.
- Aggregator (not yet built — v3) will fold CO₂ into `state/*`; hook-push
  emits e.g. `air: 1400ppm — crack a window` only past a threshold.

## Privacy design

- **Local-first** — nothing leaves the host. Muse/webcam/keystroke are
  derived to a coarse scalar on-box; raw traces/frames never stored.
- **Coarse-bucketed** — inject `focus: high` / `capacity: low`, never a number
  precise enough to be a health record. Bucketing also stops the agent
  over-reading a noisy scalar as precise.
- **Never in the transcript** — the hook injection is ephemeral by intent;
  given #40216's accumulation bug, keep it coarse so a stale trail of buckets
  is harmless (and it doubles as elapsed-signal, comparing across turns).
- **Informs, never commands** — off by default; a low-capacity reading tints,
  never vetoes. The user's explicit words always win.
- **Privacy gradient** — environment (CO₂/light/noise) is nearly free of
  privacy cost → start here. Wearables are middle (coarse derived only).
  Webcam/mic are the sharp end (local-only, derive a scalar, or leave off).

## Prior art

- **DoD: DARPA Augmented Cognition (AugCog, ~2001–07)** is the direct prior
  art and prefigures this whole design. The Technical Integration Experiment
  evaluated 20 psychophysiological measures (fNIR, EEG, ERP, **pupil dilation,
  mouse pressure, posture, HR, GSR**) on a Navy C2 task, classified cognitive
  state in real time, and closed the loop — directly-sensed state beat static
  automation. Living home: AFRL 711th Human Performance Wing. What killed its
  reach was clunky gov-only sensors and thin "mitigations"; 2026 differs
  because sensors are consumer-grade and an LLM can act on state richly.
  (DTIC ADA420147.)
- **Context engineering** is the named discipline for the injection side
  (write/select/compress/isolate; just-in-time = inject minimal sufficient
  context; ~200–500 token budget). It targets docs/tools/retrieval, NOT live
  machine+human state — the gap this project fills.
- **ActivityWatch** is the solved window-focus/AFK layer (reuse, don't build).

## Open questions / next steps

1. ~~Build the CO₂ poller (serial → MQTT `sensors/co2`).~~ Done.
2. Extend the hook-push tool to read this project's `state/*` and emit gated
   CO₂/git/cost lines; label ctx% explicitly.
3. Wire the Muse 2 (already have it) into a live focus scalar → MQTT.
4. Decide the fusion rule in the aggregator (two-channel agreement + dwell
   time before the closed loop acts).
5. Prior-art dig on the closed-loop-assistant-tuning framing.
6. Hook-push gating: threshold-gated is the baseline (see "Push discipline"
   above), but a crossed threshold that persists across a long gap between
   turns shouldn't just vanish. Add a decay/re-remind timer — surface it
   once, then again only after N minutes if still true, never every turn.
7. HRV specifically can't be compared to a population norm (see
   sensor-hardware.md), only to the wearer's own baseline — so injection
   should never carry a raw ms figure, only a personally-calibrated bucket
   relative to that baseline, consistent with the privacy design above.
