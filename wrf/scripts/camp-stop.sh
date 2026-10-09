#!/bin/bash
# Camp mode OFF. macOS: unload the launchd schedule and restore the sleep
# settings camp-start.sh replaced (from wrf/out/camp-pmset.saved). Linux:
# disable the systemd user timer (a live cycle, if any, keeps running).
#
#   wrf/scripts/camp-stop.sh
#
# Prints every change it makes. macOS pmset needs root (password prompt).
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

if [ "$(uname)" = "Linux" ]; then
  echo "== camp-stop =="
  if ! command -v systemctl >/dev/null 2>&1; then
    echo "camp-stop.sh: no systemctl on this host" >&2
    exit 1
  fi
  systemctl --user disable --now wavecaster.timer \
    && echo "disabled: wavecaster.timer" \
    || echo "wavecaster.timer was not enabled"
  systemctl --user list-timers wavecaster.timer --no-pager 2>/dev/null | sed 's/^/  /'
  echo "camp mode OFF — no further fires until camp-start.sh runs again."
  exit 0
fi

if [ "$(uname)" != "Darwin" ]; then
  echo "camp-stop.sh supports macOS (pmset + launchd) and Linux (systemd --user)." >&2
  exit 1
fi

SAVED="$ROOT/wrf/out/camp-pmset.saved"

echo "== camp-stop =="
launchctl bootout "gui/$(id -u)/org.mtwashingtonsoaring.wrf" 2>/dev/null && \
  echo "unloaded: org.mtwashingtonsoaring.wrf" || echo "schedule was not loaded"

if [ ! -f "$SAVED" ]; then
  echo "no saved pmset state at $SAVED — not touching sleep settings."
  echo "run 'sudo pmset -c sleep 1 disablesleep 0' by hand if this Mac should sleep again."
  exit 0
fi

SLEEP_AC=$(awk '/AC Power:/{f=1} f && / sleep /{print $2; exit}' "$SAVED")
DISABLE=$(awk '/^ disablesleep/{print $2; exit}' "$SAVED")

if [ -n "$SLEEP_AC" ]; then
  sudo pmset -c sleep "$SLEEP_AC"
  echo "restored: pmset -c sleep $SLEEP_AC"
else
  echo "could not read the previous AC sleep value from $SAVED — leaving sleep as-is"
fi
if [ -n "$DISABLE" ]; then
  sudo pmset -c disablesleep "$DISABLE"
  echo "restored: pmset -c disablesleep $DISABLE"
else
  echo "could not read the previous disablesleep value from $SAVED — leaving it as-is"
fi
echo "camp mode OFF"
