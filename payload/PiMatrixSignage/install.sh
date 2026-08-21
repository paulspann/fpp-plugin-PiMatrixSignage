#!/usr/bin/env bash
set -euo pipefail

APP_NAME="Pi Matrix Signage"
DEST="/home/fpp/media/pi-matrix-signage"
PERSIST="/home/fpp/media/pi-matrix-signage-data"
SERVICE="pi-matrix-signage.service"
UPGRADE_HELPER="/usr/local/sbin/pi-matrix-signage-upgrade"
SUDOERS_FILE="/etc/sudoers.d/pi-matrix-signage"
POWER_HELPER="/usr/local/sbin/pi-matrix-signage-poweroff"
RESET_HELPER="/usr/local/sbin/pi-matrix-signage-reset"
PLATFORM_HELPER="/usr/local/sbin/pi-matrix-signage-platform"
APPLIANCE_CONF="/etc/apache2/conf-available/pi-matrix-signage-appliance.conf"
APPLIANCE_ENTRY="/opt/fpp/www/pimatrix-appliance.php"
MODE_FILE="$PERSIST/interface-mode"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ ${EUID} -ne 0 ]]; then
  echo "Please run this installer with sudo: sudo ./install.sh"
  exit 1
fi
if ! id fpp >/dev/null 2>&1; then
  echo "The 'fpp' user was not found. This installer is intended for Falcon Player (FPP)."
  exit 1
fi

echo "==> Installing ${APP_NAME}"
if [[ "${PIMATRIX_SKIP_DEPENDENCY_INSTALL:-0}" == "1" ]]; then
  echo "==> Dependency installation already handled by the FPP Plugin Manager"
else
  echo "==> Installing Python support packages"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y python3 python3-flask python3-pil python3-cryptography fonts-dejavu-core fonts-liberation2 ca-certificates ffmpeg libegl1 libgl1 libgles2 gpiod
fi

mkdir -p "$DEST" "$PERSIST/data" "$PERSIST/uploads/images" "$PERSIST/uploads/fonts" "$PERSIST/uploads/videos" "$PERSIST/uploads/video-src" "$PERSIST/uploads/shaders" /home/fpp/media/logs

# Commercial licensing is configured outside the replaceable application folder.
# Existing keys, signed entitlements, endpoints and device data remain persistent.
if [[ ! -f "$PERSIST/license.env" ]]; then
  cat > "$PERSIST/license.env" <<'EOF'
PIMATRIX_LICENSE_MODE=whmcs
PIMATRIX_LICENSE_PREFIX=PMS-
PIMATRIX_LICENSE_CHECK_HOURS=168
PIMATRIX_LICENSE_GRACE_DAYS=30
PIMATRIX_LICENSE_ENDPOINT=https://www.issl.co.uk/support/modules/addons/pimatrixlicensing/api.php
PIMATRIX_LICENSE_PUBLIC_KEY_URL=https://www.issl.co.uk/support/modules/addons/pimatrixlicensing/public-key.php
# Optional override; by default the public key is downloaded automatically to the data directory.
# PIMATRIX_LICENSE_PUBLIC_KEY=/home/fpp/media/pi-matrix-signage-data/data/license-public.pem
EOF
  chmod 0640 "$PERSIST/license.env"
elif grep -q '^PIMATRIX_LICENSE_MODE=development[[:space:]]*$' "$PERSIST/license.env"; then
  echo "==> Enabling live WHMCS licence enforcement"
  sed -i 's/^PIMATRIX_LICENSE_MODE=development[[:space:]]*$/PIMATRIX_LICENSE_MODE=whmcs/' "$PERSIST/license.env"
fi

# Copy application code while keeping persistent database/uploads outside the code folder.
if [[ "$SRC" != "$DEST" ]]; then
  echo "==> Copying application to $DEST"
  rm -rf "$DEST.new"
  mkdir -p "$DEST.new"
  (cd "$SRC" && tar --exclude='./data' --exclude='./uploads' --exclude='./.venv' --exclude='./__pycache__' -cf - .) | (cd "$DEST.new" && tar -xf -)
  rm -rf "$DEST.old"
  if [[ -d "$DEST" ]]; then mv "$DEST" "$DEST.old"; fi
  mv "$DEST.new" "$DEST"
  rm -rf "$DEST.old"
fi

chown -R fpp:fpp "$DEST" "$PERSIST"
install -m 0644 "$DEST/systemd/$SERVICE" "/etc/systemd/system/$SERVICE"
# Install the narrow, root-owned updater. The web service itself still runs as fpp.
install -o root -g root -m 0755 "$DEST/systemd/pi-matrix-signage-upgrade" "$UPGRADE_HELPER"
install -o root -g root -m 0755 "$DEST/systemd/pi-matrix-signage-poweroff" "$POWER_HELPER"
install -o root -g root -m 0755 "$DEST/systemd/pi-matrix-signage-reset" "$RESET_HELPER"
install -o root -g root -m 0755 "$DEST/systemd/pi-matrix-signage-platform" "$PLATFORM_HELPER"
printf 'fpp ALL=(root) NOPASSWD: %s, %s, %s, %s\n' "$UPGRADE_HELPER" "$POWER_HELPER" "$RESET_HELPER" "$PLATFORM_HELPER" > "$SUDOERS_FILE"
chmod 0440 "$SUDOERS_FILE"
rm -f /etc/sudoers.d/pi-matrix-signage-upgrade
if command -v visudo >/dev/null 2>&1; then
  visudo -cf "$SUDOERS_FILE" >/dev/null
fi
systemctl daemon-reload
# `enable --now` starts an inactive service but does not restart an already
# running one. During FPP Plugin Manager updates the old Python process would
# therefore keep serving the previous release from memory even after the files
# had been replaced. Always restart when already active so the new VERSION/code
# is actually loaded.
if systemctl is-active --quiet "$SERVICE"; then
  systemctl restart "$SERVICE"
else
  systemctl enable --now "$SERVICE"
fi

# Controller interface mode is persistent and deliberately defaults to FPP-first.
# Upgrade migration: v0.6.43 always enabled appliance mode, so if no persisted
# choice exists yet but the old Apache config is currently enabled, preserve
# appliance mode. A genuinely fresh install has neither and therefore starts in
# FPP-first add-on mode without taking over an existing FPP home page.
interface_mode=""
if [[ -f "$MODE_FILE" ]]; then
  interface_mode="$(tr -d '\r\n' < "$MODE_FILE")"
fi
if [[ "$interface_mode" != "fpp" && "$interface_mode" != "appliance" ]]; then
  if [[ -e /etc/apache2/conf-enabled/pi-matrix-signage-appliance.conf ]]; then
    interface_mode="appliance"
    echo "==> Preserving existing Pi Matrix Signage appliance mode"
  else
    interface_mode="fpp"
    echo "==> Defaulting controller interface to FPP-first add-on mode"
  fi
  printf '%s\n' "$interface_mode" > "$MODE_FILE"
  chown fpp:fpp "$MODE_FILE" 2>/dev/null || true
  chmod 0644 "$MODE_FILE"
fi

if [[ -d /opt/fpp/www && -d /etc/apache2/conf-available ]] && command -v a2enconf >/dev/null 2>&1; then
  # Keep the appliance files installed even while disabled so switching modes
  # later is instantaneous and does not require a plugin reinstall.
  install -o root -g root -m 0644 "$DEST/systemd/pimatrix-appliance.php" "$APPLIANCE_ENTRY"
  install -o root -g root -m 0644 "$DEST/systemd/pi-matrix-signage-appliance.conf" "$APPLIANCE_CONF"
  if [[ "$interface_mode" == "appliance" ]]; then
    echo "==> Enabling Pi Matrix Signage appliance mode"
    a2enconf pi-matrix-signage-appliance >/dev/null
  else
    echo "==> Keeping FPP as the main controller interface"
    a2disconf pi-matrix-signage-appliance >/dev/null 2>&1 || true
  fi
  if apache2ctl configtest >/dev/null 2>&1; then
    systemctl reload apache2
  else
    echo "WARNING: Apache configuration failed validation; falling back to FPP-first mode"
    a2disconf pi-matrix-signage-appliance >/dev/null 2>&1 || true
    printf 'fpp\n' > "$MODE_FILE"
    chown fpp:fpp "$MODE_FILE" 2>/dev/null || true
    chmod 0644 "$MODE_FILE"
    apache2ctl configtest >/dev/null 2>&1 || true
  fi
else
  echo "WARNING: Apache/FPP web root not found; Pi Matrix remains available on port 8090"
fi

sleep 1
if systemctl is-active --quiet "$SERVICE"; then
  IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
  echo
  echo "SUCCESS: ${APP_NAME} is running."
  if [[ "$interface_mode" == "appliance" ]]; then
    echo "Controller home (Pi Matrix appliance): http://${IP:-fpp.local}/"
  else
    echo "Controller home (FPP): http://${IP:-fpp.local}/"
  fi
  echo "Pi Matrix Signage: http://${IP:-fpp.local}:8090"
  echo
  echo "Initial login on a new/migrated user database: admin / pimatrix"
  echo "The web interface requires that default password to be changed immediately."
  echo
  echo "Next: sign in to Pi Matrix Signage and use Display Setup. Controller → Interface lets you choose FPP-first or dedicated appliance mode at any time."
else
  echo
  echo "The service did not start. Recent log output:"
  journalctl -u "$SERVICE" -n 40 --no-pager || true
  exit 1
fi
