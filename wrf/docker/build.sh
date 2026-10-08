#!/usr/bin/env bash
# Build the WRF/WPS image for THIS host's architecture (arm64 MacBook today,
# x86_64 Linux server for camp). Long step → caffeinate when the host has it.
set -euo pipefail
cd "$(dirname "$0")"

CAFFEINATE=""
if command -v caffeinate >/dev/null 2>&1; then
  CAFFEINATE="caffeinate -i"
fi

case "$(uname -m)" in
  arm64|aarch64) PLATFORM=linux/arm64 ;;
  x86_64|amd64)  PLATFORM=linux/amd64 ;;
  *) echo "unsupported host arch: $(uname -m)" >&2; exit 1 ;;
esac

echo "building mtw-wrf:4.6.1 for ${PLATFORM}"
# shellcheck disable=SC2086
$CAFFEINATE docker build --platform "$PLATFORM" -t mtw-wrf:4.6.1 .
