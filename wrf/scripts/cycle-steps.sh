#!/bin/bash
# Container-side cycle phases for the WRF wave pipeline. Invoked by
# run-cycle.sh with the cycle directory as the working directory.
#
#   cycle-steps.sh static-geogrid
#   cycle-steps.sh prepare      START_ISO END_ISO SY SM SD SH EY EM ED EH HOURS
#   cycle-steps.sh chunk        YYYYMMDD HH CS CE CHUNK_START_ISO CHUNK_END_ISO
#   cycle-steps.sh real         START_ISO HOURS
#   cycle-steps.sh wrf          HOURS
#   cycle-steps.sh postprocess  CYCLE_ID WALL_SECONDS
#
# Every subcommand exits non-zero on the first failed gate and prints the
# evidence it collected; the host script turns that into a failed run.json.
set -u
SUB="$1"
shift
ulimit -s unlimited 2>/dev/null || true
# MPI ranks for real.exe/wrf.exe: 10 = the MacBook's performance cores. On
# another host, export WRF_NP (e.g. WRF_NP=16 on the 16-core 9950X) before
# invoking run-cycle.sh.
export OMP_NUM_THREADS=1
mkdir -p logs
log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

grib_ff() { # path -> the two-digit forecast hour in the filename
  basename "$1" | sed -E 's/.*f([0-9]{2})\.grib2$/\1/'
}

link_range() { # pattern first_ff last_ff  -> prints the linked count
  local pattern="$1" first="$2" last="$3" f ff i=0
  rm -f GRIBFILE.*
  for f in $(find grib -name "$pattern" | sort); do
    ff=$(grib_ff "$f")
    [ -n "$ff" ] || { echo "unparsable GRIB name: $f" >&2; exit 1; }
    # Select by forecast hour, not by position: earlier chunks delete their
    # GRIBs, so positions shift between runs.
    [ "$((10#$ff))" -ge "$first" ] || continue
    [ "$((10#$ff))" -le "$last" ] || continue
    printf -v c2 '%b' "\\$(printf '%03o' $((65 + i / 26)))"
    printf -v c3 '%b' "\\$(printf '%03o' $((65 + i % 26)))"
    ln -sf "$(readlink -f "$f")" "GRIBFILE.A${c2}${c3}"
    i=$((i + 1))
  done
  echo "$i"
}

delete_gribs() { # pattern last_ff — drop the GRIBs the chunk has consumed
  local pattern="$1" last="$2" f ff
  for f in $(find grib -name "$pattern" | sort); do
    ff=$(grib_ff "$f")
    [ -n "$ff" ] && [ "$((10#$ff))" -le "$last" ] && rm -f "$f"
  done
}

chunk_done() { # CS CE CSTART -> 0 when every met_em file for the chunk exists
  local cs="$1" ce="$2" cstart="$3" base t h missing=""
  # Epoch arithmetic on purpose: GNU date mis-parses "… 12:00:00 + N hours".
  base=$(date -u -d "${cstart/_/ }" +%s)
  h="$cs"
  while [ "$h" -le "$ce" ]; do
    t=$(date -u -d "@$((base + (h - cs) * 3600))" +%Y-%m-%d_%H:%M:%S)
    { [ -f "met_em.d01.$t.nc" ] && [ -f "met_em.d02.$t.nc" ]; } || missing="$missing $t"
    h=$((h + 1))
  done
  [ -z "$missing" ] || { echo "missing met_em:$missing"; return 1; }
  return 0
}

case "$SUB" in
prepare)
  # prepare START_ISO END_ISO SY SM SD SH EY EM ED EH HOURS
  START_ISO="$1" END_ISO="$2" SY="$3" SM="$4" SD="$5" SH="$6" EY="$7" EM="$8" ED="$9" EH="${10}" HOURS="${11}"
  cp -f /wrf/wps/namelist.wps namelist.wps
  cp -f /wrf/wrf/namelist.input namelist.input
  cp -f /wrf/wrf/iofields_d01.txt /wrf/wrf/iofields_d02.txt .
  mkdir -p geogrid metgrid
  cp -f /wrf/wps/GEOGRID.TBL geogrid/GEOGRID.TBL
  cp -f /opt/WPS/metgrid/METGRID.TBL.ARW metgrid/METGRID.TBL
  ln -sf /opt/WPS/ungrib/src/ungrib.exe .
  ln -sf /opt/WPS/metgrid/src/metgrid.exe .
  ln -sf /opt/WRF/main/real.exe .
  ln -sf /opt/WRF/main/wrf.exe .
  # Static domain: metgrid reads the geo_em pair built once in /wrf/static.
  for d in 01 02; do
    [ -s "/wrf/static/geo_em.d$d.nc" ] || {
      echo "missing /wrf/static/geo_em.d$d.nc — the static-geogrid step has not run"
      exit 1
    }
    ln -sf "/wrf/static/geo_em.d$d.nc" "geo_em.d$d.nc"
  done
  # WRF reads its runtime physics tables and RRTMG inputs from the run
  # directory; a custom run directory has none of WRF's run/ files.
  for f in LANDUSE.TBL SOILPARM.TBL VEGPARM.TBL GENPARM.TBL URBPARM.TBL URBPARM_LCZ.TBL RRTMG_LW_DATA RRTMG_SW_DATA CAMtr_volume_mixing_ratio ozone.formatted ozone_lat.formatted ozone_plev.formatted; do
    cp -f "/opt/WRF/run/$f" . 2>/dev/null
  done
  sed -i "s/^ start_date = .*/ start_date = '$START_ISO','$START_ISO',/" namelist.wps
  sed -i "s/^ end_date   = .*/ end_date   = '$END_ISO','$END_ISO',/" namelist.wps
  sed -i "s/^ start_year = .*/ start_year = $SY, $SY,/" namelist.input
  sed -i "s/^ start_month = .*/ start_month = $SM, $SM,/" namelist.input
  sed -i "s/^ start_day = .*/ start_day = $SD, $SD,/" namelist.input
  sed -i "s/^ start_hour = .*/ start_hour = $SH, $SH,/" namelist.input
  sed -i "s/^ end_year = .*/ end_year = $EY, $EY,/" namelist.input
  sed -i "s/^ end_month = .*/ end_month = $EM, $EM,/" namelist.input
  sed -i "s/^ end_day = .*/ end_day = $ED, $ED,/" namelist.input
  sed -i "s/^ end_hour = .*/ end_hour = $EH, $EH,/" namelist.input
  sed -i "s/run_hours = .*/run_hours = $HOURS,/" namelist.input
  sed -i "s/num_metgrid_levels = .*/num_metgrid_levels = -999,/" namelist.input
  sed -i "s/num_metgrid_soil_levels = .*/num_metgrid_soil_levels = -999,/" namelist.input
  log "prepared: window $START_ISO .. $END_ISO, run_hours=$HOURS"
  grep -E "start_date|end_date" namelist.wps | head -2
  grep -E "run_hours|p_top_requested" namelist.input
  ;;

static-geogrid)
  # The domain and terrain never change between cycles, so geogrid runs once
  # into /wrf/static (gitignored) and every cycle links the two geo_em files
  # from there (see prepare). The cache key is a hash of the namelist.wps
  # domain blocks plus GEOGRID.TBL: change either and the next cycle rebuilds.
  STATIC=/wrf/static
  mkdir -p "$STATIC/geogrid" "$STATIC/logs"
  cd "$STATIC"
  cp -f /wrf/wps/namelist.wps namelist.wps
  cp -f /wrf/wps/GEOGRID.TBL geogrid/GEOGRID.TBL
  ln -sf /opt/WPS/geogrid/src/geogrid.exe .
  hash=$( { sed -n '/^&share/,/^\//p; /^&geogrid/,/^\//p' namelist.wps; cat geogrid/GEOGRID.TBL; } | sha256sum | cut -d' ' -f1 )
  if [ -s geo_em.d01.nc ] && [ -s geo_em.d02.nc ] && [ -f build-hash ] && [ "$(cat build-hash)" = "$hash" ]; then
    echo "static geo_em is current (hash $hash) — skipping geogrid"
    echo "  --- terrain gate ---"
    python /wrf/scripts/check-geogrid.py . || exit 1
    exit 0
  fi
  echo "static geo_em missing or stale (want hash $hash) — running geogrid"
  t0=$(date +%s)
  ./geogrid.exe > logs/geogrid-run.log 2>&1 || { tail -8 logs/geogrid-run.log; exit 1; }
  grep -q "Successful completion" logs/geogrid-run.log || { tail -8 logs/geogrid-run.log; exit 1; }
  log "geogrid: $(( $(date +%s) - t0 ))s for both domains"
  ls -l geo_em.d0*.nc
  echo "  --- terrain gate ---"
  python /wrf/scripts/check-geogrid.py . || exit 1
  echo "$hash" > build-hash
  ;;

chunk)
  # chunk YYYYMMDD HH CS CE CHUNK_START_ISO CHUNK_END_ISO
  YYYYMMDD="$1" HH="$2" CS="$3" CE="$4" CSTART="$5" CEND="$6"
  EXPECT=$((CE - CS + 1))

  # Resume: a chunk whose met_em files all exist is already done (its GRIBs may
  # be gone). This is what makes a re-run after a mid-cycle failure cheap.
  if chunk_done "$CS" "$CE" "$CSTART"; then
    echo "chunk $CS..$CE already complete — skipping"
    delete_gribs "hrrr.t${HH}z.wrfnatf*.grib2" "$CE"
    delete_gribs "hrrr.t${HH}z.soilf*.grib2" "$CE"
    exit 0
  fi

  # The ungrib window must BE the chunk's window: ungrib walks the namelist
  # window hourly and writes only the times it finds — missing times are
  # printed as errors but do not fail the run, so the output-count gates below
  # are load-bearing, and a leftover window from the previous chunk silently
  # produces zero intermediates.
  sed -i "s/^ start_date = .*/ start_date = '$CSTART','$CSTART',/" namelist.wps
  sed -i "s/^ end_date   = .*/ end_date   = '$CEND','$CEND',/" namelist.wps
  rm -f NAT:* SOIL:*

  n=$(link_range "hrrr.t${HH}z.wrfnatf*.grib2" "$CS" "$CE")
  log "chunk $CS..$CE: linked $n NAT files (expect $EXPECT)"
  [ "$n" -eq "$EXPECT" ] || exit 1
  cp -f /wrf/wps/Vtable.NAT.trimmed Vtable
  sed -i "s/^ prefix = .*/ prefix = 'NAT',/" namelist.wps
  t0=$(date +%s)
  ./ungrib.exe > "logs/ungrib-nat-$CS-$CE.log" 2>&1 || { tail -8 "logs/ungrib-nat-$CS-$CE.log"; exit 1; }
  [ "$(ls NAT:* 2>/dev/null | wc -l)" -eq "$EXPECT" ] || {
    echo "ungrib NAT wrote $(ls NAT:* 2>/dev/null | wc -l) intermediate files, expected $EXPECT"
    tail -8 "logs/ungrib-nat-$CS-$CE.log"
    exit 1
  }
  log "ungrib NAT: $(( $(date +%s) - t0 ))s for $EXPECT times"

  n=$(link_range "hrrr.t${HH}z.soilf*.grib2" "$CS" "$CE")
  log "chunk $CS..$CE: linked $n SOIL files (expect $EXPECT)"
  [ "$n" -eq "$EXPECT" ] || exit 1
  cp -f /wrf/wps/Vtable.HRRR.wrfprs Vtable
  sed -i "s/^ prefix = .*/ prefix = 'SOIL',/" namelist.wps
  t0=$(date +%s)
  ./ungrib.exe > "logs/ungrib-soil-$CS-$CE.log" 2>&1 || { tail -8 "logs/ungrib-soil-$CS-$CE.log"; exit 1; }
  [ "$(ls SOIL:* 2>/dev/null | wc -l)" -eq "$EXPECT" ] || {
    echo "ungrib SOIL wrote $(ls SOIL:* 2>/dev/null | wc -l) intermediate files, expected $EXPECT"
    tail -8 "logs/ungrib-soil-$CS-$CE.log"
    exit 1
  }
  log "ungrib SOIL: $(( $(date +%s) - t0 ))s for $EXPECT times"

  t0=$(date +%s)
  ./metgrid.exe > "logs/metgrid-$CS-$CE.log" 2>&1 || { tail -8 "logs/metgrid-$CS-$CE.log"; exit 1; }
  grep -q "Successful completion" "logs/metgrid-$CS-$CE.log" || { tail -8 "logs/metgrid-$CS-$CE.log"; exit 1; }
  log "metgrid: $(( $(date +%s) - t0 ))s for $EXPECT times"
  chunk_done "$CS" "$CE" "$CSTART" || { echo "chunk $CS..$CE incomplete after metgrid"; exit 1; }
  log "chunk $CS..$CE: met_em complete ($(ls met_em.d01.* 2>/dev/null | wc -l) times so far)"
  python /wrf/scripts/check-met-em.py . --times "$(ls met_em.d01.* 2>/dev/null | wc -l)" || exit 1

  # Free the chunk's intermediates and GRIBs (met_em keeps everything forward)
  rm -f NAT:* SOIL:*
  delete_gribs "hrrr.t${HH}z.wrfnatf*.grib2" "$CE"
  delete_gribs "hrrr.t${HH}z.soilf*.grib2" "$CE"
  log "chunk $CS..$CE: intermediates and GRIBs cleaned"
  ;;

real)
  # real START_ISO HOURS
  START_ISO="$1" HOURS="$2"
  read -r NLEV NSOIL < <(python -c "
import xarray as xr
ds = xr.open_dataset('met_em.d01.${START_ISO}.nc')
print(ds.sizes['num_metgrid_levels'], int(ds.attrs['NUM_METGRID_SOIL_LEVELS']))
")
  log "derived from met_em at run time: num_metgrid_levels=$NLEV  num_metgrid_soil_levels=$NSOIL"
  [ -n "$NLEV" ] && [ -n "$NSOIL" ] || exit 1
  sed -i "s/num_metgrid_levels = .*/num_metgrid_levels = $NLEV,/" namelist.input
  sed -i "s/num_metgrid_soil_levels = .*/num_metgrid_soil_levels = $NSOIL,/" namelist.input
  grep -E "p_top_requested|num_metgrid|run_hours" namelist.input
  rm -f rsl.*
  # OpenMPI 4.1 binds to nothing by default (observed "rank N is not bound"
  # in --report-bindings on the 9950X); --map-by core --bind-to core pins
  # one rank per physical core (16 ranks -> cores 0..15, no SMT siblings
  # shared between ranks).
  t0=$(date +%s)
  mpirun --map-by core --bind-to core -np "${WRF_NP:-10}" ./real.exe > logs/real.log 2>&1
  rc=$?
  log "real rc=$rc in $(( $(date +%s) - t0 ))s"
  grep -m2 "Assume RUC LSM" rsl.error.0000 2>/dev/null || echo "  (no 'Assume RUC LSM' line found!)"
  grep -m1 "SUCCESS COMPLETE REAL_EM" rsl.error.0000 2>/dev/null || { tail -15 rsl.error.0000 2>/dev/null; exit 1; }
  ls -l wrfinput_d0* wrfbdy_d01 2>/dev/null | awk '{print "  ", $5, $9}'
  echo "  --- soil gate ---"
  python /wrf/scripts/check-wrfinput-soil.py . || exit 1
  echo "  --- level / sponge gate ---"
  python /wrf/scripts/check-levels.py . --sponge-depth 5000 --min-levels 5 || exit 1
  ;;

wrf)
  # wrf HOURS
  HOURS="$1"
  # Resume guard: a complete run (final wrfout + the model's own SUCCESS line) is
  # skipped, so a killed orchestrator never costs a 4-hour re-run. Delete rsl.*
  # and the wrfout files to force one.
  if ls wrfout_d02_* >/dev/null 2>&1 && grep -q "SUCCESS COMPLETE WRF" rsl.error.0000 2>/dev/null; then
    echo "complete wrfout present (SUCCESS COMPLETE WRF in rsl.error.0000) — skipping the run"
    exit 0
  fi
  rm -f rsl.*
  t0=$(date +%s)
  mpirun --map-by core --bind-to core -np "${WRF_NP:-10}" ./wrf.exe > logs/wrf.log 2>&1
  rc=$?
  wall=$(( $(date +%s) - t0 ))
  log "wrf rc=$rc, wall ${wall}s for ${HOURS} h ($(awk -v w="$wall" -v h="$HOURS" 'BEGIN{printf "%.1f", w/h}') s per forecast hour)"
  echo "  SUCCESS COMPLETE WRF lines: $(grep -c 'SUCCESS COMPLETE WRF' rsl.error.0000 2>/dev/null || echo 0)"
  echo "  CFL mentions: $(grep -c CFL rsl.error.0000 2>/dev/null || echo 0)"
  ls -l wrfout_d0* 2>/dev/null | awk '{print "  ", $5, $9}'
  for f in wrfout_d01_* wrfout_d02_*; do
    [ -f "$f" ] || continue
    frames=$(ncdump -h "$f" 2>/dev/null | grep -m1 'Time = UNLIMITED' | sed 's/.*(\([0-9]*\) currently).*/\1/')
    echo "  frames in $f: $frames"
  done
  [ "$rc" -eq 0 ] || exit "$rc"
  grep -q "SUCCESS COMPLETE WRF" rsl.error.0000 || exit 1
  ;;

postprocess)
  # postprocess CYCLE_ID WALL_SECONDS
  CYCLE_ID="$1" WALL="$2"
  python /wrf/scripts/postprocess.py . --contract grid.json --cycle "$CYCLE_ID" --wall-seconds "$WALL" || exit 1
  ;;

*)
  echo "unknown subcommand: $SUB" >&2
  exit 2
  ;;
esac
