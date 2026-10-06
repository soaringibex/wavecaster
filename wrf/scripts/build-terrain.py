#!/usr/bin/env python3
"""Mosaic the USGS 3DEP 1-arcsecond tiles and convert them to WPS geog tiles.

Runs inside the image (rasterio + convert_geotiff on PATH). Writes:
  /wrf/geog/usgs_1s_mosaic.tif   merged 1″ elevation (cached between runs)
  /wrf/geog/usgs_1s/             geogrid index + tiles, referenced by the
                                 HGT_M usgs_1s entry in wrf/wps/GEOGRID.TBL

The six staged tiles (n43/n44 × w071/w072/w073) cover 43–45 N, 70–73 W —
the demanded 43.5–45.0 N, 72.5–70.0 W window plus margin.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import rasterio
from rasterio.merge import merge

ROOT = Path("/wrf")
TILE_DIR = ROOT / "geog" / "usgs_1s_tiles"
MOSAIC = ROOT / "geog" / "usgs_1s_mosaic.tif"
OUT_DIR = ROOT / "geog" / "usgs_1s"


def build_mosaic() -> Path:
    tiles = sorted(TILE_DIR.glob("USGS_1_*.tif"))
    if len(tiles) != 6:
        raise SystemExit(f"expected 6 USGS tiles in {TILE_DIR}, found {len(tiles)}")
    datasets = [rasterio.open(t) for t in tiles]
    try:
        mosaic, transform = merge(datasets)
        profile = datasets[0].profile.copy()
    finally:
        for dataset in datasets:
            dataset.close()
    profile.update(
        height=mosaic.shape[1],
        width=mosaic.shape[2],
        transform=transform,
        count=1,
        dtype=mosaic.dtype,
        compress="deflate",
    )
    with rasterio.open(MOSAIC, "w", **profile) as dst:
        dst.write(mosaic[0], 1)
    print(f"mosaic: {MOSAIC}  {MOSAIC.stat().st_size / 1e6:.0f} MB")
    return MOSAIC


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
            "-t", "100",         # tile size
            str(mosaic),
        ],
        cwd=OUT_DIR,
        check=True,
    )
    index = OUT_DIR / "index"
    if not index.exists():
        raise SystemExit("convert_geotiff did not write an index file")
    n_tiles = len([p for p in OUT_DIR.iterdir() if p.name[0].isdigit()])
    print(f"usgs_1s: index + {n_tiles} tiles written to {OUT_DIR}")
    print("---- index ----")
    print(index.read_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
