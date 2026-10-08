#!/bin/bash
# Camp-mode cycle runner for the Mt Washington 1 km wave pipeline.
#
#   wrf/scripts/run-cycle.sh latest [--hours 36] [--chunk-hours 12] [--skip-fetch] [--no-publish]
#   wrf/scripts/run-cycle.sh <YYYYMMDD> <HH> [same flags]
#
# Host-side orchestration: battery gate, lock, container phases (cycle-steps.sh),
# grid-contract export, publish (run.json last), retention cleanup. On failure a
# run.json with status "failed" and the failing step's log tail is written and —
# when the Blob token exists — it is the ONLY file published, so the site keeps
# its stamp and falls back to HRRR.
set -u

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WRF_DIR="$ROOT/wrf"
IMAGE="mtw-wrf:4.6.1"
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"

# Sleep-proofing: every entry point (terminal, launchd, cron) runs the cycle
# under caffeinate when the host has it (macOS); a Linux server never sleeps.
if [ -z "${WRF_CAFFEINATED:-}" ] && command -v caffeinate >/dev/null 2>&1; then
  export WRF_CAFFEINATED=1
  exec caffeinate -i "$0" "$@"
fi

# One date dialect per host: BSD date on macOS, GNU date on Linux.
if date -j -u -f "%Y-%m-%d" "2026-01-01" +%s >/dev/null 2>&1; then
  DATE_BSD=1
else
  DATE_BSD=0
fi
fmt_epoch() { # <epoch> <format>
  if [ "$DATE_BSD" -eq 1 ]; then date -j -u -r "$1" "+$2"; else date -u -d "@$1" "+$2"; fi
}
epoch_of() { # "YYYY-MM-DD_HH:MM:SS" -> epoch
  if [ "$DATE_BSD" -eq 1 ]; then
    date -j -u -f "%Y-%m-%d_%H:%M:%S" "$1" +%s
  else
    date -u -d "${1/_/ }" +%s
  fi
}

HOURS=""   # decided per cycle below unless --hours overrides
CHUNK_HOURS=12
SKIP_FETCH=0
NO_PUBLISH=0
POSITIONAL=()
while [ $# -gt 0 ]; do
  case "$1" in
    --hours) HOURS="$2"; shift 2 ;;
    --chunk-hours) CHUNK_HOURS="$2"; shift 2 ;;
    --skip-fetch) SKIP_FETCH=1; shift ;;
    --no-publish) NO_PUBLISH=1; shift ;;
    -*) echo "unknown flag: $1" >&2; exit 2 ;;
    *) POSITIONAL+=("$1"); shift ;;
  esac
done

if [ "${#POSITIONAL[@]}" -eq 2 ]; then
  CYCLE_DATE="${POSITIONAL[0]}"
  CYCLE_HOUR=$(printf '%02d' "$((10#${POSITIONAL[1]}))")
elif [ "${#POSITIONAL[@]}" -eq 1 ] && [ "${POSITIONAL[0]}" = "latest" ]; then
  CYCLE_DATE=$(date -u +%Y%m%d)
  CYCLE_HOUR=$(printf '%02d' "$((10#$(date -u +%H) / 6 * 6))")
else
  echo "usage: run-cycle.sh latest|<YYYYMMDD> <HH> [--hours N] [--chunk-hours N] [--skip-fetch] [--no-publish]" >&2
  exit 2
fi

if [ -z "$HOURS" ]; then
  # Forecast length matched to the briefing it serves (owner, 2026-10-07):
  # the 18Z cycle runs 28 h (through 22Z the next day — the whole next flying
  # day), the 06Z cycle runs 18 h (through 00Z). Manual runs of other cycles
  # keep the full 36 h. --hours overrides any of it.
  case "$CYCLE_HOUR" in
    18) HOURS=28 ;;
    06) HOURS=18 ;;
    *) HOURS=36 ;;
  esac
fi

CYCLE_ID="${CYCLE_DATE}T${CYCLE_HOUR}Z"

# Battery gate: macOS only (a Linux server has no battery and no pmset).
if command -v pmset >/dev/null 2>&1 && pmset -g batt | grep -q "Battery Power"; then
  echo "refusing to start: running on battery"
  exit 3
fi

LOCK="$WRF_DIR/out/.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "refusing to start: $LOCK exists (another cycle running, or a stale lock)"
  exit 4
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT

CYCLE_DIR="$WRF_DIR/out/$CYCLE_ID"
mkdir -p "$CYCLE_DIR/logs"

START_ISO="${CYCLE_DATE:0:4}-${CYCLE_DATE:4:2}-${CYCLE_DATE:6:2}_${CYCLE_HOUR}:00:00"
START_EPOCH=$(epoch_of "$START_ISO")
END_EPOCH=$((START_EPOCH + HOURS * 3600))
END_ISO=$(fmt_epoch "$END_EPOCH" "%Y-%m-%d_%H:%M:%S")
SY=$(fmt_epoch "$START_EPOCH" "%Y")
SM=$(fmt_epoch "$START_EPOCH" "%m")
SD=$(fmt_epoch "$START_EPOCH" "%d")
SH=$(fmt_epoch "$START_EPOCH" "%H")
EY=$(fmt_epoch "$END_EPOCH" "%Y")
EM=$(fmt_epoch "$END_EPOCH" "%m")
ED=$(fmt_epoch "$END_EPOCH" "%d")
EH=$(fmt_epoch "$END_EPOCH" "%H")

log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

STEP="startup"
STEP_LOG="$CYCLE_DIR/logs/startup.log"

step() { # name, container command
  STEP="$1"
  shift
  STEP_LOG="$CYCLE_DIR/logs/${STEP}.log"
  echo "===== $STEP ====="
  local rc=0
  docker run --rm -v "$WRF_DIR:/wrf" -w "/wrf/out/$CYCLE_ID" "$IMAGE" bash -lc "$*" >>"$STEP_LOG" 2>&1 || rc=$?
  log "$STEP rc=$rc"
  return $rc
}

host_step() { # name, host command
  STEP="$1"
  shift
  STEP_LOG="$CYCLE_DIR/logs/${STEP}.log"
  echo "===== $STEP ====="
  local rc=0
  bash -c "$*" >>"$STEP_LOG" 2>&1 || rc=$?
  log "$STEP rc=$rc"
  return $rc
}

publish_available() { [ -f "$WRF_DIR/.env" ] && grep -q "BLOB_READ_WRITE_TOKEN" "$WRF_DIR/.env"; }

fail() {
  echo "FAILED step: $STEP"
  tail -30 "$STEP_LOG" 2>/dev/null
  python3 - "$CYCLE_DIR" "$CYCLE_ID" "$STEP" "$STEP_LOG" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path

cycle_dir, cycle_id, step, step_log = sys.argv[1:5]
try:
    tail = Path(step_log).read_text(errors="replace").splitlines()[-30:]
except OSError:
    tail = []
payload = {
    "schema": 1,
    "cycle": cycle_id,
    "status": "failed",
    "step": step,
    "log_tail": tail,
    "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
}
Path(cycle_dir, "run.json").write_text(json.dumps(payload, indent=2) + "\n")
PY
  if [ "$NO_PUBLISH" -eq 0 ] && publish_available; then
    node "$WRF_DIR/scripts/publish.mts" "$CYCLE_DIR" --only run.json || echo "publishing the failure stamp failed"
  else
    echo "publish skipped (no token or --no-publish)"
  fi
  exit 1
}

log "cycle $CYCLE_ID, ${HOURS} h, chunks up to ${CHUNK_HOURS} h"

AVAIL_GB=$(df -g "$WRF_DIR" 2>/dev/null | awk 'NR==2{print $4}')
if [ -z "$AVAIL_GB" ]; then  # GNU df has no -g
  AVAIL_GB=$(df -BG --output=avail "$WRF_DIR" 2>/dev/null | awk 'NR==2{gsub(/G/,"");print}')
fi
if [ -n "${AVAIL_GB:-}" ] && [ "$AVAIL_GB" -lt 60 ]; then
  echo "refusing to start: only ${AVAIL_GB} GB free under $WRF_DIR (need >= 60)"
  exit 5
fi
[ -n "${AVAIL_GB:-}" ] && log "free space: ${AVAIL_GB} GB"

if [ "$SKIP_FETCH" -eq 0 ]; then
  step fetch-nat "python -u /wrf/scripts/fetch-hrrr.py $CYCLE_DATE $CYCLE_HOUR --hours $HOURS --product nat --subset --dest grib" || fail
  step fetch-soil "python -u /wrf/scripts/fetch-soil.py $CYCLE_DATE $CYCLE_HOUR --hours $HOURS --dest grib" || fail
else
  log "fetch skipped (--skip-fetch)"
fi

step prepare "bash /wrf/scripts/cycle-steps.sh prepare $START_ISO $END_ISO $SY $SM $SD $SH $EY $EM $ED $EH $HOURS" || fail
host_step export-grid "node '$WRF_DIR/scripts/export-grid.mts' --out '$CYCLE_DIR/grid.json'" || fail

CS=0
while [ "$CS" -le "$HOURS" ]; do
  CE=$((CS + CHUNK_HOURS))
  [ "$CE" -gt "$HOURS" ] && CE="$HOURS"
  CSTART=$(fmt_epoch "$((START_EPOCH + CS * 3600))" "%Y-%m-%d_%H:%M:%S")
  CEND=$(fmt_epoch "$((START_EPOCH + CE * 3600))" "%Y-%m-%d_%H:%M:%S")
  step "chunk-${CS}-${CE}" "bash /wrf/scripts/cycle-steps.sh chunk $CYCLE_DATE $CYCLE_HOUR $CS $CE $CSTART $CEND" || fail
  CS=$((CE + 1))
done

step real "bash /wrf/scripts/cycle-steps.sh real $START_ISO $HOURS" || fail

T0=$(date +%s)
step wrf "bash /wrf/scripts/cycle-steps.sh wrf $HOURS" || fail
WALL_SECONDS=$(( $(date +%s) - T0 ))

step postprocess "bash /wrf/scripts/cycle-steps.sh postprocess $CYCLE_ID $WALL_SECONDS" || fail

if [ "$NO_PUBLISH" -eq 0 ] && publish_available; then
  host_step publish "node '$WRF_DIR/scripts/publish.mts' '$CYCLE_DIR'" || fail
else
  log "publish skipped (no token or --no-publish)"
fi

host_step cleanup-retention "
  rm -f '$CYCLE_DIR'/wrfout_d01_* 2>/dev/null
  rm -rf '$CYCLE_DIR'/grib 2>/dev/null
  # A cycle directory containing a KEEP file is never pruned (reference cases).
  for d in '$WRF_DIR'/out/20*/; do
    [ -e \"\$d/KEEP\" ] && continue
    find \"\$d\" -name 'wrfout_d0*' -mtime +1 -delete 2>/dev/null
    find \"\$d\" -name 'met_em.*' -mtime +3 -delete 2>/dev/null
  done
  find '$WRF_DIR/out' -maxdepth 1 -type d -name '20*' -mtime +30 -exec sh -c 'test -e \"\$1/KEEP\" || rm -rf \"\$1\"' _ {} + 2>/dev/null
  true" || fail

log "cycle $CYCLE_ID complete (wrf wall ${WALL_SECONDS}s)"
echo "===== CYCLE COMPLETE ====="
