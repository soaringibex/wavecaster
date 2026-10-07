# WRF 1 km wave-forecast pipeline — implementation plan

Status: **approved** (owner, 2026-10-06). Living document — updated as gates land.
The goal, machine survey and non-negotiables come from `PROMPT.md`; this file records
the decisions made on top of it and the gate every phase must pass.

## Goal

A reproducible WRF-ARW setup that runs on this MacBook during wave camp, producing
vertical velocity over the Presidential Range at 1 km from HRRR twice a day (00Z and
06Z cycles), publishing to Vercel Blob in the exact JSON shapes the site already reads
(`map-field` / `cross-section`, see `mtwashingtonsoaring/src/lib/wx-datasets.ts`), so
the Wx Brief map and cross-section gain a "WRF 1 km" field with no UI redesign.

## Locked decisions (owner, 2026-10-06)

| Decision | Value |
|---|---|
| Repo layout | The `wrf/` tree lives in **wavecaster** (this repo). Phase 5 site wiring happens in **mtwashingtonsoaring**. Local commits only; nothing is pushed without approval. |
| Vertical grid | `e_vert=100, dzbot=50., dzstretch_s=1.035, dzstretch_u=1.035, max_dz=1000, p_top_requested=1000 Pa, auto_levels_opt=2`. Target: ≤ ~120 m through 2 km, ≤ ~250 m through 5 km, top at 10 hPa. Verified against a replica of WRF 4.6.1 `levels()`; `real.exe`'s printed profile is the gate. |
| `max_dz` pin | PROMPT's `max_dz=4` is metres in WRF 4.6.1 and makes `real.exe` fatal (`Upper levels may be too thick`). Superseded by the retune above. |
| Docker | Start the daemon → **inventory shown** → `docker system prune -a --volumes` → disk-image limit ≥ 120 GB. |
| Blob | No store creation from this machine's CLI (it is scoped to the wrong team). `.gitignore` + `wrf/.env` + `publish.mts` are prepared; the owner creates the store in the Vercel dashboard under the mtwashingtonsoaring project and supplies the token. The Phase 5 publish gate stays **pending** until then. |
| Disk policy | GRIB deleted after a successful metgrid; `met_em` + `wrfout` kept 3 days; logs / `run.json` / check PNGs 30 days; d01 `wrfout` pruned after postprocess; free-space check before each cycle. |
| Run style | Autonomous across phases under `caffeinate -i`; pause only at the gates listed below. |
| Phase 3 | **6-hour** forecast with the **final** namelist (pipeline + Vtable audit + timing per forecast hour). Phase 4 is the full 36-h 2026-10-06 12Z run, reusing the retained `met_em` — no refetch. |
| `met_em` | Retained 3 days (~2 GB/cycle) so a CFL fallback or a namelist edit never forces the 14 GB refetch. |
| HRRR fetch | First cycle uses full pressure files; then `fetch-hrrr.py` switches to `.idx` byte-range subsetting (~14 GB → ~2–3 GB), verified by the identical ungrib field audit. |
| Cross-repo contract | `export-grid.mts` resolves: sibling checkout → deployed `wrf-contract.json` → loud failure. The site generates `public/wrf-contract.json` from `wx-grid.ts` in its build. |

## Non-negotiables (carried from PROMPT.md)

- Max `HGT_M` on d02 ≥ 1,750 m — asserted, and the summit grid point printed.
- Model top 10 hPa with Rayleigh damping (`damp_opt=3`); `w_damping=0`.
- No cumulus parametrization on either domain.
- Every phase ends with a printed check; no advancing on "probably worked".
- Pinned versions recorded in `wrf/README.md`.
- No accounts or spending without asking; never print the Blob token; delete nothing
  outside `wrf/out/` and Docker's own storage.

## Deliverables

**wavecaster** — `wrf/docker/{Dockerfile,build.sh}`, `wrf/wps/{namelist.wps,GEOGRID.TBL,Vtable.RAP.pressure.ncep}`,
`wrf/wrf/{namelist.input,iofields_d01.txt,iofields_d02.txt}`, `wrf/scripts/{fetch-hrrr.py,postprocess.py,publish.mts,export-grid.mts,run-cycle.sh,camp-start.sh,camp-stop.sh}`,
`wrf/launchd/org.mtwashingtonsoaring.wrf.plist`, `wrf/README.md` (pins), `wrf/.env` (gitignored),
minimal `package.json` (+`@vercel/blob`), `.gitignore` (written before anything large).

**mtwashingtonsoaring** — new `src/lib/wx-grid.ts` (grid/level constants; re-exported by
`wx-datasets.ts` so nothing else moves), three `buildUpstreamRequest` cases (`wrf-map-field`,
`wrf-cross-section`, `wrf-run`; 404 when `WRF_BLOB_BASE_URL` is unset; revalidate 900/900/300),
a "WRF 1 km" option + `run.json` stamp + fallback (missing / older than 9 h / `status != "ok"`)
in `WaveMap.tsx` and `WaveCrossSection.tsx`, and `scripts/write-wrf-contract.mts` +
`public/wrf-contract.json` wired into the build.

## Phases, gates, pauses

**Phase 0 — prep.** `.gitignore` first; scaffold; this plan; pins stub; commits. Docker:
start daemon, show inventory, prune, raise disk limit. *Pause: inventory review.*

**Phase 1 — image.** Ubuntu 24.04 arm64; WRF v4.6.1 (release tarball) + WPS v4.6.0 (source
archive from the tag — its release asset URL is a 404), SHA-256 pinned in the Dockerfile and
README; OpenMPI, zlib, libpng, Jasper, HDF5, NetCDF C/Fortran; `convert_geotiff` (pinned
commit); Python 3.12 layer with pinned wrf-python, xarray, netCDF4, numpy, scipy, herbie-data,
rasterio, matplotlib, boto3. `-fallow-argument-mismatch -fallow-invalid-boz` applied via `sed`
to `configure.wrf` (reported; same for `configure.wps` if needed). *Gate:* image builds;
`wrf.exe` with no namelist prints "namelist.input not found"; `wrf.exe`/`real.exe`/`ndown.exe`
exist non-empty; `geogrid.exe`/`ungrib.exe`/`metgrid.exe` exist; `nproc` = 14; `mpirun -np 10
hostname` works; `convert_geotiff` responds.

**Phase 2 — static data + domains.** `geog_high_res_mandatory` (2.6 GB) → `wrf/geog/WPS_GEOG`
(checksum verified if NCAR publishes one, else recorded). USGS 3DEP 1″ tiles (6 tiles, ~350 MB)
→ mosaic → `convert_geotiff` → `wrf/geog/usgs_1s/`; patched `HGT_M` block in `wrf/wps/GEOGRID.TBL`
(`rel_path = usgs_1s:usgs_1s/`); `geog_data_res = 'default','usgs_1s+default'`; `namelist.wps`
exactly as pinned; `i_parent_start`/`j_parent_start` computed so d02 centres on 44.30 N / 71.30 W
(anticipated 36/36, confirmed from geogrid output); commented-out 333 m d03 left disabled.
*Gate:* max `HGT_M` on d02 ≥ 1,750 m; printed height at 44.2705 N / 71.3032 W; d01 max for
comparison; `wrf/out/checks/hgt_d02.png`.

**Phase 3 — data + 6-h smoke run.** `fetch-hrrr.py` (herbie, anonymous S3, ff 00–36);
ungrib with `Vtable.HRRR.wrfprs` — the audited merge of the stock RAP pressure table
and the RAP hybrid table's soil/land/ice rows. (PROMPT.md's pin was wrong on this
point: `Vtable.RAP.pressure.ncep` supplies no soil/LANDSEA/SEAICE, and `Vtable.GFS`
loses PMSL and HRRR's soil encoding — audit evidence in `wrf/README.md`.) Field
audit per the supply table. real.exe reads `num_metgrid_levels` /
`num_metgrid_soil_levels` **derived at run time** from the met_em headers
(`BOTTOM-TOP_GRID_DIMENSION`/`NUM_METGRID_SOIL_LEVELS`), never hardcoded. **Soil
gate before the smoke run counts:** `check-wrfinput-soil.py` — SMOIS volumetric
(~0.05–0.45 m³/m³), TSLB ~275–295 K, 4 Noah layers from the 9 RUC levels, and
`real.exe`'s log shows the "Assume RUC LSM" multi-level path. 6-h wrf run with the
final namelist under `caffeinate -i`, `mpirun -np 10`; per-forecast-hour timing
recorded. *Gate:* frame count, `SUCCESS COMPLETE WRF`, no CFL warnings; timing
reported.

**Phase 4 — wave physics, full 36-h case.** Pinned namelist (10 hPa top + Rayleigh, `w_damping=0`,
no cumulus, MYNN/Thompson/RRTMG, `diff_opt=2 / km_opt=4 / epssm=0.5`, retuned levels), rationale
in comments. *Checkpoint:* `real.exe` dry run first — first 25 level heights/thicknesses printed,
pause if the spacing bounds miss. Then the full 36-h run from the retained `met_em`. CFL
fallbacks in order (adaptive timestep → `epssm=0.9` → `time_step=12`), reported. *Gate:* printed
eta profile; max |W| on d02 at ~3 km AGL at 20Z; wall time.

**Phase 5 — post-process, publish, wire in.** `export-grid.mts` reads the site's `wx-grid.ts`
(sibling → deployed `wrf-contract.json` → fail loudly); `postprocess.py` destaggers W and
interpolates onto the repo's levels; emits `map-field.json` (247 locations, row-major,
Open-Meteo layout, `hourly.time` = `YYYY-MM-DDTHH:MM` local, `utc_offset_seconds`,
`vertical_velocity_<hPa>hPa` in m/s), `cross-section-<azimuth>.json` for all 72 buckets
(15 points × 12 levels × 36 h, with `elevation` + `geopotential_height_<hPa>hPa`), `run.json`,
and hourly `w3km_*.png`. `publish.mts` uploads fixed paths with `allowOverwrite` — **`run.json`
last**. *Gate:* `npx tsc --noEmit`, `npm run lint`, `npm run check:wave`; the map and the 315°
cross-section render locally against the Oct 6 field. **Publish gate pending the owner's token.**

**Phase 6 — camp mode.** `run-cycle.sh` (battery check → fetch → ungrib → metgrid → real → wrf →
postprocess → publish; `caffeinate`, lock file, per-step logs, cleanup per the disk policy);
launchd plist at 01:45 / 07:45 UTC; `camp-start.sh` / `camp-stop.sh` (save/restore `pmset`; one
sudo prompt); failure path writes `status:"failed"` + last 30 log lines and publishes only that
file. *Gate:* one real end-to-end `run-cycle.sh` run on the next available cycle; plist lint;
cleanup dry run.

**Phase 7 — verification, no tuning.** Against the SkySight field at 16:00 EDT / 3,000 m ASL:
dominant wavelength along the 315° transect through the Glider Area centre (1-D spectrum of W),
primary lift position vs summit, secondary near Route 113, peak |W|, summit-level wind at
1,917 m. Agreement or disagreement reported plainly.

## Pauses (the only ones)

Prune inventory · Phase 4 `real.exe` profile if a bound misses · any CFL fallback · Blob token
arrival · `WRF_BLOB_BASE_URL` added to the Vercel project env (needs approval + redeploy) ·
`camp-start.sh` sudo.

## Final report checklist (per PROMPT.md)

Prune freed / `wrf/` disk used · every gate's printed values · Vtable and any fallbacks ·
wall time per forecast hour on 10 cores · Blob base URL + the three published paths ·
the Phase 7 comparison · what could not be verified.
