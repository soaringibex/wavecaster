#!/bin/bash
# Camp mode ON. macOS: save the current pmset state, keep the machine awake on
# AC, and load the launchd schedule. Linux: install the systemd user units and
# enable the timer. Either way the fires are the 18Z and 06Z HRRR cycles at
# 19:45/07:45 UTC.
#
#   wrf/scripts/camp-start.sh
#
# macOS pmset needs root, so you will be asked for your password; camp-stop.sh
# restores exactly the sleep/disablesleep values this script replaced.
# Linux timers need user lingering to fire while logged out (admin to-do;
# camp-start.sh warns when linger is off — it cannot enable it itself).
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

if [ "$(uname)" = "Linux" ]; then
  UNITS_SRC="$ROOT/wrf/systemd"
  UNITS_DST="$HOME/.config/systemd/user"
  echo "== camp-start =="
  if ! command -v systemctl >/dev/null 2>&1; then
    echo "camp-start.sh: no systemctl on this host" >&2
    exit 1
  fi
  mkdir -p "$UNITS_DST"
  cp -f "$UNITS_SRC/wavecaster.service" "$UNITS_SRC/wavecaster.timer" "$UNITS_DST/"
  systemctl --user daemon-reload
  systemctl --user enable --now wavecaster.timer
  echo "enabled: wavecaster.timer (fires 07:45 and 19:45 UTC)"
  systemctl --user list-timers wavecaster.timer --no-pager | sed 's/^/  /'
  if ! loginctl show-user "$USER" -p Linger 2>/dev/null | grep -q "Linger=yes"; then
    echo
    echo "WARNING: user lingering is OFF — the timer only fires while this account"
    echo "is logged in. Ask the admin to run:  loginctl enable-linger $USER"
  fi
  echo "camp mode ON — run-cycle.sh latest picks 06Z at 07:45 and 18Z at 19:45."
  exit 0
fi

if [ "$(uname)" != "Darwin" ]; then
  echo "camp-start.sh supports macOS (pmset + launchd) and Linux (systemd --user)." >&2
  exit 1
fi

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
