#!/usr/bin/env python3
"""Mosaic the USGS 3DEP 1-arcsecond tiles and convert them to WPS geog tiles.

Runs inside the image (rasterio + convert_geotiff on PATH). Writes:
  /wrf/geog/usgs_1s_mosaic.tif   merged 1″ elevation (overwritten each run)
  /wrf/geog/usgs_1s/             geogrid index + tiles, referenced by the
                                 HGT_M usgs_1s entry in wrf/wps/GEOGRID.TBL

Coverage: USGS tiles are named by their NORTH-WEST corner, so the demanded
43.5–45.0 N / 72.5–70.0 W window (plus margin to tile edges) is
n44w071..n44w073 (43–44 N) + n45w071..n45w073 (44–45 N).

Two anomalies are handled explicitly here:
  * nodata cells (-999999, ocean/edges) are written as 0 so ABC GEOGRID.TBL's
    fill_missing=0. sees them as missing — otherwise -999999 would truncate
    into garbage in the 2-byte geogrid integers.
  * the mosaic is padded to multiples of the source TIFFs' 512-px internal
    tile size. convert_geotiff 0.1.0 (pinned commit da7003fe) overflows its
    output buffer on partial edge tiles — its tiled copy loop never clamps to
    the image edge — and segfaults on any of these 3612×3612 tiles. Padding
    removes partial tiles without patching the tool.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import rasterio
from rasterio.merge import merge

ROOT = Path("/wrf")
TILE_DIR = ROOT / "geog" / "usgs_1s_tiles"
MOSAIC = ROOT / "geog" / "usgs_1s_mosaic.tif"
OUT_DIR = ROOT / "geog" / "usgs_1s"
NODATA = -999999.0
INTERNAL_TILE = 512  # the 3DEP staged tiles' internal tiling

SUMMIT_LAT, SUMMIT_LON = 44.2705, -71.3032
TILE_NAMES = [f"USGS_1_n{lat}w{lon:03d}.tif" for lat in (44, 45) for lon in (71, 72, 73)]


def build_mosaic() -> Path:
    tiles = [TILE_DIR / name for name in TILE_NAMES]
    missing = [t for t in tiles if not t.exists()]
    if missing:
        raise SystemExit(f"missing USGS tiles: {[m.name for m in missing]}")

    datasets = [rasterio.open(t) for t in tiles]
    try:
        mosaic, transform = merge(datasets)
        profile = datasets[0].profile.copy()
    finally:
        for dataset in datasets:
            dataset.close()

    data = mosaic[0]
    nodata_cells = int((data == NODATA).sum())
    data = np.where(data == NODATA, np.float32(0.0), data)

    row = int(round((transform.f - SUMMIT_LAT) / (-transform.e)))
    col = int(round((SUMMIT_LON - transform.c) / transform.a))
    print(f"summit cell in mosaic: {float(data[row, col]):.1f} m at row/col {row},{col}")

    height, width = data.shape
    padded_h = -(-height // INTERNAL_TILE) * INTERNAL_TILE
    padded_w = -(-width // INTERNAL_TILE) * INTERNAL_TILE
    if (padded_h, padded_w) != (height, width):
        padded = np.zeros((padded_h, padded_w), dtype=data.dtype)
        padded[:height, :width] = data
        data = padded

    profile.update(
        transform=transform,
        height=padded_h,
        width=padded_w,
        count=1,
        dtype=data.dtype,
        compress="deflate",
        tiled=True,
        blockxsize=INTERNAL_TILE,
        blockysize=INTERNAL_TILE,
    )
    with rasterio.open(MOSAIC, "w", **profile) as dst:
        dst.write(data, 1)
    print(
        f"mosaic: {MOSAIC}  {MOSAIC.stat().st_size / 1e6:.0f} MB  "
        f"({padded_w}x{padded_h}, nodata cells zeroed: {nodata_cells})"
    )
    return MOSAIC


def patch_index(index_path: Path, mosaic: Path) -> None:
    """Repair the georeference convert_geotiff gets wrong.

    convert_geotiff 0.1.0 mis-reads the ModelPixelScale tag (its TIFFGetField
    call fails and it writes stack residue: observed dx = 2.743193e-04 against
    the true 1/3600 = 2.777778e-04, a ~1.2 km terrain displacement) and rounds
    the origin by a few metres. All four georeference fields are rewritten from
    the mosaic's actual transform, after checking the tool's origin is within
    ~10 m of it.
    """
    with rasterio.open(mosaic) as ds:
        left, top = ds.transform.c, ds.transform.f
        res_x, res_y = ds.transform.a, -ds.transform.e
    text = index_path.read_text()
    lat = float(re.search(r"known_lat = ([-\d.eE]+)", text).group(1))
    lon = float(re.search(r"known_lon = ([-\d.eE]+)", text).group(1))
    if abs(lat - top) > 1e-4 or abs(lon - left) > 1e-4:
        raise SystemExit(
            f"index origin ({lat}, {lon}) disagrees with the mosaic transform ({top}, {left})"
        )
    text = re.sub(r"^known_lat = .*$", f"known_lat = {top:.10f}", text, flags=re.M)
    text = re.sub(r"^known_lon = .*$", f"known_lon = {left:.10f}", text, flags=re.M)
    text = re.sub(r"^dx = .*$", f"dx = {res_x:.9e}", text, flags=re.M)
    text = re.sub(r"^dy = .*$", f"dy = {res_y:.9e}", text, flags=re.M)
    index_path.write_text(text)
    print(f"index georeference corrected: dx={res_x:.9e} dy={res_y:.9e} origin=({lat:.6f},{lon:.6f})")


def main() -> int:
    mosaic = build_mosaic()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "convert_geotiff",
            "-w", "2",           # 2-byte integers
            "-s", "1.0",         # 1 m scale factor
            "-m", "0.",          # missing → 0 (GEOGRID.TBL fill_missing=0.)
            "-u", "meters",
            "-d", "USGS 3DEP 1 arc-second elevation above sea level",
            "-b", "3",           # tile halo
            "-t", "100",         # output tile size
            str(mosaic),
        ],
        cwd=OUT_DIR,
        check=True,
    )
    index = OUT_DIR / "index"
    if not index.exists():
        raise SystemExit("convert_geotiff did not write an index file")
    patch_index(index, mosaic)
    # WPS resolves rel_path entries under geog_data_path (= /wrf/geog/WPS_GEOG),
    # while the converted tiles live at /wrf/geog/usgs_1s per the plan — a
    # symlink gives WPS the layout it needs without duplicating the tiles.
    link = ROOT / "geog" / "WPS_GEOG" / "usgs_1s"
    if not link.exists():
        link.symlink_to(OUT_DIR)
    n_tiles = len([p for p in OUT_DIR.iterdir() if p.name[0].isdigit()])
    print(f"usgs_1s: index + {n_tiles} tiles written to {OUT_DIR}")
    print("---- index ----")
    print(index.read_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
