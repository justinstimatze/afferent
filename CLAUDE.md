# afferent

Read `README.md` for setup, `ambient-context-design.md` for design rationale
and open questions, `sensor-hardware.md` for HR/HRV device details.

## Before assuming hardware state

Nothing in this repo should hardcode live physical state, so check rather
than assume:
- `ls /dev/ttyACM* /dev/ttyUSB*` — is the sensor board actually plugged in?
  Identify it by USB vendor:product ID (see `config.yaml`'s `co2_sensor`
  block), not a specific device name — that's not stable across reboots.
- `docker ps` — is the MQTT broker running? It isn't by default; start it per
  the README before expecting the poller to publish anywhere.

## Quality gate

`make check` (mypy --strict + ruff + pytest) must pass before a change counts
as done — enforced by CI and by a local pre-commit hook (the hook isn't part
of the clone; CI is the gate a fresh clone actually gets for free).

## What not to do

Never name this repo's private sibling projects (the ones it was split out
of, or is meant to interoperate with) by name in committed files — generalize
to "a sibling project" instead. Check a project's actual GitHub visibility
before assuming; several referenced here were confirmed private only once
actually checked.
