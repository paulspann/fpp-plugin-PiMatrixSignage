#!/bin/bash
set -euo pipefail
# Plugin updates are idempotent; the installer upgrades the bundled app only
# when the payload is newer and never downgrades an app updated independently.
"$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/fpp_install.sh"
