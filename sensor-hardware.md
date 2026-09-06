# Sensor hardware — HR/HRV device selection

Written 2026-07-24. **Polar H10 and Polar Verity Sense both ordered 2026-07-24.**
Nothing below has been measured on this project's hardware yet — the reasoning
is pre-purchase and the numbers are predictions to be checked, not results.
Spec figures come from recall, not from a vendor datasheet read at the time of
writing.

## Decision

Both devices owned. The **H10** is shared with another local project that
needs its ECG-grade R-R. The **Verity Sense** is afferent's candidate for
all-day wear.

The original plan was to buy the H10 first and add the Verity Sense only if
all-day chest wear failed. Buying both up front changes the question from "do I
need to spend more money" to "which one do I prefer wearing all day", and it
makes the head-to-head jitter measurement available immediately rather than
after a week of screening. Run that comparison first — it is the cheapest way
to learn whether PPI is good enough here, and everything below about the error
model is a prediction it will confirm or refute.

## The original worry was the wrong one

Chest straps do not sleep on motion. They sleep on electrode contact — the H10
powers down a few seconds after it stops reading skin impedance, and does not
care whether you are moving. Sitting still at a desk keeps it connected.

The Garmin band that sleeps when idle is a wrist optical sensor duty-cycling
its LEDs to save power. Different mechanism; it does not carry over.

## The real all-day risk

Electrode dry-out during sedentary wear. Sweat maintains contact during
exercise without any prep, which is why the strap works fine there. Whether
sedentary sweat suffices varies by person, ambient temperature, and whether a
shirt is wicking moisture away. Plenty of people wear an H10 through eight
hours of sleep with no dropouts; others get flaky readings after two hours at a
desk in a cool room. A cool air-conditioned room in a t-shirt is the bad case.

This is a risk, not a certainty. The fix if it appears is conductive electrode
gel (Signa Gel, Lectron II) rather than water — water evaporates in an hour or
two, gel lasts a workday. Buy a tube with the strap so it is on the shelf.

Slower version of the same problem: dried sweat leaves salt in the fabric, and
after a few unwashed weeks the electrodes read worse.

Second all-day risk is skin irritation. Eight hours a day of chest strap is a
real comfort question and the reason the Verity Sense fallback exists.

## Screening protocol

Order of operations now that both devices are on hand:

1. **The 20-minute simultaneous comparison** (see below). Answers the PPI
   question with real numbers instead of the model further down. Do this first;
   it is short and it informs everything else.
2. **A full work week wearing the H10** for afferent. The failure modes it
   screens for are time-dependent — electrodes drying out over a sedentary
   afternoon, irritation accumulating over consecutive days. "Worked fine
   today" is not afferent passing.
3. **A full work week wearing the Verity Sense.** Same reason, different
   failure modes: armband slippage, whether it stays put under a sleeve, and
   whether the ~20 h charge cycle fits the day without a gap.

The sibling project resolves on a much shorter clock — one 45-minute session
tells it what it needs. Do not let afferent's week-long screen block it.

## Polar Verity Sense

Optical armband, rechargeable, ~20 h streaming per charge, magnetic clip
charger. Needs no conductive contact at all — just snug and not sliding — so
the entire dry-out problem class disappears. No wetting ritual, ever.

Optical's weakness is motion artifact, and afferent is a person sitting still at
a desk, so it holds up better here than the spec sheet implies. It is *not*
good enough for the sibling project's 4.0 ms RMSSD threshold.

Roughly $100 as of writing.

## Is PPI good enough for afferent's thresholds?

Yes for what afferent does, with one exclusion.

The Verity Sense reports **PPI** (peak-to-peak intervals from the pressure
wave), not **RR** (time between electrical depolarizations). Polar keeps the
terms distinct in its SDK because they are not the same measurement. PPI ships
with an error estimate and a blocker bit.

Jitter is roughly ±10 ms per interval at rest on a good armband. RMSSD is the
root mean square of *successive differences*, so independent per-beat noise
compounds. As a first-order model, measured ≈ √(true² + 2σ²):

| True RMSSD | Measured (σ = 10 ms) | Inflation |
|---|---|---|
| 40 ms | ~42 ms | 6% |
| 20 ms | ~24 ms | 22% |

The bias is state-dependent and always inflates, which compresses dynamic
range. A real 50% drop from 40 → 20 shows up as ~42%. The
`hrv_scattered_rmssd_drop_pct: 30` threshold in `config.yaml` still fires, but
with less headroom than the number implies — consider that when tuning.

That is a model, not a measurement, and it assumes per-beat independence. Some
of the error is correlated instead: pulse transit time moves systematically
with respiration.

**A single dropped or doubled beat costs more than the jitter.** RMSSD squares
successive differences, so one bad interval can dominate a 60-second window.
Gate windows on the PPI blocker bit and error estimate, and discard windows
with too many flagged intervals rather than computing on them.

**Skip frequency-domain HRV entirely from PPI.** The HF band is 0.15–0.4 Hz,
which is exactly where the jitter noise lives — LF/HF from an armband measures
the sensor.

It works for afferent because the question is a within-person trend: is this
person drifting from their own baseline over the day. Same body, same device,
same armband position, so most systematic error is a constant offset that
subtracts out. What PPI cannot give is a number comparable to a population
norm, to a Fenix, or to the H10.

Consider longer windows than 60 s for the RMSSD statistic — noise floor falls
with √N, and 5 minutes is the conventional resting window anyway.

## The comparison run — do this first

Both devices are on hand, so measure rather than trust the model above. Sit
still for 20 minutes wearing the H10 and the Verity Sense at once, log both R-R
and PPI series, and compare the 60-second RMSSD traces.

What it gives you:

- The actual per-interval jitter σ for this body and this armband position,
  replacing the assumed ±10 ms in the table above.
- Whether the inflation is state-dependent in the direction the model predicts,
  or whether correlated respiratory error dominates instead.
- A real number for the sibling project's 4.0 ms threshold, which was
  calibrated against Muse PPG and should shrink once the H10 supplies R-R —
  this run measures how far.
- A flag rate for the PPI blocker bit under genuinely sedentary conditions,
  which is what the windowing logic should gate on.

It slots into that project's existing gate structure and takes one sitting.
Run it before the week-long wear screens.

## Integration notes

Standard BLE Heart Rate Service (0x180D) with the RR-interval field on the H10,
readable directly with `bleak`. No vendor SDK for the basic path.

**The Verity Sense needs a one-time BLE bond before PMD/HR will stay
connected.** Confirmed 2026-09-05: a `bleak` connection would establish,
resolve services, and even get a successful PMD control-point ack for
starting the PPI stream, then drop ~1-3s later regardless of whether PMD was
touched at all (a plain HR-only subscribe disconnected too, faster).
`journalctl -u bluetooth` showed the actual cause: `src/device.c:new_auth()
No agent available for request type 2` / `device_confirm_passkey: Operation
not permitted` — the device requests LE bonding, and with no BlueZ pairing
agent registered, that request goes unanswered and the link gets torn down.
Registering an agent and pairing once (`bluetoothctl`: `agent
NoInputNoOutput`, `default-agent`, `scan on`, `pair <mac>`, `trust <mac>` —
see README) resolved it immediately, no PIN/passkey needed (silent "Just
Works"). This looked at first like the firmware-3.0.16 PMD regression
tracked in polarofficial/polar-ble-sdk#829 (HR keeps working, PMD/online
streaming silently fails) — it isn't; that issue is Android-specific
(`PolarNotificationNotEnabled`, PMD CCCD write itself rejected with GATT
status 1) and reproduces even with a bonded device. This project's failure
was BlueZ-specific and one layer earlier: no agent to complete bonding at
all. Once bonded, HR and PPI both stream cleanly (PPI error estimates
7-10ms, matching the ±10ms this doc predicted above).

Both devices share Polar's PMD/SDK-mode protocol — same service UUIDs, same
stream-request pattern, same offline-recording machinery, one open-source SDK
(`polarofficial/polar-ble-sdk`). Porting the poller between them is close to a
config change. What differs is the analog front end, and only the front end.

The H10 also exposes raw ECG at ~130 Hz; the Verity Sense exposes raw PPG plus
accelerometer. **For all-day afferent use, leave raw off** — SDK-mode raw
streaming burns considerably more than the ~20 h broadcast figure. Run HR
service plus PPI.

The H10 holds two concurrent BLE connections plus ANT+. **Do not use both.**
This project's poller and the sibling project's controller must not each
connect to the strap directly. This poller publishes to MQTT; the sibling
project subscribes instead. The broker already in `config.yaml` is the right
seam.

The sibling project's BLE path uses SimpleBLE over raw HCI while a `bleak`
poller uses BlueZ over D-Bus. Two stacks plus the Muse on one radio is where
to expect trouble — a cheap USB Bluetooth dongle as a second adapter is worth
having.

## Battery

H10 runs a CR2025 coin cell, on the order of 400 hours. At ten hours a day that
is roughly six weeks. Swap is a coin twist on the back; cells cost under a
dollar. Buy spares with the strap so a dead cell does not interrupt a screening
week.

Verity Sense is rechargeable Li-ion, ~20 h streaming, nightly charge.

The difference is forced by sensing physics, not packaging. An ECG differential
amplifier draws microamps; driving PPG LEDs into tissue draws milliamps.

## Naming cleanup

~~`README.md`'s architecture diagram said `[Garmin H10]`, and `config.yaml`
keyed off `garmin_hr` / `garmin_hrv`.~~ Fixed — Garmin makes the HRM-Dual,
Polar makes the H10; both now read `polar_hr` / `polar_hrv`.

## Devices considered and not bought

Garmin HRM-Dual — CR2032, very long battery, BLE + ANT+, broadcasts R-R. Fine,
but the H10 is better validated for HRV and has the raw ECG stream.

Fourth Frontier Frontier X2 — continuous ECG, rechargeable, built for long
sessions. More device than either project needs.

Bittium Faros 180 — research grade, adhesive electrodes so sweat never enters
the picture. Four figures.

Movesense Medical — programmable, sits between the two above.

Whoop — no usable real-time R-R over BLE.
