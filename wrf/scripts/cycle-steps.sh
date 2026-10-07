#!/bin/bash
# Container-side cycle phases for the WRF wave pipeline. Invoked by
# run-cycle.sh with the cycle directory as the working directory.
#
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
export OMP_NUM_THREADS=1
mkdir -p logs
log() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

link_range() { # pattern first_ff last_ff  -> prints the linked count
  local pattern="$1" first="$2" last="$3"
  local i=0
  rm -f GRIBFILE.*
  for f in $(find grib -name "$pattern" | sort | sed -n "$((first + 1)),$((last + 1))p"); do
    printf -v c2 '%b' "\\$(printf '%03o' $((65 + i / 26)))"
    printf -v c3 '%b' "\\$(printf '%03o' $((65 + i % 26)))"
    ln -sf "$(readlink -f "$f")" "GRIBFILE.A${c2}${c3}"
    i=$((i + 1))
  done
  echo "$i"
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

chunk)
  # chunk YYYYMMDD HH CS CE CHUNK_START_ISO CHUNK_END_ISO
  YYYYMMDD="$1" HH="$2" CS="$3" CE="$4" CSTART="$5" CEND="$6"
  EXPECT=$((CE - CS + 1))

  n=$(link_range "hrrr.t${HH}z.wrfnatf*.grib2" "$CS" "$CE")
  log "chunk $CS..$CE: linked $n NAT files (expect $EXPECT)"
  [ "$n" -eq "$EXPECT" ] || exit 1
  cp -f /wrf/wps/Vtable.NAT.trimmed Vtable
  sed -i "s/^ prefix = .*/ prefix = 'NAT',/" namelist.wps
  ./ungrib.exe > "logs/ungrib-nat-$CS-$CE.log" 2>&1 || { tail -8 "logs/ungrib-nat-$CS-$CE.log"; exit 1; }

  n=$(link_range "hrrr.t${HH}z.soilf*.grib2" "$CS" "$CE")
  log "chunk $CS..$CE: linked $n SOIL files (expect $EXPECT)"
  [ "$n" -eq "$EXPECT" ] || exit 1
  cp -f /wrf/wps/Vtable.HRRR.wrfprs Vtable
  sed -i "s/^ prefix = .*/ prefix = 'SOIL',/" namelist.wps
  ./ungrib.exe > "logs/ungrib-soil-$CS-$CE.log" 2>&1 || { tail -8 "logs/ungrib-soil-$CS-$CE.log"; exit 1; }

  sed -i "s/^ start_date = .*/ start_date = '$CSTART','$CSTART',/" namelist.wps
  sed -i "s/^ end_date   = .*/ end_date   = '$CEND','$CEND',/" namelist.wps
  ./metgrid.exe > "logs/metgrid-$CS-$CE.log" 2>&1 || { tail -8 "logs/metgrid-$CS-$CE.log"; exit 1; }
  log "chunk $CS..$CE: met_em now $(ls met_em.* 2>/dev/null | wc -l) files"
  grep -q "Successful completion" "logs/metgrid-$CS-$CE.log" || { tail -8 "logs/metgrid-$CS-$CE.log"; exit 1; }

  # Free the chunk's intermediates and GRIBs (met_em keeps everything forward)
  rm -f NAT:* SOIL:*
  find grib -name "hrrr.t${HH}z.wrfnatf*.grib2" | sort | sed -n "1,$((CE + 1))p" | xargs -r rm -f
  find grib -name "hrrr.t${HH}z.soilf*.grib2" | sort | sed -n "1,$((CE + 1))p" | xargs -r rm -f
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
  t0=$(date +%s)
  mpirun -np 10 ./real.exe > logs/real.log 2>&1
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
  rm -f rsl.*
  t0=$(date +%s)
  mpirun -np 10 ./wrf.exe > logs/wrf.log 2>&1
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
