# afferent

`README.md` covers setup, `ambient-context-design.md` the design rationale and
open questions, and `sensor-hardware.md` the HR/HRV device details.

## Before assuming hardware state

Check hardware state instead of hardcoding it:

- `ls /dev/ttyACM* /dev/ttyUSB*` shows whether the sensor board is plugged in.
  Identify it by USB vendor:product ID (the `co2_sensor` block in
  `config.yaml`), since the device name changes across reboots.
- `docker ps` shows whether the MQTT broker is running. It does not start on
  its own; use `docker compose up -d`.

## Quality gate

`make check` (mypy --strict, ruff, pytest) must pass before a change is done.
CI runs the same command.

## Privacy rules

- The keystroke poller must publish only `{is_backspace, dt_ms, ts}`. Never
  add a keycode, key name or typed character to a publish call or a log line.
- Do not commit sensor logs, state snapshots or baseline files; they are
  biometric data.
- Keep the MQTT broker bound to loopback.
