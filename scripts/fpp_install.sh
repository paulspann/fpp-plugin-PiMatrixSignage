#!/bin/bash
set -euo pipefail

# Keep the plugin scripts self-contained.  Sourcing FPP's scripts/common under
# `set -u` is unsafe on some FPP builds because common may reference optional
# environment variables (for example LD_LIBRARY_PATH) before defining them.
MEDIADIR="${MEDIADIR:-/home/fpp/media}"

PLUGIN_NAME="fpp-plugin-PiMatrixSignage"
PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PAYLOAD="$PLUGIN_DIR/payload/PiMatrixSignage"
APP_DIR="/home/fpp/media/pi-matrix-signage"
LOG_DIR="${MEDIADIR:-/home/fpp/media}/logs"
LOG_FILE="$LOG_DIR/plugin-${PLUGIN_NAME}.log"

mkdir -p "$LOG_DIR"
touch "$LOG_FILE"
chown fpp:fpp "$LOG_FILE" 2>/dev/null || true
exec > >(tee -a "$LOG_FILE") 2>&1

echo "[$(date -Is)] Pi Matrix Signage plugin install started"

if [[ ! -f "$PAYLOAD/VERSION" || ! -f "$PAYLOAD/install.sh" ]]; then
  echo "ERROR: Plugin payload is incomplete (missing VERSION or install.sh)"
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

expected_version="$installed_version"
if [[ "$should_install" == "1" ]]; then
  PIMATRIX_SKIP_DEPENDENCY_INSTALL=1 bash "$PAYLOAD/install.sh"
  expected_version="$payload_version"
fi

if ! systemctl is-active --quiet pi-matrix-signage.service; then
  echo "Pi Matrix Signage service is not active after installation"
  journalctl -u pi-matrix-signage.service -n 60 --no-pager || true
  exit 1
fi

# Confirm the HTTP health endpoint becomes available *and* that the running
# process loaded the version we just installed. A merely healthy old process
# must not make a Plugin Manager update look successful.
ok=0
running_version=""
for _ in $(seq 1 25); do
  health_json="$(curl -fsS --max-time 2 http://127.0.0.1:8090/health 2>/dev/null || true)"
  if [[ -n "$health_json" ]]; then
    running_version="$(printf '%s' "$health_json" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("version", ""))' 2>/dev/null || true)"
    if [[ -n "$running_version" && "$running_version" == "$expected_version" ]]; then
      ok=1
      break
    fi
  fi
  sleep 1
done
if [[ "$ok" != "1" ]]; then
  echo "Pi Matrix Signage did not pass the post-install version health check"
  echo "Expected running version: ${expected_version:-unknown}"
  echo "Reported running version: ${running_version:-none}"
  echo "Disk version: $(tr -d '[:space:]' < "$APP_DIR/VERSION" 2>/dev/null || echo missing)"
  systemctl show -p FragmentPath -p ExecStart -p WorkingDirectory pi-matrix-signage.service || true
  journalctl -u pi-matrix-signage.service -n 60 --no-pager || true
  exit 1
fi

echo "Running application version verified: $running_version"
echo "[$(date -Is)] Pi Matrix Signage plugin install completed successfully"
exit 0
