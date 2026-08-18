#!/bin/bash
set -euo pipefail

FPPDIR="${FPPDIR:-/opt/fpp}"
if [[ -f "$FPPDIR/scripts/common" ]]; then
  # FPP-provided paths/helpers (MEDIADIR, settings, logging location).
  . "$FPPDIR/scripts/common"
fi
PLUGIN_NAME="fpp-plugin-PiMatrixSignage"
APP_DIR="/home/fpp/media/pi-matrix-signage"
LOG_DIR="${MEDIADIR:-/home/fpp/media}/logs"
LOG_FILE="$LOG_DIR/plugin-${PLUGIN_NAME}.log"
mkdir -p "$LOG_DIR"
exec >>"$LOG_FILE" 2>&1

echo "[$(date -Is)] Pi Matrix Signage plugin uninstall started"
if [[ -x "$APP_DIR/uninstall.sh" ]]; then
  "$APP_DIR/uninstall.sh"
else
  systemctl disable --now pi-matrix-signage.service 2>/dev/null || true
  rm -f /etc/systemd/system/pi-matrix-signage.service
  rm -f /usr/local/sbin/pi-matrix-signage-upgrade /usr/local/sbin/pi-matrix-signage-poweroff
  rm -f /etc/sudoers.d/pi-matrix-signage /etc/sudoers.d/pi-matrix-signage-upgrade
  systemctl daemon-reload
  rm -rf "$APP_DIR"
fi

echo "Saved Pi Matrix user data remains in /home/fpp/media/pi-matrix-signage-data for recovery/reinstall."
echo "[$(date -Is)] Pi Matrix Signage plugin uninstall completed"
exit 0
