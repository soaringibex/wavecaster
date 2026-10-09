#!/usr/bin/env bash
# Build the WRF/WPS image for THIS host's architecture (arm64 MacBook,
# x86_64 Linux server). Uses docker when present, else rootless podman —
# no emulation on either. Long step → caffeinate when the host has it.
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

# Compiler parallelism: use physical cores where we can tell (SMT siblings
# would just oversubscribe the WRF module compiles), and fall back to nproc /
# sysctl / 8. The Dockerfile's RUN steps get this via BUILD_JOBS.
JOBS=8
if command -v nproc >/dev/null 2>&1; then
  JOBS=$(nproc)
  if command -v lscpu >/dev/null 2>&1; then
    PHYS=$(lscpu -p=Core,Socket 2>/dev/null | grep -v '^#' | sort -u | wc -l)
    [ "${PHYS:-0}" -gt 0 ] && JOBS=$PHYS
  fi
else
  JOBS=$(sysctl -n hw.physicalcpu 2>/dev/null || echo 8)
fi

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  ENGINE=docker
  FORMAT_FLAGS=""
elif command -v podman >/dev/null 2>&1; then
  ENGINE=podman
  # Podman defaults to the OCI image format, which ignores the Dockerfile's
  # SHELL instruction — the compile steps need bash (pipefail). Docker format.
  FORMAT_FLAGS="--format docker"
else
  echo "no container engine found (need docker or podman)" >&2
  exit 1
fi

echo "building mtw-wrf:4.6.1 for ${PLATFORM} with ${ENGINE} (-j ${JOBS})"
# shellcheck disable=SC2086
$CAFFEINATE "$ENGINE" build $FORMAT_FLAGS --platform "$PLATFORM" \
  --build-arg BUILD_JOBS="$JOBS" -t mtw-wrf:4.6.1 .
