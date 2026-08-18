#!/usr/bin/env bash
set -euo pipefail
if [[ ${EUID} -ne 0 ]]; then echo "Run with sudo: sudo ./uninstall.sh"; exit 1; fi
systemctl disable --now pi-matrix-signage.service 2>/dev/null || true
rm -f /etc/systemd/system/pi-matrix-signage.service
rm -f /usr/local/sbin/pi-matrix-signage-upgrade /usr/local/sbin/pi-matrix-signage-poweroff
rm -f /etc/sudoers.d/pi-matrix-signage /etc/sudoers.d/pi-matrix-signage-upgrade
systemctl daemon-reload
rm -rf /home/fpp/media/pi-matrix-signage
cat <<'MSG'
Pi Matrix Signage has been removed.
Your messages, schedules, fonts and images were deliberately kept in:
  /home/fpp/media/pi-matrix-signage-data
Delete that folder manually only if you want to erase the saved content as well.
MSG
