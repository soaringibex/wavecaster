#!/bin/bash
# Camp mode ON: save the current pmset state, keep the machine awake on AC, and
# load the launchd schedule (18Z and 06Z HRRR cycles, 19:45/07:45 UTC).
#
#   wrf/scripts/camp-start.sh
#
# pmset needs root, so you will be asked for your password. camp-stop.sh
# restores exactly the sleep/disablesleep values this script replaced.
# macOS-only: on a Linux server use cron instead (README, Linux section).
set -u
if [ "$(uname)" != "Darwin" ]; then
  echo "camp-start.sh is macOS-only (pmset + launchd)."
  echo "On a Linux server, schedule wrf/scripts/run-cycle.sh with cron — see the README's Linux section."
  exit 1
fi
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PLIST_SRC="$ROOT/wrf/launchd/org.mtwashingtonsoaring.wrf.plist"
PLIST_DST="$HOME/Library/LaunchAgents/org.mtwashingtonsoaring.wrf.plist"
SAVED="$ROOT/wrf/out/camp-pmset.saved"

echo "== camp-start =="
mkdir -p "$ROOT/wrf/out"

# 1. Save the settings we are about to change, so camp-stop can restore them.
{
  echo "# saved by camp-start.sh $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  pmset -g custom
  pmset -g | grep disablesleep || true
} > "$SAVED"
echo "saved current pmset state -> $SAVED"
awk '/AC Power:/{f=1} f && /sleep/{print "  AC sleep (was): "$2; exit}' "$SAVED"

# 2. Keep the machine awake on AC power for the duration of camp.
sudo pmset -c sleep 0 disablesleep 1
echo "set: pmset -c sleep 0 disablesleep 1"

# 3. Load the schedule (reload if it was already loaded).
mkdir -p "$HOME/Library/LaunchAgents"
cp -f "$PLIST_SRC" "$PLIST_DST"
launchctl bootout "gui/$(id -u)/org.mtwashingtonsoaring.wrf" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_DST"
echo "loaded: $PLIST_DST"
launchctl list | grep mtwashingtonsoaring | sed 's/^/  /' || true

echo "camp mode ON — cycles fire 21:45 and 03:45 local (01:45/07:45 UTC during EDT)"
echo "run-cycle.sh refuses to start on battery; this Mac will now stay awake on AC."
