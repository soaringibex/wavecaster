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
  WRF's `FCBASEOPTS_NO_G`; `-fallow-argument-mismatch` to WPS's `FFLAGS`/`F77FLAGS`
  (GNU 13 on arm64).
- **wrf-python** comes from conda-forge (linux-aarch64, 1.4.2): its pip sdist
  does not build on Python 3.12 (`numpy.distutils` was removed). Same API
  (`destagger`, `to_np`, `interplevel`).
- **Vertical grid**: `max_dz = 4` in PROMPT.md is metres in WRF 4.6.1 and makes
  `real.exe` fatal ("Upper levels may be too thick"). Retuned per owner:
  `dzbot=50, dzstretch_s=dzstretch_u=1.035, max_dz=1000, e_vert=100`.
- **Disk policy**: GRIB deleted after a successful metgrid; `met_em` + `wrfout`
  kept 3 days; logs/`run.json`/check PNGs 30 days.
- **`num_metgrid_levels` / `num_metgrid_soil_levels`**: never hardcoded — the run
  script reads them from the `met_em` headers; the namelist carries a `-999`
  sentinel so a stray `real.exe` fails loudly.
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
