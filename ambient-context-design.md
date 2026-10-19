# Design notes

Design rationale for afferent, covering the existing pipeline plus the CO2
sensor and the prompt-hook surface. These are working notes. Some sections
describe what is built, and the open questions at the end are not settled.

## Goal

Give a coding agent a view of the working environment that a prompt-only
agent cannot see: bad air, a drop in recovery, a long session without a
break. The sensors report on whether the agent's output is helping or wearing
the user down, a channel the text conversation does not carry. If stress rises
every time the agent emits a wall of text, that shows up as a measurement
instead of waiting for the user to complain.

The signals are a weak prior. An explicit statement from the user always
outranks a sensor reading.

## Output surfaces

- **MCP pull.** `get_session_state`, `get_focus_window` and
  `suggest_intervention`. The agent asks when it thinks to. Built.
- **Hook push.** A `UserPromptSubmit` hook injects ambient state into prompts
  so the agent does not need to remember to ask. This lives outside this repo
  and only reads the snapshot afferent writes
  (`$XDG_STATE_HOME/afferent/state.json`). It should work with no sensor
  hardware installed, on its own time signal.
- **Status line.** A human-facing display in Claude Code that the agent does
  not see.

All three consume the same state, computed once in the aggregator.

### Push discipline

Injected context costs tokens on every turn and currently accumulates in the
transcript instead of being ephemeral (anthropics/claude-code#40216). A hook
should therefore not fire on every turn:

- Continuous values go to the human-facing status line only.
- Ambient safety rails (CO2, RAM, disk, git-dirty, cost, context fullness) are
  threshold-gated: inject only when a limit is near or crossed.
- Orientation (project, session context) is injected on transition, such as
  session start or a directory change.
- Elapsed-time notes are injected only when a gap or daypart is notable.

Keep an injection to a few hundred tokens. Because injected text accumulates,
the cost of a re-reminder is roughly its size times the turns remaining in the
session, so re-remind intervals should be longer early in a session.

A raw string like `ctx23%` can be read
as used or remaining and misread with confidence; `context: 23% used (77%
free)` cannot, so label numbers explicitly for the model.

## Fuse for confidence

One noisy scalar steering behavior is the failure mode: EEG "focus" scores are
confounded by blinks, jaw clench and movement, and consumer "readiness" scores
are opaque. The aggregator requires two physically independent channels to
agree before it suggests an intervention, for example HRV below baseline and
an elevated backspace rate. HR and HRV do not count as two, since both derive
from the same PPI stream. CO2 is the one single-channel exception because it
is a direct, low-noise measurement of the room.

## Sensors by layer

Use roughly one sensor per layer rather than stacking redundant ones, and
combine a slow recovery signal with a fast load signal.

### Recovery (slow, hourly to daily)

- **Polar Verity Sense / HRV.** Built. A day-scale budget signal.
- **CO2.** Built. High indoor CO2 is associated with reduced performance on
  some cognitive tasks in controlled studies, though the evidence is mixed.
  It is also actionable and carries almost no privacy cost.

### Live attention and load (fast)

- **Keystroke dynamics.** Built (`keystroke_poller.py`). Backspace rate is a
  rough real-time proxy for friction, and needs no hardware. It uses an
  absolute configurable threshold because there is no natural resting rate
  the way HRV has a baseline. It covers the whole system rather than one Claude
  Code window; scoping would need foreground-window tracking. Pause structure is
  not used yet.
- **EEG (Muse 2).** Not integrated. Would stream locally over OSC/LSL into a
  derived focus scalar.
- **Eye tracking.** Not built. Pupil dilation is a well-studied load measure,
  and gaze separates reading from scanning. Needs hardware.

### Presence and context

- **Webcam (MediaPipe).** Not built. Would derive gaze/presence, blink rate
  and posture drift locally, storing a scalar and never a frame.
- **Window focus.** Reuse ActivityWatch (`aw-watcher-window`,
  `aw-watcher-afk`) rather than building it. On Wayland it needs
  `aw-watcher-window-wayland` or `awatcher`. Focused window is not the same
  as looked-at window, which is why webcam gaze would complement it.
- **Machine state.** Git dirty flag, free RAM and disk, session cost and
  context fullness come from the host and belong with the ambient safety
  rails.

### Environment

CO2, light, noise and temperature/humidity carry the lowest privacy cost.

## CO2 build

### USB serial, not WiFi

The sensor tethers to the desktop over USB serial. There is no network link to
drop and no broker round-trip. The board has WiFi and BLE for later
relocation.

### Parts (Adafruit)

- QT Py ESP32 Pico (product 5395)
- SCD-41 NDIR CO2 breakout, STEMMA QT (product 5190). Buy a true NDIR sensor,
  not an eCO2/VOC estimator.
- STEMMA QT / Qwiic cable, 100 mm (product 4210)
- USB-A to USB-C cable (product 4474), which must carry data

Prices change; check them before ordering. No soldering is needed, and the
board runs from a USB port. The SCD-41 sits at I2C address 0x62.

### Firmware and poller

- The firmware is MicroPython. This board reaches the host through a
  USB-to-serial bridge chip with no native USB, so there is no CircuitPython
  drive to copy `adafruit_scd4x` onto. MicroPython installs over the same
  serial link. `firmware/scd41.py` is a small driver written against
  Sensirion's command set, since `adafruit_scd4x` is CircuitPython-only.
  `firmware/main.py` prints `co2=NNN,temp=NN.N,rh=NN` every few seconds.
- `src/afferent/co2_poller.py` finds the board by USB vendor:product ID, not
  `/dev/ttyACM0`, which changes across reboots and with other USB-serial
  devices. It publishes to MQTT `sensors/co2`. Consumers should read through
  MQTT or the aggregator, not the serial port.

## Privacy design

- **Local-first.** Nothing leaves the host from this code. Keystroke and
  heart-rate data are reduced to a coarse scalar on the machine, and raw
  traces and frames are not stored.
- **Coarse buckets for injection.** Push surfaces carry `focus: high` or
  `capacity: low`, not a number precise enough to be a health record. Bucketing
  also keeps the agent from over-reading a noisy scalar.
- **Informs, never commands.** A low-capacity reading is context for the agent;
  it never vetoes what the user asks for.
- **Privacy gradient.** Environment sensors (CO2, light, noise) cost the least.
  Wearables sit in the middle when only coarse derived values leave the
  sensor process. Keystroke dynamics sits past wearables: it observes every
  key press system-wide while it runs, though it publishes only a backspace
  flag and inter-key timing. Webcam and microphone are the most sensitive
  and, if added, should stay local and produce a scalar or stay off.
- The MCP server's `mcp.expose_raw_biometrics` setting controls whether the
  pull tool returns raw heart rate and RMSSD. Push surfaces should not carry
  raw figures.

## Prior art

- **DARPA Augmented Cognition (about 2001 to 2007)** used physiological
  measures (fNIR, EEG, pupil dilation, heart rate, galvanic skin response and
  others) to classify cognitive state in real time and adapt a task, in a Navy
  command-and-control setting. Its sensors were bulky and government-only; the
  sensors here are consumer-grade.
- **Context engineering** covers what to inject into an agent's context. Live
  machine and human state is the part it does not usually address.
- **ActivityWatch** already solves window-focus and AFK tracking.

## Open questions

1. Integrate a Muse 2 into a live focus scalar published to MQTT.
2. Add a dwell time to the fusion rule. Rolling windows are the only
   smoothing now.
3. Posture and activity fusion, which waits on the webcam poller.
4. Prior-art review of closed-loop assistant tuning.
5. A voice/prosody stress signal. It probably does not belong here: afferent
   has no audio access, and a project that already processes audio in real
   time could derive it more cheaply.
