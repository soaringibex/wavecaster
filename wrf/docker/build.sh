#!/usr/bin/env bash
# Build the WRF/WPS image for linux/arm64 (this MacBook). Long step → caffeinate.
set -euo pipefail
cd "$(dirname "$0")"

CAFFEINATE=""
if command -v caffeinate >/dev/null 2>&1; then
  CAFFEINATE="caffeinate -i"
fi

# shellcheck disable=SC2086
$CAFFEINATE docker build --platform linux/arm64 -t mtw-wrf:4.6.1 .
