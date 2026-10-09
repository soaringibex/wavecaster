# WRF pipeline — build and run notes

Everything is pinned. WRF and WPS are built from SHA-verified tarballs; the
conda-forge Python layer resolves at image-build time and its exact manifest
lands at `/opt/venv/conda-explicit.txt` inside the image.

| Component | Pin |
|---|---|
| Base image | `ubuntu:24.04@sha256:534baea6a22c03a63003dbc8dbe78fe34bc0d7e595d9a9dc9834884ff530eb55` (multi-arch index) |
| WRF | v4.6.1 release tarball — SHA-256 `b8ec11b240a3cf1274b2bd609700191c6ec84628e4c991d3ab562ce9dc50b5f2` |
| WPS | v4.6.0 source archive from tag — SHA-256 `ca7bbfc6c28a107c6eb00ded70e693f5c9a3926ecde7656f49e306c9eb9a309b` (no release asset exists) |
| Jasper | 2.0.33 (source) — SHA-256 `28d28290cc2eaf70c8756d391ed8bcc8ab809a895b9a67ea6e89da23a611801a` (Ubuntu 24.04 dropped `libjasper-dev`) |
| convert_geotiff | commit `da7003fe8a99b1adb9cf00baab9b36b693554b2b` |
| micromamba | 2.9.0 per-arch binary — aarch64 `9f93b974adcb4d166996af969b6cd371287d1a3e52733704727884d9b74cb7a7`, x86_64 `366cd9cd8be14df1ab8ed50352a82111082a36686b2d389fdb79a92c3fafb3e3` (both SHA-verified in the Dockerfile) |
| Compilers | Ubuntu 24.04: gcc/gfortran 13.2.0 |
| MPI | OpenMPI 4.1.6 (`libopenmpi-dev`) |
| NetCDF / HDF5 / zlib / libpng | Ubuntu: netcdf-c 4.9.2, netcdf-fortran 4.6.0, hdf5 1.10.10, zlib 1.3, libpng 1.6.43 |
| Python | conda-forge python 3.12 + wrf-python 1.4.2, xarray, netCDF4, scipy, matplotlib, rasterio, boto3, herbie-data — exact manifest `/opt/venv/conda-explicit.txt` in the image (filled in below after the first build) |
| Vtable | atmosphere: stock `Vtable.RAP.hybrid.ncep` (`wrfnat`); soil prefix: `Vtable.HRRR.wrfprs` (the audited merge) |
| HRRR | `s3://noaa-hrrr-bdp-pds`, `hrrr.tHHz.wrfprsfFF.grib2` (anonymous HTTPS/S3) |
| 3DEP terrain | `s3://prd-tnm/StagedProducts/Elevation/1/TIFF/current/…` (anonymous), 6 tiles n43/n44 × w071/w072/w073 |
| Blob base URL | _pending — owner creates the store under the mtwashingtonsoaring Vercel project_ |

## Recorded deviations from PROMPT.md (all deliberate; see `PLAN.md`)

- **WPS aarch64**: WPS 4.6.0 ships no aarch64 entry; its x86_64 gfortran entry
  carries no x86-only flags, so the `#ARCH` line is patched in the image.
- **Compiler flags**: `-fallow-argument-mismatch -fallow-invalid-boz` appended to
  WRF's `FCBASEOPTS_NO_G` (GNU 13 on arm64; WRF 4.6.1 already carries them via
  `FCCOMPAT`, so duplicates are harmless); `-fallow-argument-mismatch` appended
  to WPS's `FFLAGS`/`F77FLAGS`.
- **WPS netCDF-Fortran link**: WPS's configure probes for
  `$NETCDF/lib/libnetcdff.a` and misses Ubuntu's multiarch path, so the
  gfortran entry never gets `-lnetcdff` and metgrid cannot resolve the `nf_*`
  symbols in WRF's `libwrfio_nf.a`. The image appends `-lnetcdff` to the
  `configure.wps` link line. (Same root cause makes the optional util targets
  unbuildable as shipped — this pipeline does not build them.)
- **wrf-python** comes from conda-forge (linux-aarch64, 1.4.2): its pip sdist
  does not build on Python 3.12 (`numpy.distutils` was removed). Same API
  (`destagger`, `to_np`, `interplevel`).
- **Vertical grid (owner-retuned 2026-10-07)**: `dzbot=50, dzstretch_s=dzstretch_u=1.035,
  max_dz=1000, e_vert=100` (`max_dz=4` in PROMPT.md is metres in WRF 4.6.1 and makes
  real.exe fatal — "Upper levels may be too thick"); `p_top_requested = 1800` — the
  data ceiling, see the lid note below.
- **Disk policy**: GRIB deleted after a successful metgrid; `met_em` + `wrfout`
  kept 3 days; logs/`run.json`/check PNGs 30 days.
- **Lid / product pin superseded (owner, 2026-10-07)**: PROMPT.md's "10 hPa top from
  HRRR" is impossible — real.exe refuses any top below the data's top-level pressure,
  and HRRR tops out at **50 hPa** (`wrfprs`) and **~17.3 hPa** (`wrfnat`; HRRRv4 is
  documented at 15 hPa). The `wrfprs` + `Vtable.RAP.pressure.ncep` pin was also wrong
  in a second way: that Vtable carries no soil/LANDSEA/SEAICE rows. The pipeline runs
  **`wrfnat`** for the atmosphere with **`Vtable.NAT.trimmed`** — the stock hybrid
  table minus the hydrometeor rows (WRF initializes condensate to zero; they were
  3.8 GB of the 6.1 GB per-time intermediate and pushed ungrib past the VM's memory)
  and minus the soil rows (the native file's two SOILW records must not shadow the
  SOIL prefix) — plus a **~1 GB/cycle byte-range soil subset** from `wrfprs`
  (`fetch-soil.py`, ~27 MB/hour), merged by metgrid as `fg_name = 'NAT','SOIL'`.
  `p_top_requested = 1800` (~26.9 km top), and `check-levels.py` gates the Rayleigh
  sponge (`zdamp = 5000` m) to hold at least 5–6 levels. `Vtable.HRRR.wrfprs` remains
  in the repo as the soil prefix's table. Native intermediates are ~2 GB per time, so
  the cycle processes in chunks and deletes each chunk's intermediates after metgrid
  (~74 GB if retained for all 37 times).
- **Documented fallback (not built)**: if the ~24 GB/cycle native fetch becomes a
  problem, use `wrfprs` plus a **GFS 0.25° upper-level byte-range subset** as a third
  `fg_name` for a true 10-hPa lid — the seam sits at 50 hPa, above the waves and below
  the sponge. Same merge machinery as the soil subset.
- **WPS `parse_table` quirks found while building that table**: comments are
  fine anywhere and must be followed by... the data rows must end with a
  `-----` separator line — reading to EOF without one is "Read error 2"; and a
  `GRIB1|` column-header line left inside the rows is a fatal
  "Bad integer for item 1". Both handled in the committed table.
- **`num_metgrid_levels`**: met_em carries the `num_metgrid_levels` dimension (41 for
  the pressure path, 51 for the native path) and `NUM_METGRID_SOIL_LEVELS`; the run
  script derives both namelist values from the file at run time (51 and 9 for the
  current path), never copying them in once.
- **Phase 3** is a 6-hour smoke run on the final namelist (not a shipped-default
  baseline); Phase 4 extends the same case to 36 h.
- **Native fetch subsetting (2026-10-07)**: `fetch-hrrr.py --product nat --subset`
  downloads only the messages `Vtable.NAT.trimmed` consumes, via .idx byte
  ranges — 362 MB per hour instead of 663 MB. Herbie's subset download is
  renamed to the canonical `hrrr.tHHz.wrfnatfFF.grib2` so every downstream
  script is mode-agnostic (existence is the resume signal; switching
  subset↔full in one cycle dir needs the GRIB cache removed). Validated
  through the production pipeline — `cycle-steps.sh chunk` on the subset
  reproduces the full-file `met_em` **field-for-field** (all 88 variables,
  51 levels, 9 soil levels).
- **WRF runtime files**: a custom run directory has none of WRF's `run/` data
  files, and `wrf.exe` fails at startup with a clear FATAL naming the missing
  one (`CAMtr_volume_mixing_ratio` for `ghg_input=1`, then `LANDUSE.TBL`). The
  `prepare` step copies the physics tables and RRTMG inputs
  (`LANDUSE/SOILPARM/VEGPARM/GENPARM/URBPARM*.TBL`, `RRTMG_LW_DATA`,
  `RRTMG_SW_DATA`, `CAMtr_volume_mixing_ratio`, `ozone*.formatted`).
- **ungrib walks the namelist window** (2026-10-07): it does not filter the
  linked GRIBs — it iterates `start_date..end_date` hourly and writes an
  intermediate for each time it *finds*. Missing times print
  `ERROR: Data not found` and it still exits 0, so a window that does not match
  the chunk's GRIBs silently writes nothing. The chunk step therefore sets the
  window to the chunk before ungrib and gates on the intermediate file count
  (NAT:/SOIL: == expected), which is what caught the leftover-window bug.
- **Static domain** (2026-10-08, Linux port): the committed `cycle-steps.sh`
  never invoked `geogrid.exe`, so a fresh cycle directory could not run
  metgrid (it needs `geo_em.d0*.nc`). The domain and terrain never change
  between cycles, so `cycle-steps.sh static-geogrid` now builds the pair once
  into `wrf/static/` (gitignored), gated by `check-geogrid.py` (d02 max HGT_M
  ≥ 1750 m), and caches a sha256 of the `namelist.wps` `&share`/`&geogrid`
  blocks plus `GEOGRID.TBL`. Change either and the next cycle rebuilds;
  otherwise `prepare` just links the two files into the cycle directory.
  Same `namelist.wps` and pinned `GEOGRID.TBL` — no science change.
- **`wrf-wind.json` vs `iofields_d02.txt`** (2026-10-09, Linux port):
  `2a90f26` dropped U/V (with QCLOUD and the hydrometeors) from d02 output,
  but `f56ca04`'s `wrf-wind.json` — and the wind section of
  `phase7-verify.py` — read U/V from the d02 wrfout. The Mac's reference
  output predated the drop, so the conflict was latent and only surfaced on
  a fresh cycle. `iofields_d02.txt` now excludes only QCLOUD and the
  hydrometeors; U/V are kept. Output-only change; the 36-h d02 wrfout is
  7.8 GB → 9.6 GB.
- **Engine detection** (2026-10-09, Linux port): a `docker` CLI appeared on
  the server with no daemon behind it; `run-cycle.sh` and `build.sh` now
  choose docker only when `docker info` succeeds, otherwise podman. A bare
  CLI must not shadow a working podman.
- **USGS 3DEP tile set**: the staged tiles are named by their **NW corner**, so
  the demanded 43.5–45.0 N window needs the `n44`+`n45` rows × `w071..w073`
  (an earlier `n43`+`n44` fetch stopped at 44 N and missed the range).
- **convert_geotiff 0.1.0 — two anomalies, handled in `build-terrain.py`**:
  its tiled copy loop never clamps to the image edge (heap overflow/SIGSEGV on
  partial edge tiles), so the mosaic is padded to multiples of the source
  TIFFs' 512-px internal tiles; and it mis-reads `ModelPixelScale` (writes
  stack residue — observed `dx = 2.743193e-04` against the true `2.777778e-04`,
  a ~1.2 km terrain displacement), so the script rewrites the four
  georeference fields in `usgs_1s/index` from the mosaic's own transform after
  asserting the origin agrees within ~10 m.
- **GEOGRID.TBL HGT_M for `usgs_1s`**: `four_pt+average_4pt` interpolation
  (the 30″ recipes' `average_gcell(4.0)` averages ~4 km and flattens the
  summit), and the block's `smth-desmth` smoothing is disabled (it removes
  ~130 m from the Presidential peaks; d02 max 1825 m unsmoothed vs 1693 m with
  it). Gate: d02 max HGT_M 1824.8 m at 44.2685/−71.3063 — 310 m from the
  summit, the expected bilinear result on a 1 km grid; d01 max 1490.0 m.
- **Phase 3** is a 6-hour smoke run on the final namelist (not a shipped-default
  baseline); Phase 4 extends the same case to 36 h.

## Layout

- `docker/` — the image (Dockerfile, build.sh). Sources are cached under
  `docker/src/` (gitignored) and SHA-verified inside the Dockerfile.
- `geog/` — static data (gitignored): `WPS_GEOG/` (29 GB), `usgs_1s_tiles/`,
  `usgs_1s_mosaic.tif`, `usgs_1s/` (convert_geotiff output).
- `wps/`, `wrf/` — namelists and tables copied into each cycle directory.
- `scripts/` — fetch, terrain, post-process, publish, camp-mode scripts.
- `out/` — runs (gitignored): `out/<cycle>/`, `out/checks/`, `out/logs/`.
- `launchd/`, `systemd/` — the camp schedules (macOS launchd plist, Linux
  systemd user service + timer).

## Build and smoke checks

```bash
wrf/docker/build.sh                         # mtw-wrf:4.6.1, native host arch, docker or podman
docker run --rm -v "$PWD/wrf:/wrf" mtw-wrf:4.6.1 wrf.exe    # must print 'namelist.input not found'
docker run --rm mtw-wrf:4.6.1 nproc                          # 14 cpus on the MacBook, 32 on the server
docker run --rm mtw-wrf:4.6.1 mpirun -np 16 hostname         # OMPI_ALLOW_* are baked in
```

## Measured — 2026-10-06 12Z case (36 h, mtw-wrf:4.6.1, mpirun -np 10)

- WPS per 12–13-time chunk: ungrib NAT ~29 s/time, ungrib SOIL ~2 s/time,
  metgrid ~25 s/time; real.exe (37 times) ~20 s.
- **wrf.exe 36 h: 14,657 s = 407.1 s per forecast hour** (4 h 04 m), 0 CFL
  warnings, frames exact (d01 37 hourly, d02 145 at 15 min). Cost is strongly
  diurnal: ~350 s/h overnight, ~800–980 s/h in daylight (RRTMG radiative work),
  so the 6-h daytime smoke's 521 s/h was a high-water sample, not the average.
- postprocess (145 frames, 72 cross-sections, 37 check PNGs): ~5 min.
- fetch: 37 × **362 MB** NAT subset (`--subset` via .idx byte ranges, ~13.5 GB)
  + ~1 GB soil subsets — ~20 min on the home link.
- Full cycle wall on the MacBook: ~5–5.5 h (fetch + WPS + run + postprocess).

## Measured — 2026-10-06 12Z case (36 h, mtw-wrf:4.6.1, mpirun -np 16, Linux server)

Machine: AMD Ryzen 9 9950X — 16 physical cores / 32 threads (CPU N and N+16
are SMT siblings), **60 GB RAM**, Ubuntu 24.04, rootless podman 5.7, ~1.6 TB
free. The same replay as above, on the production Linux host:

- **Binding**: OpenMPI 4.1's default here is *no binding at all*
  (`--report-bindings` says "rank N is not bound"), so both mpirun lines carry
  `--map-by core --bind-to core`: ranks 0–15 land one per physical core, each
  bound to both hyperthreads of its own core (`core 0[hwt 0-1]` …
  `core 15[hwt 0-1]`), no siblings shared between ranks.
- **Peak memory**: container cgroup `memory.peak` **14.4 GB** (30-s sampler
  high-water 14.3 GB) — comfortable in 60 GB.
- geogrid (static, hash-keyed, off the cycle path): **1 s** for both domains.
- fetch: 3,044 s (NAT) + 282 s (soil) = 55 min.
- WPS chunks (37 times): 450 + 445 + 383 = **1,278 s** (~34.5 s/time).
- real.exe: **15 s**.
- **wrf.exe 36 h: 26,999 s = 750.0 s per forecast hour** (7 h 30 m), 0 CFL
  mentions in any of the 16 rank logs, frames exact (d01 37 hourly, d02 145
  at 15 min).
- postprocess (145 frames, 72 cross-sections, 37 check PNGs, `wrf-wind.json`):
  **300 s**.
- Full cold cycle: **~8 h 52 m** (fetch + WPS + real + wrf + postprocess).
  d02 `wrfout` is 9.6 GB with U/V retained; GRIBs are deleted after metgrid,
  so every cycle refetches.

## Field agreement — 2026-10-06 20Z at 3 km on d02 (Linux replay)

`python /wrf/scripts/phase7-verify.py --time 2026-10-06_20:00:00` on the
replay above, against the Mac reference values:

| Quantity | Mac | Linux (9950X) | Difference |
|---|---|---|---|
| max W | +9.87 m/s | +9.88 m/s | +0.01 (+0.1 %) |
| min W | −9.67 m/s | −9.67 m/s | 0.00 |
| dominant wavelength, 315° transect | 9.3 km | 9.4 km | +0.1 km |
| summit (W at 3 km) | −2.8 m/s | −3.17 m/s | −0.37 m/s |
| Pinkham (Notch point) | +5.3 m/s | +6.00 m/s | +0.70 m/s |
| Glider Area centre | +5.5 m/s | +5.64 m/s | +0.14 m/s |

Stop conditions (>10 % on the peaks, wavelength outside 8.8–9.8 km): **not
triggered** — the peaks agree to 0.1 % and the wavelength is 9.4 km. The
summit and Pinkham point values differ by up to 0.7 m/s (13 % at single
points in a steep terrain gradient), in line with codegen/CPU rounding on a
sensitive wave field; nothing was tuned. Supporting output: strongest sink
within 5 km of the summit −5.74 m/s; primary lift cells +9.88 m/s at
(44.224, −71.256), +9.65 at (44.250, −71.118), +8.29 at (44.214, −71.018);
median 3 km wind 40.6 kt from 305° and summit-column 48.6 kt from 304° —
the NE–SW bands perpendicular to a ~300–315° flow.

## Camp schedule (owner, 2026-10-07)

Two cycles a day, each length matched to the briefing it serves (in
`run-cycle.sh`; `--hours` overrides):

| fire | cycle | run_hours | covers through | product |
|---|---|---|---|---|
| 19:45 UTC (15:45 EDT) | 18Z | 28 h | 22Z the next day (6 PM EDT) | evening + the whole next flying day |
| 07:45 UTC (03:45 EDT) | 06Z | 18 h | 00Z | morning |

`wrf/launchd/org.mtwashingtonsoaring.wrf.plist` carries these fires (EDT
mapping; EST lands one hour later in UTC and `latest` still selects the right
cycle). Load with `camp-start.sh`, unload with `camp-stop.sh`.

Timing expectation from the measured diurnal profile (~350 s/h overnight,
~430–980 s/h in daylight — the 407 s/h 36-h average does **not** apply to
these windows, each of which spans a different mix of cheap night and
expensive daylight hours): the 28-h 18Z run ≈ 5 h of model time (ready
~9:30–10 PM EDT including fetch and WPS); the 18-h 06Z run ≈ 3.5 h (ready
~7:45–8 AM EDT).

### Projection from the measured Linux numbers

Cost model from the replay: ≈ 750 s/forecast-hour (wrf) + 34.5 s (WPS) +
90 s (NAT fetch) + 7.6 s (soil fetch) ≈ **882 s per forecast hour**, plus
~315 s fixed (real + postprocess), counted over `--hours + 1` hourly times.

| fire | cycle | run_hours | start (America/New_York) | projected ready | deadline | result |
|---|---|---|---|---|---|---|
| 19:45 UTC | 18Z | 28 h | 15:45 EDT | **22:40 EDT** (02:40 UTC) | before the 03:45 EDT morning fire | fits, 5 h 05 m margin |
| 07:45 UTC | 06Z | 18 h | 03:45 EDT | **08:14 EDT** (12:14 UTC) | ready by 07:00 EDT | **misses by 1 h 15 m** |

**The 06Z run is the one that misses.** The largest `--hours` that fits by
07:00 EDT with this cost model is **12 h** (ready ≈ 06:47 EDT; 13 h lands at
07:01:47). The 18Z run needs no truncation — it clears the next morning's
fire with hours to spare (and if the evening product were instead required
by a 19:45 EDT cutoff, the largest fit would be 15 h, though it would then
stop producing at 09Z — the owner's call, not a tuning decision made here).

Disk: `wrfout` is kept **1 day** (the JSON products are what the site needs;
`run.json`, logs and check PNGs persist 30 days), and `iofields_d02.txt` drops
QCLOUD and the hydrometeors (U/V are kept — `wrf-wind.json` and
`phase7-verify.py` read them). Check
PNGs are named by valid datetime (`w3km_<cycle>_v<YYYY-MM-DDTHH>Z.png`); the
old hour-of-day names collided across days in a 36-h run. A `KEEP` file inside
a cycle directory pins it — the retention pass skips it entirely (wrfout,
met_em, and the 30-day directory sweep).

## Running on a Linux server (port notes)

The same tree runs on x86_64 Linux and arm64 macOS; the science (namelists,
Vtables, GEOGRID.TBL, fetch, post-process, publish contract) is identical.
What differs on the server:

- **Image**: `wrf/docker/build.sh` builds `mtw-wrf:4.6.1` natively for the
  host arch with docker or rootless podman (`--format docker`, no emulation),
  passing the host's physical core count as `BUILD_JOBS`. Per `TARGETARCH`
  the Dockerfile selects WRF's own GNU-dmpar configure entry (7 on arm64,
  34 on amd64 — both re-derived from WRF 4.6.1's arch-filtered menu and the
  `arch/configure.defaults` entry count) and the matching micromamba 2.9.0
  binary (aarch64 `9f93b974…`, x86_64 `366cd9cd…`, SHA-verified in the
  Dockerfile). WPS compiles with menu option 1 on both arches: the stock
  x86_64 entry matches here, and its `#ARCH` line is extended to aarch64 in
  the image.
- **`wrf/docker/src/`** (gitignored): copy the SHA-pinned tarballs and
  `convert_geotiff/` from the Mac, then add the x86_64 micromamba —
  `mamba-org/micromamba-releases` asset `micromamba-linux-64`, saved as
  `micromamba-2.9.0-linux-x86_64` (its sha256 is recorded above). The
  Dockerfile installs whichever `micromamba-2.9.0-linux-*` is present.
- **Container engine**: `run-cycle.sh` uses docker when present, else podman
  with `--userns=keep-id --shm-size=2g` — the default 64 MB `/dev/shm` is
  too small for OpenMPI's shared-memory transport at 16 ranks — and `:Z` on
  the bind mounts only under enforcing SELinux.
- **Ranks**: `WRF_NP` is forwarded into the container (`-e WRF_NP=…`);
  `cycle-steps.sh` reads it for both mpirun lines. The server unit sets
  `WRF_NP=16` (one rank per physical core; the 9950X's CPU N and N+16 are
  SMT siblings). The Mac default stays 10.
- **Schedule**: `wrf/systemd/wavecaster.{service,timer}` fire 07:45 and
  19:45 UTC with `Persistent=false`; `camp-start.sh` / `camp-stop.sh` copy
  the units and enable/disable the timer with `systemctl --user` on Linux,
  keeping their macOS pmset/launchd path. The service clears a stale
  `wrf/out/.lock` first (`ExecStartPre`) and `TimeoutStartSec=4h30min` kills
  a hung run before the next fire. User timers only fire while the account
  is logged in unless the admin runs `loginctl enable-linger <user>`. The
  units assume the repo lives at `~/wavecaster`; adjust `%h/wavecaster` in
  the ExecStart/ExecStartPre lines if it is cloned elsewhere.
- **Terrain**: `build-terrain.py` reuses an existing `geog/usgs_1s/` plus
  `usgs_1s_mosaic.tif` when its format already matches this script's output
  (index georeference vs the mosaic transform, tiles present); it never
  downloads — the local `geog/usgs_1s_tiles/` are the only input. Pass
  `--force` to rebuild the mosaic and re-run convert_geotiff offline.
- **Host scripts**: GNU/BSD `date` and `df` are picked per host, the battery
  gate and `caffeinate` are no-ops where `pmset` is absent, and the host-side
  `.mts` scripts (export-grid, publish) run under the `tsx` devDependency
  when Node lacks native type stripping (fallback: bare `node`).
- **Prerequisites**: docker or podman, git, bash, python3, Node ≥ 20.12, and
  one `npm install` in the repo root (the publish/export-grid scripts import
  `@vercel/blob` and `tsx` from there).
- **Schedule with cron** (if systemd user units are unwanted — a server runs
  UTC, so no launchd, sleep management or battery gate):

```cron
45 19 * * * /path/to/wavecaster/wrf/scripts/run-cycle.sh latest >> /path/to/wavecaster/wrf/out/logs/cron.log 2>&1
45 7  * * * /path/to/wavecaster/wrf/scripts/run-cycle.sh latest >> /path/to/wavecaster/wrf/out/logs/cron.log 2>&1
```

`wrf/.env` carries the one line the publisher needs
(`BLOB_READ_WRITE_TOKEN=…`); everything else — fetch, chunks, retention,
publish — behaves exactly as on the Mac.
