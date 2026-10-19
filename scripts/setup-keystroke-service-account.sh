#!/usr/bin/env bash
# setup-keystroke-service-account.sh -- creates a dedicated, unprivileged
# system account for keystroke_poller.py, so the `input` group grant (raw
# keyboard read, system-wide -- see SECURITY.md) is scoped to one narrow
# account that runs nothing else, instead of your own interactive login.
#
# Run with sudo. Idempotent -- safe to re-run.
#
# Does NOT change your own account's groups. If you are in `input` today,
# revoking it is a separate, manual step this script prints at the end.
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "Run with sudo: sudo $0" >&2
  exit 1
fi

SERVICE_USER="raw-input"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! id -u "$SERVICE_USER" &>/dev/null; then
  useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
  echo "Created system account: $SERVICE_USER"
else
  echo "System account $SERVICE_USER already exists, reusing it."
fi

usermod -aG input "$SERVICE_USER"
echo "Added $SERVICE_USER to the input group."

# The service account must be able to traverse every parent directory of the
# repo (and of the uv-managed interpreter the .venv points at). Grant
# execute-only (no read, so it cannot list anything) on each parent that is
# not already world-executable, typically just your home directory.
PY_REAL="$(readlink -f "$REPO_DIR/.venv/bin/python" 2>/dev/null || true)"
missing_acl=0
for target in "$REPO_DIR" "$PY_REAL"; do
  [ -n "$target" ] || continue
  dir="$(dirname "$target")"
  while [ "$dir" != "/" ]; do
    if [ "$(stat -c %A "$dir" | cut -c10)" != "x" ] && [ "$(stat -c %A "$dir" | cut -c10)" != "t" ]; then
      if command -v setfacl &>/dev/null; then
        setfacl -m "u:${SERVICE_USER}:x" "$dir"
        echo "Granted $SERVICE_USER execute-only (traversal) access to $dir."
      else
        echo "WARNING: $dir is not world-executable and setfacl is missing" >&2
        missing_acl=1
      fi
    fi
    dir="$(dirname "$dir")"
  done
done
if [ "$missing_acl" -eq 1 ]; then
  echo "Install the 'acl' package and re-run, or the service will fail to start." >&2
fi

UNIT_SRC="$REPO_DIR/systemd/afferent-keystroke.service.template"
UNIT_DST="/etc/systemd/system/afferent-keystroke.service"
sed -e "s|__SERVICE_USER__|$SERVICE_USER|g" -e "s|__REPO_DIR__|$REPO_DIR|g" "$UNIT_SRC" > "$UNIT_DST"
echo "Installed $UNIT_DST"

systemctl daemon-reload
echo
echo "Next steps:"
echo "  1. Confirm keystroke.enabled: true in $REPO_DIR/config.yaml."
echo "  2. Confirm the MQTT broker is up: docker compose -f $REPO_DIR/docker-compose.yml up -d"
echo "  3. systemctl enable --now afferent-keystroke.service"
echo "  4. systemctl status afferent-keystroke.service   # confirm it's running as $SERVICE_USER"
echo "  5. journalctl -u afferent-keystroke.service -f   # watch for MQTT connect, no errors"
echo
if [ -n "${SUDO_USER:-}" ]; then
  echo "This script did not change $SUDO_USER's groups. If $SUDO_USER is in the"
  echo "input group and nothing else needs it, revoke it with:"
  echo "  sudo gpasswd -d $SUDO_USER input"
  echo "(then log out and back in for it to take effect)."
fi
