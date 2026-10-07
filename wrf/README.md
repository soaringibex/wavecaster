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
| Vtable | `Vtable.RAP.pressure.ncep` from WPS 4.6.0 (`wrf/wps/`) |
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
- **Vertical grid**: `max_dz = 4` in PROMPT.md is metres in WRF 4.6.1 and makes
  `real.exe` fatal ("Upper levels may be too thick"). Retuned per owner:
  `dzbot=50, dzstretch_s=dzstretch_u=1.035, max_dz=1000, e_vert=100`.
- **Disk policy**: GRIB deleted after a successful metgrid; `met_em` + `wrfout`
  kept 3 days; logs/`run.json`/check PNGs 30 days.
- **Vtable (audited 2026-10-07 against HRRR `wrfprs` 2026-10-06 12Z f00)**: the
  stock `Vtable.RAP.pressure.ncep` supplies no soil, `LANDSEA` or `SEAICE`;
  `Vtable.GFS` loses `PMSL` and its depth-ranged soil rows do not match HRRR's
  9-level soil encoding (met_em comes out with zero soil levels). The pipeline
  therefore uses **`wrf/wps/Vtable.HRRR.wrfprs`**, built from the RAP pressure
  table plus the soil/land/sea-ice rows of `Vtable.RAP.hybrid.ncep`; the
  met_em audit shows `SOILT`/`SOILM` with 9 levels, `LANDSEA`, `SEAICE`, and
  `NUM_METGRID_SOIL_LEVELS = 9` — everything real.exe needs, from the
  pressure-level files alone (no `wrfsfc`/`wrfnat` fetch required).
- **WPS `parse_table` quirks found while building that table**: comments are
  fine anywhere and must be followed by... the data rows must end with a
  `-----` separator line — reading to EOF without one is "Read error 2"; and a
  `GRIB1|` column-header line left inside the rows is a fatal
  "Bad integer for item 1". Both handled in the committed table.
- **`num_metgrid_levels`**: met_em carries `BOTTOM-TOP_GRID_DIMENSION` (levels+1)
  and `NUM_METGRID_SOIL_LEVELS`; the run script derives the namelist values
  from those (40 and 9 for this case), never hardcoding them.
- **Phase 3** is a 6-hour smoke run on the final namelist (not a shipped-default
  baseline); Phase 4 extends the same case to 36 h.
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
