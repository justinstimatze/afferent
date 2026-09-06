# Security Policy

If you discover a security vulnerability, please email justin@justinstimatze.com directly rather than opening a public issue or PR.

I'll acknowledge receipt within 7 days and aim to provide an initial assessment within 30 days. We can coordinate on a disclosure timeline — defaulting to 90 days from initial report unless circumstances warrant otherwise.

Thanks for helping keep this project and its users safe.

## What `keystroke_poller.py` does — and does not do — with your keystrokes

`keystroke_poller.py` reads raw keyboard events from `/dev/input/event*`. It
is gated by `config.yaml`'s `keystroke.enabled` -- on by default since
2026-09-06, once the dedicated-account setup below was proven end to end;
set it `false` if you don't want your keyboard read at all. It is **not** a
keylogger:

- It inspects only whether an event is a key *press* and whether that key is
  backspace. The scancode of every other key is read off the wire but never
  stored, published, or logged -- traced end to end in `_reduce_event`
  (`src/afferent/keystroke_poller.py`).
- It publishes only `{is_backspace, dt_ms, ts}` to the local MQTT broker --
  never a keycode, never the literal keys typed.
- It writes nothing to disk itself and opens no files for writing.
- It makes only the one MQTT connection to the configured broker (default
  `localhost:1883`) -- no other network activity.

All of this is verifiable directly in `src/afferent/keystroke_poller.py` --
short enough to read end to end rather than take this file's word for it.

## The `input` group is a real, permanent grant — know what you enable

Enabling `keystroke.enabled: true` requires your account (or a dedicated
service account -- see below) to be in the `input` group:

```sh
sudo usermod -aG input "$USER"
```

**This grants every process that account runs -- not just this poller --
read access to every `/dev/input` device: raw keystrokes system-wide, for
the life of the account.** It is not scoped to `keystroke_poller.py`, and
disabling `keystroke.enabled` in `config.yaml` does **not** revoke it. To
revoke:

```sh
sudo gpasswd -d "$USER" input
```

This constraint is inherent to how Linux's evdev layer grants access -- it
is not something this project's code can narrow further at the point of
reading the device. (A public sibling project, flock, reads the same way
and states the same limit in its own `SECURITY.md`.)

**Recommended: run it under a dedicated account instead of your own.**
`scripts/setup-keystroke-service-account.sh` (run with `sudo`) creates a
narrow, login-less system account that's the only thing in `input`, and
installs a hardened systemd unit (`systemd/afferent-keystroke.service.template`)
to run the poller under it -- confined to `NoNewPrivileges`, a read-only
view of the filesystem outside this repo, and `IPAddressAllow` restricted
to loopback (the MQTT-reachable analog of flock's own
`RestrictAddressFamilies=AF_UNIX`). With this in place, an arbitrary
process running under *your own* login no longer gains keystroke-reading
capability just because this signal is enabled -- it would have to
compromise the dedicated account specifically, which runs nothing else.
This still doesn't change the underlying OS fact above; it changes *whose*
account carries it.
