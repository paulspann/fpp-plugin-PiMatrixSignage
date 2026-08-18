#!/bin/bash
set -euo pipefail

FPPDIR="${FPPDIR:-/opt/fpp}"
if [[ -f "$FPPDIR/scripts/common" ]]; then
  # FPP-provided paths/helpers (MEDIADIR, settings, logging location).
  . "$FPPDIR/scripts/common"
fi

PLUGIN_NAME="fpp-plugin-PiMatrixSignage"
PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PAYLOAD="$PLUGIN_DIR/payload/PiMatrixSignage"
APP_DIR="/home/fpp/media/pi-matrix-signage"
LOG_DIR="${MEDIADIR:-/home/fpp/media}/logs"
LOG_FILE="$LOG_DIR/plugin-${PLUGIN_NAME}.log"

mkdir -p "$LOG_DIR"
touch "$LOG_FILE"
chown fpp:fpp "$LOG_FILE" 2>/dev/null || true
exec >>"$LOG_FILE" 2>&1

echo "[$(date -Is)] Pi Matrix Signage plugin install started"

if [[ ! -f "$PAYLOAD/VERSION" || ! -x "$PAYLOAD/install.sh" ]]; then
  echo "Plugin payload is incomplete"
  exit 1
fi

payload_version="$(tr -d '[:space:]' < "$PAYLOAD/VERSION")"
installed_version=""
if [[ -f "$APP_DIR/VERSION" ]]; then
  installed_version="$(tr -d '[:space:]' < "$APP_DIR/VERSION")"
fi

echo "Payload version: $payload_version"
echo "Installed version: ${installed_version:-none}"

should_install=1
if [[ -n "$installed_version" ]]; then
  newest="$(printf '%s\n%s\n' "$installed_version" "$payload_version" | sort -V | tail -n1)"
  if [[ "$newest" == "$installed_version" && "$installed_version" != "$payload_version" ]]; then
    echo "Installed application is newer than plugin payload; not downgrading"
    should_install=0
  fi
fi

if [[ "$should_install" == "1" ]]; then
  PIMATRIX_SKIP_DEPENDENCY_INSTALL=1 "$PAYLOAD/install.sh"
fi

if ! systemctl is-active --quiet pi-matrix-signage.service; then
  echo "Pi Matrix Signage service is not active after installation"
  journalctl -u pi-matrix-signage.service -n 60 --no-pager || true
  exit 1
fi

# Confirm the HTTP health endpoint becomes available.
ok=0
for _ in $(seq 1 20); do
  if curl -fsS --max-time 2 http://127.0.0.1:8090/health >/dev/null 2>&1; then
    ok=1
    break
  fi
  sleep 1
done
if [[ "$ok" != "1" ]]; then
  echo "Pi Matrix Signage did not pass the post-install health check"
  journalctl -u pi-matrix-signage.service -n 60 --no-pager || true
  exit 1
fi

echo "[$(date -Is)] Pi Matrix Signage plugin install completed successfully"
exit 0
