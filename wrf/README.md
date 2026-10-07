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
| micromamba | 2.9.0 linux-aarch64 binary — SHA-256 `9f93b974adcb4d166996af969b6cd371287d1a3e52733704727884d9b74cb7a7` |
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
- `launchd/` — the camp schedule plist.

## Build and smoke checks

```bash
wrf/docker/build.sh                         # mtw-wrf:4.6.1 (linux/arm64)
docker run --rm -v "$PWD/wrf:/wrf" mtw-wrf:4.6.1 wrf.exe    # must print 'namelist.input not found'
docker run --rm mtw-wrf:4.6.1 nproc                          # 14 visible cores
docker run --rm mtw-wrf:4.6.1 mpirun -np 10 hostname         # runs as root: OMPI_ALLOW_* are baked in
```

## Measured — 2026-10-06 12Z case (36 h, mtw-wrf:4.6.1, mpirun -np 10)

- WPS per 12–13-time chunk: ungrib NAT ~29 s/time, ungrib SOIL ~2 s/time,
  metgrid ~25 s/time; real.exe (37 times) ~20 s.
- **wrf.exe 36 h: 14,657 s = 407.1 s per forecast hour** (4 h 04 m), 0 CFL
  warnings, frames exact (d01 37 hourly, d02 145 at 15 min). Cost is strongly
  diurnal: ~350 s/h overnight, ~800–980 s/h in daylight (RRTMG radiative work),
  so the 6-h daytime smoke's 521 s/h was a high-water sample, not the average.
- postprocess (145 frames, 72 cross-sections, 37 check PNGs): ~5 min.
- fetch: 37 × ~660 MB NAT (~24 GB) + ~1 GB soil subsets — ~35 min on the home link.
- Full cycle wall on the MacBook: ~5–5.5 h (fetch + WPS + run + postprocess).

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

Disk: `wrfout` is kept **1 day** (the JSON products are what the site needs;
`run.json`, logs and check PNGs persist 30 days), and `iofields_d02.txt` drops
U, V, QCLOUD and the hydrometeors — roughly a third lighter per run. Check
PNGs are named by valid datetime (`w3km_<cycle>_v<YYYY-MM-DDTHH>Z.png`); the
old hour-of-day names collided across days in a 36-h run.
