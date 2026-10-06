# WRF pipeline — build and run notes

Pins are filled in as the image is built (each SHA-256 is recorded here and in the
Dockerfile). Nothing here is secret except `wrf/.env`, which is gitignored.

| Component | Pin |
|---|---|
| WRF | v4.6.1 — GitHub release tarball — SHA-256: _pending_ |
| WPS | v4.6.0 — source archive from tag (`codeload.github.com/wrf-model/WPS/tar.gz/refs/tags/v4.6.0`; release-asset URL is a 404) — SHA-256: _pending_ |
| convert_geotiff | github.com/openwfm/convert_geotiff — commit: _pending_ |
| Base image | `ubuntu:24.04` (linux/arm64) |
| Compilers | Ubuntu 24.04 GCC / gfortran _version pending_ |
| MPI | OpenMPI _version pending_ (Ubuntu package) |
| NetCDF C / Fortran | _version pending_ (Ubuntu packages) |
| HDF5 / Jasper / zlib / libpng | _version pending_ (Ubuntu packages) |
| Python | 3.12 + pinned: wrf-python, xarray, netCDF4, numpy, scipy, herbie-data, rasterio, matplotlib, boto3 — _versions pending_ (`pip freeze` captured at image build) |
| Vtable | `Vtable.RAP.pressure.ncep` (from WPS v4.6.0) |
| HRRR data | `s3://noaa-hrrr-bdp-pds` (anonymous HTTPS), pressure files `hrrr.tHHz.wrfprsfFF.grib2` |
| 3DEP terrain | `s3://prd-tnm/StagedProducts/Elevation/1/TIFF/current/n43..n44w071..w073` (anonymous) |
| Blob base URL | _pending — the owner creates the store under the mtwashingtonsoaring Vercel project_ |

## Layout

- `docker/` — the image (WRF + WPS + convert_geotiff + Python layer) and its build script.
- `geog/` — static data (gitignored): `WPS_GEOG/`, USGS 1″ tiles, `usgs_1s/` output.
- `wps/`, `wrf/` — the pinned namelists and tables the runs copy into each cycle directory.
- `scripts/` — fetch, post-process, publish, camp-mode scripts.
- `out/` — runs (gitignored): `out/<cycle>/` per cycle, `out/checks/` for gate artifacts.
- `launchd/` — the camp schedule plist.

## Status

Phase 0 in progress. Gate results are recorded in the session log and in `out/checks/`.
