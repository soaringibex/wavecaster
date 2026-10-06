# Build a WRF forecast pipeline for Mt Washington wave camp — on this MacBook

## Goal

A reproducible WRF-ARW setup that runs on this laptop during the ~10 days of wave camp each year, producing vertical velocity over the Presidential Range at 1 km from HRRR, twice a day (00Z and 06Z 
cycles), and publishing it to Vercel Blob in the exact JSON shapes the mtwashingtonsoaring site   already reads (`map-field` and `cross-section` in `src/lib/wx-datasets.ts`), so the Wx Brief map and
cross-section gain a "WRF 1 km" field with no UI redesign. Everything lives in a new top-level `wrdirectory of this repo; nothing in `src/` changes until Phase 5.                                    
                                                                                                  ## The machine (already surveyed — don't re-decide this)                                            
                                                                                                  Apple M4 Max, 10 performance + 4 efficiency cores, 36 GB RAM, 161 GB free, Docker Desktop 29.x and  
Homebrew gfortran installed. This is both the dev and the production box. Consequences:           - Build everything in Docker for **`linux/arm64`** natively. Never emulate x86 (5× slower). Keep the
Dockerfile multi-arch-clean so it would also build for amd64, but don't build amd64 here.         - Pin MPI to the **10 performance cores** (`mpirun -np 10`); leave the efficiency cores to the OS.  
- Raise Docker Desktop's disk-image limit to ≥ 120 GB before building (Settings → Resources); the current image file is 39 GB with a stopped daemon — run `docker system prune -a --volumes` first and
report what it freed.                                                                             - Expected wall time for the full configuration below: roughly 1–1.5 h per 36-h forecast. Measure it
in Phase 3 and record it; the camp schedule depends on that number.                               - It's a laptop: every long step runs under `caffeinate -i`, and the run script refuses to start on 
battery (`pmset -g batt`).                                                                                                                                                                            
## Non-negotiables (each has been someone's silent failure)                                                                                                                                           
- Model terrain must resolve the Presidentials: max `HGT_M` on the 1 km domain ≥ 1,750 m (summit 1m). The default WPS 30-arcsec terrain yields ~1,400 m. Assert it, and print the summit grid point's 
height.                                                                                           - Model top 10 hPa with a Rayleigh damping layer (`damp_opt = 3`). A 50 hPa lid reflects mountain   
waves back into the field we're producing.                                                        - `w_damping = 0`. We're producing W; don't clip it.                                                
- No cumulus parametrization on either domain.                                                    - Every phase ends with a printed check; don't advance on a run that "probably worked".             
- Pin every version (WRF, WPS, compilers, Python packages). Put the pins in `wrf/README.md`.      - Don't create accounts or spend money without asking. Never print the Blob token. Don't delete     
anything outside `wrf/out/` and Docker's own storage.                                                                                                                                                 
## Phase 1 — Build the image                                                                                                                                                                          
`wrf/docker/Dockerfile` (Ubuntu 24.04, arm64):                                                    - WRF **v4.6.1** and WPS **v4.6.0** from the GitHub release tarballs; gfortran, OpenMPI, zlib, libpn
Jasper, HDF5, NetCDF-C, NetCDF-Fortran.                                                           - WRF: `./configure` with the dmpar GNU option, nesting = basic; `./compile em_real -j 8`. Verify   
`main/wrf.exe`, `real.exe`, `ndown.exe` exist and are non-empty. On arm64 GNU 13+ you will likely `-fallow-argument-mismatch -fallow-invalid-boz` in `configure.wrf` — apply it via `sed` in the      
Dockerfile and say so.                                                                            - WPS: serial GNU option with GRIB2; verify `geogrid.exe`, `ungrib.exe`, `metgrid.exe`.             
- `convert_geotiff` (github.com/openwfm/convert_geotiff) for the custom terrain.                  - A Python 3.12 layer with pinned `wrf-python`, `xarray`, `netCDF4`, `numpy`, `scipy`, `herbie-data`
`rasterio`, `matplotlib`, `boto3`.                                                                                                                                                                    
`wrf/docker/build.sh` builds it with `--platform linux/arm64`. Gate: image builds; running `wrf.exwith no namelist produces its "namelist.input not found" error (that's a pass); print `nproc` and   
confirm 14 visible, and that `mpirun -np 10 hostname` works inside the container.                                                                                                                     
Mounts: `wrf/geog` (static data), `wrf/out` (runs), both gitignored, both on the internal SSD.                                                                                                        
## Phase 2 — Static data and domains                                                                                                                                                                  
- Download the WPS `geog_high_res_mandatory` package (~2.6 GB compressed, ~30 GB on disk) into    `wrf/geog/WPS_GEOG`. Verify the checksum NCAR publishes if available.                               
- **Custom terrain (the Mt Washington item):** fetch USGS 3DEP 1-arc-second GeoTIFFs covering     43.5–45.0 N, 72.5–70.0 W from the public bucket `s3://prd-tnm/StagedProducts/Elevation/1/TIFF/`     
(anonymous, `--no-sign-request`). Mosaic with `rasterio`, convert with `convert_geotiff` into     `wrf/geog/usgs_1s/` (it writes the tiles and the `index`). Add an `HGT_M` block to                  
`wrf/wps/GEOGRID.TBL` with `rel_path = usgs_1s:usgs_1s/` and use `geog_data_res = 'default',      'usgs_1s+default'`.                                                                                 
                                                                                                  `wrf/wps/namelist.wps` — pin:                                                                       
```                                                                                               &share    wrf_core = 'ARW',  max_dom = 2,  interval_seconds = 3600,  io_form_geogrid = 2            
&geogrid  parent_id = 1,1    parent_grid_ratio = 1,3                                                        e_we = 121,151     e_sn = 121,151                                                         
          dx = 3000, dy = 3000                                                                              map_proj = 'lambert', ref_lat = 44.30, ref_lon = -71.30, truelat1 = 43.0, truelat2 = 46.0,
stand_lon = -71.30                                                                                          geog_data_res = 'default','usgs_1s+default'                                               
```                                                                                               Compute `i_parent_start`/`j_parent_start` so d02 is centred on 44.30 N, 71.30 W. d01 = 360 km at 3 k
(HRRR boundary adjusts); d02 = 150 km at 1 km (Presidentials, Carter–Moriah, Pliny/Kilkenny,      Mahoosucs, the lee to Fryeburg). Leave a commented-out 333 m d03 block; do not enable it.           
                                                                                                  Run `geogrid`. Gate: print max `HGT_M` on d02 (≥ 1,750 m required) and the height at 44.2705 N /    
71.3032 W; print d01's max for comparison. Write `wrf/out/checks/hgt_d02.png` so a person can see Notches.                                                                                            
                                                                                                  ## Phase 3 — Boundary data and the first real run                                                   
                                                                                                  `wrf/scripts/fetch-hrrr.py` using `herbie`: for a cycle `YYYYMMDD HHz`, fetch HRRR **pressure-level*
files `hrrr.tHHz.wrfprsfFF.grib2` hourly for FF = 00…36 from `s3://noaa-hrrr-bdp-pds` (anonymous).Only 00/06/12/18Z cycles carry 48 h; we run 36 h. (Native-level `wrfnat` is a later option; pressure
files are the robust default.)                                                                                                                                                                        
- `ungrib` with **`Vtable.RAP.pressure.ncep`** (HRRR shares RAP's layout; its soil levels differ fGFS). Check the ungrib/metgrid logs for: PRES, HGT, TT, UU, VV, RH, PSFC, PMSL, SKINTEMP, SOILHGT,  
LANDSEA, SEAICE, SNOW, and soil T/moisture at all levels. If any are missing, try `Vtable.GFS`, pra table of which Vtable supplies what, and stop if holes remain — don't proceed with missing soil   
fields.                                                                                           - `real.exe` reads `num_metgrid_levels` and `num_metgrid_soil_levels` from the `met_em` files — neve
hardcode them.                                                                                                                                                                                        
First run = **the 2026-10-06 12Z cycle** from the archive (same bucket, dated prefix). It doubles the verification case in Phase 7. On this machine run the full two-domain, 36-h configuration under 
`caffeinate -i` with `mpirun -np 10`. Gate: `wrfout_d02` has the expected frame count,            `rsl.error.0000` ends with SUCCESS COMPLETE WRF, no CFL warnings. **Report wall-clock per forecast  
hour** and total — this number sets the camp schedule.                                                                                                                                                
## Phase 4 — Physics and vertical grid for mountain waves                                                                                                                                             
`wrf/wrf/namelist.input` — pin (both domains unless noted), with the rationale as comments in the file:                                                                                               
```                                                                                               &time_control  history_interval = 60, 15     frames_per_outfile = 1000                              
               iofields_filename = 'iofields_d01.txt', 'iofields_d02.txt'                                        (keep only U, V, W, PH, PHB, T, P, PB, QVAPOR, QCLOUD, PBLH, HGT, U10, V10, T2, PSFC,
RAINNC)                                                                                           &domains       time_step = 15    parent_time_step_ratio = 1, 3    feedback = 0    smooth_cg_topo =  
.true.                                                                                                           e_vert = 81, 81   p_top_requested = 1000                                             
               auto_levels_opt = 2, dzbot = 50., dzstretch_s = 1.1, dzstretch_u = 1.04, max_dz = 4               hybrid_opt = 2                                                                       
&physics       mp_physics = 8, 8      ra_lw_physics = 4, 4    ra_sw_physics = 4, 4    radt = 3                   sf_sfclay_physics = 5, 5    bl_pbl_physics = 5, 5    sf_surface_physics = 2, 2       
               cu_physics = 0, 0      num_land_cat = 21                                           &dynamics      diff_opt = 2, 2    km_opt = 4, 4    damp_opt = 3    zdamp = 5000., 5000.    dampcoef 
0.2, 0.2                                                                                                         w_damping = 0      epssm = 0.5, 0.5    non_hydrostatic = .true., .true.              
&bdy_control   spec_bdy_width = 5, spec_zone = 1, relax_zone = 4                                  ```                                                                                                 
Rationale to record: 10 hPa top + Rayleigh layer prevents lid reflection; `dzbot = 50` with slow  stretching gives ~50–100 m spacing through the 0–4 km wave duct; MYNN for stable nights; Thompson fo
cap/lenticular/rotor cloud; `diff_opt 2 / km_opt 4 / epssm 0.5` for stability over 1 km steep terrno cumulus at these resolutions. If the 1 km nest blows up (CFL), try in order:                     
`use_adaptive_time_step = .true.` with `step_to_output_time = .true.`; `epssm = 0.9`; `time_step =12`. Report which was needed.                                                                       
                                                                                                  Gate: re-run the Oct 6 case with these settings. Print the first 20 eta-level heights (confirm ~50–1
m through 4 km) and max |W| on d02 at ~3 km AGL at 20Z (expect several m/s, not clipped). Re-reporwall time.                                                                                          
                                                                                                  ## Phase 5 — Post-process to the site's shapes, publish to Vercel Blob, wire it in                  
                                                                                                  `wrf/scripts/postprocess.py` (`wrf-python`):                                                        
- Destagger W (`wa`), get `z` and pressure, `interplevel` W and geopotential height onto pressure levels. Read the level lists from the repo so they can't drift: `MAP_LEVELS` and `CROSS_LEVELS` (hPa
`MAP_GRID` (19×13), and `MODEL_DISTANCES` / `alongTransect` / `GLIDER_AREA` from                  `src/lib/wx-datasets.ts`.                                                                           
- Emit `map-field.json`: 247 locations in Open-Meteo's layout — `utc_offset_seconds`, `hourly.timelocal `YYYY-MM-DDTHH:MM`, `hourly.vertical_velocity_<hPa>hPa` in m/s — bilinearly sampled from the 1
km field.                                                                                         - Emit `cross-section-<azimuth>.json` for every 5° bucket 0…355 (15 points × 12 levels × 36 h each —
tiny), same layout with `elevation` and `geopotential_height_<hPa>hPa`, so `fetchModelField(bucketworks unchanged.                                                                                    
- Emit `run.json`: cycle, init time, forecast length, wall time, max summit `HGT_M`, `generated_at`status`.                                                                                           
- Emit `wrf/out/checks/w3km_<cycle>_<hour>.png` per hour for human verification.                                                                                                                      
**Publish to Vercel Blob.** Use the project's existing Blob store (Vercel dashboard → Storage → Blcreate one named `wrf` only if there is none, and say so. Put the read-write token in `wrf/.env` as 
`BLOB_READ_WRITE_TOKEN` — add `wrf/.env` to `.gitignore` *before* writing it, and never print the token. `wrf/scripts/publish.mts` runs with the repo's own `node_modules` (`npm i -D @vercel/blob` at
the repo root) and uploads every file in the run directory with                                   `put(\`wrf/${name}\`, body, { access: "public", addRandomSuffix: false, allowOverwrite: true,       
cacheControlMaxAge: 300, contentType: "application/json" })`                                      — fixed paths, overwritten each cycle, so the site reads stable URLs: `wrf/map-field.json`,         
`wrf/cross-section-<azimuth>.json`, `wrf/run.json`. Upload `run.json` **last**, so a reader never a new stamp pointing at old data. (`allowOverwrite: true` is required in current `@vercel/blob`;    
without it the second cycle fails with "blob already exists".) Print the base URL                 (`https://<store>.public.blob.vercel-storage.com/wrf/`), record it in `wrf/README.md`, and add it to
the Vercel project's env as `WRF_BLOB_BASE_URL` — ask before adding env vars to the Vercel projectneeds a redeploy.                                                                                   
                                                                                                  In the repo: add `wrf-map-field`, `wrf-cross-section`, `wrf-run` cases to `buildUpstreamRequest` in 
`src/lib/wx-datasets.ts` that build their URLs from `process.env.WRF_BLOB_BASE_URL` and return `nu(→ 404, which the views already treat as "no field") when it is unset; `revalidate: 300` for        
`wrf-run`, `900` for the field files. Add a "WRF 1 km" field option in `WaveMap.tsx` and          `WaveCrossSection.tsx` beside "Linear estimate" and "HRRR field", showing the `run.json` cycle stamp; fall back to the HRRR option automatically when `run.json` is missing, older than 9 h, or `status` is not `"ok"` (outside camp the option simply doesn't appear). Read `node_modules/next/dist/docs/` before touching route code, per AGENTS.md.

Gate: `tsc --noEmit`, `npm run lint`, `npm run check:wave` pass; the map renders the Oct 6 WRF field from Blob; the cross-section renders for bucket 315.

## Phase 6 — Camp mode (no monitoring stack)

- `wrf/scripts/run-cycle.sh <YYYYMMDD> <HH>`: battery check → fetch → ungrib → metgrid → real → wrf → postprocess → publish, under `caffeinate -i`, with a lock file, per-step logs in `wrf/out/<cycle>/`, and cleanup of GRIB and `wrfout` older than 3 days (keep `run.json`, logs and check PNGs for 30 days).
- `wrf/launchd/org.mtwashingtonsoaring.wrf.plist`: fires at **01:45 and 07:45 UTC** (the 00Z and 06Z HRRR cycles land ~90 min after cycle time), each calling `run-cycle.sh` for the latest cycle. 00Z → ready ~11 PM EDT for the evening briefing; 06Z → ready ~6 AM for the morning one.
- `wrf/scripts/camp-start.sh` loads the plist and sets `pmset -c sleep 0 disablesleep 1`; `camp-stop.sh` unloads it and restores the previous `pmset` settings (save them first). Both print what they changed.
- On failure: write `run.json` with `status: "failed"`, the failing step and its last 30 log lines, and publish **only that file** — the site shows the stamp and falls back to HRRR. No email, no ntfy.

## Phase 7 — Verification against the Oct 6 SkySight field

Using the Oct 6 12Z run from Phase 4, at **16:00 EDT, 3,000 m ASL**, SkySight showed: NE–SW bands perpendicular to a 300–315° flow, ~12 km wavelength, sink over the Mt Washington crest, primary lift over Pinkham Notch/Wildcat, secondary near Route 113, peaks ±8 kt. From our d02 field print: dominant wavelength along the 315° transect through the Glider Area centre (peak of the 1-D spectrum of W), the primary lift's position relative to the summit, peak |W| at 3 km, and the summit-level wind at 1,917 m. Report agreement or disagreement plainly. Do not tune anything to match the screenshot — the point is to learn whether the pinned configuration is right.

## Reporting

End with: the prune result and disk used by `wrf/`; every gate's printed values; the Vtable and any physics fallbacks that were needed; wall time per forecast hour on 10 cores; the Blob base URL and the three published paths; the Phase 7 comparison; and what you could not verify. If any pinned setting is wrong for WRF 4.6.1 or physically mistaken, stop and say why rather than substituting silently.
