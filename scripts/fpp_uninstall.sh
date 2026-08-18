#!/bin/bash
set -euo pipefail

# This uninstall hook must remain self-contained.  Do not source
# /opt/fpp/scripts/common here: some FPP releases reference optional shell
# variables such as LD_LIBRARY_PATH and abort when the plugin uses `set -u`.
MEDIADIR="${MEDIADIR:-/home/fpp/media}"
PLUGIN_NAME="fpp-plugin-PiMatrixSignage"
APP_DIR="/home/fpp/media/pi-matrix-signage"
PERSIST_DIR="/home/fpp/media/pi-matrix-signage-data"
SERVICE="pi-matrix-signage.service"
LOG_DIR="$MEDIADIR/logs"
LOG_FILE="$LOG_DIR/plugin-${PLUGIN_NAME}.log"

mkdir -p "$LOG_DIR"
touch "$LOG_FILE"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "[$(date -Is)] Pi Matrix Signage plugin uninstall started"

# Stop the running application first.  Do not delegate to APP_DIR/uninstall.sh:
# the application tree is replaceable and may be missing/partially updated.
systemctl disable --now "$SERVICE" 2>/dev/null || true
systemctl stop "$SERVICE" 2>/dev/null || true

# If a stale process somehow survived systemd removal, terminate only the exact
# Pi Matrix application command line before deleting the application directory.
if pgrep -f '/home/fpp/media/pi-matrix-signage/app.py' >/dev/null 2>&1; then
  pkill -TERM -f '/home/fpp/media/pi-matrix-signage/app.py' 2>/dev/null || true
  sleep 1
fi

rm -f "/etc/systemd/system/$SERVICE"
rm -f /usr/local/sbin/pi-matrix-signage-upgrade /usr/local/sbin/pi-matrix-signage-poweroff
rm -f /etc/sudoers.d/pi-matrix-signage /etc/sudoers.d/pi-matrix-signage-upgrade
systemctl daemon-reload
systemctl reset-failed "$SERVICE" 2>/dev/null || true
rm -rf "$APP_DIR"

# Do not claim success unless the replaceable application is really gone and
# the service/process is no longer running.
if systemctl is-active --quiet "$SERVICE" 2>/dev/null; then
  echo "ERROR: $SERVICE is still active after uninstall"
  exit 1
fi
if pgrep -f '/home/fpp/media/pi-matrix-signage/app.py' >/dev/null 2>&1; then
  echo "ERROR: Pi Matrix Signage process is still running after uninstall"
  exit 1
fi
if [[ -e "$APP_DIR" ]]; then
  echo "ERROR: Pi Matrix Signage application directory still exists: $APP_DIR"
  exit 1
fi

echo "Pi Matrix Signage application and service removed successfully."
echo "Saved messages, schedules, media and licence data remain in $PERSIST_DIR for reinstall/recovery."
echo "[$(date -Is)] Pi Matrix Signage plugin uninstall completed"
exit 0
