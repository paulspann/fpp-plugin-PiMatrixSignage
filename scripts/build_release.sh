#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VERSION="$(tr -d '[:space:]' < "$ROOT_DIR/payload/PiMatrixSignage/VERSION")"
OUTPUT="${1:-$ROOT_DIR/dist/PiMatrixSignage-v${VERSION}.zip}"
TEMP_DIR="$(mktemp -d)"
TEMP_ZIP="$TEMP_DIR/PiMatrixSignage-v${VERSION}.zip"
trap 'rm -rf "$TEMP_DIR"' EXIT

mkdir -p "$(dirname "$OUTPUT")"

(
  cd "$ROOT_DIR"
  find . \
    -path './.git' -prune -o \
    -path './dist' -prune -o \
    -path './.pytest_cache' -prune -o \
    -path '*/__pycache__' -prune -o \
    -name '*.pyc' -prune -o \
    -name '.DS_Store' -prune -o \
    -type f -print \
    | LC_ALL=C sort \
    | zip -q "$TEMP_ZIP" -@
)

unzip -tq "$TEMP_ZIP"

for executable in \
  scripts/fpp_install.sh \
  scripts/fpp_uninstall.sh \
  payload/PiMatrixSignage/install.sh \
  payload/PiMatrixSignage/uninstall.sh \
  payload/PiMatrixSignage/start-local.sh; do
  zipinfo -l "$TEMP_ZIP" | grep -E "^-rwx[^ ]* .* ${executable}$" > /dev/null || {
    echo "Release validation failed: $executable is not executable in the ZIP" >&2
    exit 1
  }
done

ARCHIVE_VERSION="$(unzip -p "$TEMP_ZIP" payload/PiMatrixSignage/VERSION | tr -d '[:space:]')"
if [[ "$ARCHIVE_VERSION" != "$VERSION" ]]; then
  echo "Release validation failed: expected version $VERSION, found $ARCHIVE_VERSION" >&2
  exit 1
fi

mv "$TEMP_ZIP" "$OUTPUT"
echo "$OUTPUT"
