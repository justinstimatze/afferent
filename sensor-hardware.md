# Sensor hardware: HR and HRV devices

Notes on choosing a heart-rate device for afferent. The reasoning predates
measurement on this pipeline, and the error figures come from a model with no
measurement behind them, except where a sentence says otherwise. Spec figures
are from memory and not checked against a vendor datasheet.

## Devices

- **Polar Verity Sense** (optical armband, about $100). Rechargeable, about
  20 h streaming per charge. It needs no electrode contact, only a snug fit.
  This is what afferent's poller targets.
- **Polar H10** (chest strap). ECG-grade R-R intervals and raw ECG at about
  130 Hz. Runs on a CR2025 coin cell, on the order of 400 hours.

The H10 holds two concurrent BLE connections plus ANT+. Do not let two
programs connect to the same strap directly. If another tool needs the H10,
have this pipeline's poller publish to MQTT and let that tool subscribe.

## Chest strap vs armband for all-day wear

A chest strap does not sleep on motion. It powers down when it stops sensing
electrode contact, so sitting still at a desk keeps it connected. The real
risk is electrode dry-out during sedentary wear. It varies by person and
room: a cool air-conditioned room in a t-shirt is the bad case. Conductive
electrode gel (Signa Gel, Lectron II) lasts a workday where water does not.
Dried salt in the fabric also degrades the electrodes over weeks of unwashed
wear, and eight hours a day of chest strap is a comfort question. The armband has neither problem.

## Is PPI good enough for afferent's thresholds?

Yes, for within-person trends.

The Verity Sense reports PPI (peak-to-peak intervals of the pressure wave),
not RR (time between electrical depolarizations). Polar's SDK keeps the terms
apart because they are different measurements. PPI ships with an error
estimate and a blocker bit.

Jitter is about plus or minus 10 ms per interval at rest on a good armband.
RMSSD is the root mean square of successive differences, so independent
per-beat noise compounds. First-order model: measured is about
sqrt(true^2 + 2 * sigma^2).

| True RMSSD | Measured (sigma = 10 ms) | Inflation |
|---|---|---|
| 40 ms | about 42 ms | 6% |
| 20 ms | about 24 ms | 22% |

The bias always inflates and depends on state, which compresses dynamic range:
a real 50% drop from 40 to 20 appears as about 42%. The
`hrv_scattered_rmssd_drop_pct: 30` threshold in `config.yaml` still fires but
with less headroom than the number suggests. The model assumes independent
per-beat noise; some real error is correlated, since pulse transit time varies
with respiration.

One dropped or doubled beat costs more than jitter, because RMSSD squares
successive differences. Gate windows on the PPI blocker bit and error
estimate, and discard any window with many flagged intervals. The aggregator
does this.

Do not compute frequency-domain HRV from PPI. The HF band (0.15 to 0.4 Hz) is
where the jitter noise lives, so LF/HF from an armband measures the sensor.

PPI works here because the question is a within-person trend: is this person
drifting from their own baseline over the day. Same body, same device and same
armband position make most systematic error a constant offset. PPI cannot
give a number comparable to a population norm, another wearable, or an H10.
Longer windows help, since noise falls with the square root of the sample
count; 5 minutes is the conventional resting window.

## Measuring jitter on your own setup

To replace the assumed 10 ms with real numbers, sit still for 20 minutes
wearing the H10 and the Verity Sense together, log both R-R and PPI, and
compare 60-second RMSSD traces. That gives the actual per-interval jitter for
your body and armband position, whether the inflation follows the model, and
the blocker-bit flag rate under sedentary conditions.

## Integration notes

- The H10 exposes the standard BLE Heart Rate Service (0x180D) with an RR
  field, readable directly with `bleak`.
- **The Verity Sense needs a one-time BLE bond.** Without one, a `bleak`
  connection establishes, resolves services, and even acknowledges a PMD
  start, then drops after one to three seconds. `journalctl -u bluetooth`
  shows `No agent available for request type 2` and `device_confirm_passkey:
  Operation not permitted`: the device requests LE bonding, no BlueZ pairing
  agent answers, and the link is torn down. Registering an agent and pairing
  once fixes it with no passkey (see the README). This is separate from the
  Android-specific PMD regression in firmware 3.0.16
  (polarofficial/polar-ble-sdk#829), which also affects bonded devices.
  Once bonded, HR and PPI stream cleanly, with PPI error estimates of 7 to
  10 ms.
- Both devices use Polar's PMD protocol and the same open-source SDK
  (`polarofficial/polar-ble-sdk`), so porting the poller between them is
  close to a configuration change.
- The H10 also exposes raw ECG; the Verity Sense exposes raw PPG and
  accelerometer. For all-day use leave raw streaming off, which drains the
  battery much faster. Use the HR service plus PPI.
- `bleak` uses BlueZ over D-Bus. If another program on the same radio uses a
  different BLE stack, expect contention; a cheap USB Bluetooth dongle as a
  second adapter helps.

## Battery

The H10's coin cell is replaced by twisting the back off; cells cost under a
dollar. The Verity Sense is rechargeable and needs a nightly charge. The
difference follows from the sensing physics: an ECG amplifier draws
microamps, while driving PPG LEDs into tissue draws milliamps.

## Devices considered and not used

- Garmin HRM-Dual: long battery life, BLE and ANT+, broadcasts R-R. The H10 is
  better validated for HRV and has raw ECG.
- Fourth Frontier Frontier X2: continuous ECG, built for long sessions.
- Bittium Faros 180: research grade with adhesive electrodes; very expensive.
- Movesense Medical: programmable, between the two above.
- Whoop: no usable real-time R-R over BLE.
