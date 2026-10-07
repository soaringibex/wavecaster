#!/bin/bash
# Camp mode OFF: unload the launchd schedule and restore the sleep settings that
# camp-start.sh replaced (from wrf/out/camp-pmset.saved).
#
#   wrf/scripts/camp-stop.sh
#
# Prints every change it makes. pmset needs root (password prompt).
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
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
