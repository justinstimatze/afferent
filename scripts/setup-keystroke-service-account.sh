#!/usr/bin/env bash
# setup-keystroke-service-account.sh -- creates a dedicated, unprivileged
# system account for keystroke_poller.py, so the `input` group grant (raw
# keyboard read, system-wide -- see SECURITY.md) is scoped to one narrow
# account that runs nothing else, instead of your own interactive login.
#
# Run with sudo. Idempotent -- safe to re-run.
#
# Does NOT remove your own account from `input`. flock also currently
# needs it there (it runs as you via its own user systemd unit, to reach
# your PipeWire session) -- revoking your account's membership is a
# separate, manual step this script prints at the end, once you've decided
# whether/how flock migrates too.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Run with sudo: sudo $0" >&2
  exit 1
fi

SERVICE_USER="raw-input"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TRAVERSE_DIR="$(dirname "$(dirname "$REPO_DIR")")"  # the account's home dir, e.g. /home/gas6amus

if ! id -u "$SERVICE_USER" &>/dev/null; then
  useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
  echo "Created system account: $SERVICE_USER"
else
  echo "System account $SERVICE_USER already exists, reusing it."
fi

usermod -aG input "$SERVICE_USER"
echo "Added $SERVICE_USER to the input group."

if command -v setfacl &>/dev/null; then
  # Execute-only, no read: lets the service account traverse through your
  # home directory to reach the repo without being able to list anything
  # else in it. Everything below (Documents/, the repo dir, .venv, and the
  # uv-managed interpreter under .local/share/uv) is already world-
  # readable+executable, so this one ACL entry is the only gap.
  setfacl -m "u:${SERVICE_USER}:x" "$TRAVERSE_DIR"
  echo "Granted $SERVICE_USER execute-only (traversal) access to $TRAVERSE_DIR."
else
  echo "WARNING: setfacl not found (install the 'acl' package) -- $SERVICE_USER" >&2
  echo "cannot traverse into $TRAVERSE_DIR yet and the service will fail to start" >&2
  echo "until you grant it execute access some other way." >&2
fi

UNIT_SRC="$REPO_DIR/systemd/afferent-keystroke.service.template"
UNIT_DST="/etc/systemd/system/afferent-keystroke.service"
sed -e "s|__SERVICE_USER__|$SERVICE_USER|g" -e "s|__REPO_DIR__|$REPO_DIR|g" "$UNIT_SRC" > "$UNIT_DST"
echo "Installed $UNIT_DST"

systemctl daemon-reload
echo
echo "Next steps:"
echo "  1. Confirm keystroke.enabled: true in $REPO_DIR/config.yaml (opt-in, off by default)."
echo "  2. Confirm the MQTT broker is up: docker compose -f $REPO_DIR/docker-compose.yml up -d"
echo "  3. systemctl enable --now afferent-keystroke.service"
echo "  4. systemctl status afferent-keystroke.service   # confirm it's running as $SERVICE_USER"
echo "  5. journalctl -u afferent-keystroke.service -f   # watch for MQTT connect, no errors"
echo
if [ -n "${SUDO_USER:-}" ]; then
  echo "This script did NOT remove $SUDO_USER from the input group -- flock still"
  echo "needs it there today. Once you've decided flock's future, revoke it with:"
  echo "  sudo gpasswd -d $SUDO_USER input"
  echo "(then log out and back in for it to take effect)."
fi
