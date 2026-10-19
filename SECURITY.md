# Security Policy

If you discover a security vulnerability, please email justin@justinstimatze.com directly rather than opening a public issue or PR.

I'll acknowledge receipt within 7 days and aim to provide an initial assessment within 30 days. We can coordinate on a disclosure timeline — defaulting to 90 days from initial report unless circumstances warrant otherwise.

Thanks for helping keep this project and its users safe.

## What `keystroke_poller.py` does with your keystrokes

`keystroke_poller.py` reads raw keyboard events from `/dev/input/event*`. It
is gated by `keystroke.enabled` in `config.yaml`, which is `false` in the
shipped file, so the poller exits at startup unless you turn it on. The poller
cannot open any device unless its account is in the `input` group (see
below). It is not a keylogger:

- It checks only whether an event is a key press and whether that key is
  backspace. The scancode of every other key is read and discarded; it is
  never stored, published or logged (see `_reduce_event` in
  `src/afferent/keystroke_poller.py`).
- It publishes `{is_backspace, dt_ms, ts}` to the local MQTT broker: a
  backspace flag, the milliseconds since the previous key press, and a
  timestamp. It never publishes a keycode or typed text.
- It writes nothing to disk and opens no files for writing.
- Its only network activity is one MQTT connection to the configured broker
  (default `localhost:1883`).

The guarantee has limits. Inter-key timing is published for every key press,
and timing patterns can carry some information about what was typed
(keystroke-dynamics research uses it to identify typists). The broker allows
anonymous connections on loopback, so any local user or process can subscribe
to `sensors/keystroke`. On a machine with other users, add a `password_file`
to `mosquitto.conf` first.

You can check all of this in `src/afferent/keystroke_poller.py`, which is short
enough to read end to end.

## The `input` group grants broad access

Reading `/dev/input` requires your account, or a dedicated service account
(see below), to be in the `input` group:

```sh
sudo usermod -aG input "$USER"
```

**This gives every process that account runs, not just this poller, read
access to every `/dev/input` device: raw keystrokes system-wide, for as long
as the membership lasts.** Setting `keystroke.enabled: false` does not revoke
it. To revoke:

```sh
sudo gpasswd -d "$USER" input
```

Linux's evdev layer grants access this way, and this project's code cannot
narrow it at the point of reading the device.

**Recommended: run the poller under a dedicated account.**
`scripts/setup-keystroke-service-account.sh` (run with `sudo`) creates a
login-less system account that is the only member of `input`, and installs a
systemd unit (`systemd/afferent-keystroke.service.template`) that runs the
poller under it. The unit sets `NoNewPrivileges`, an empty capability set,
a read-only view of the filesystem, and `IPAddressAllow` limited to loopback.
With this in place, an arbitrary process running under your own login does not
gain keystroke access just because this signal is enabled; it would have to
compromise the dedicated account, which runs nothing else. The OS-level grant
still exists. It moves to a different account.

## Other data at rest

The aggregator writes `state.json` and `hrv_baseline.json` under
`$XDG_STATE_HOME/afferent/` (default `~/.local/state/afferent/`) with directory
mode `0700` and file mode `0600`. `make run-*` logs go to `logs/` with the same
modes; `--verbose` adds raw per-beat heart data to those logs.
