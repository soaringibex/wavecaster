#!/usr/bin/env python3
"""Mosaic the USGS 3DEP 1-arcsecond tiles and convert them to WPS geog tiles.

Runs inside the image (rasterio + convert_geotiff on PATH) and only ever reads
the local tile directory — it does not download anything. Writes:
  /wrf/geog/usgs_1s_mosaic.tif   merged 1″ elevation (overwritten each run)
  /wrf/geog/usgs_1s/             geogrid index + tiles, referenced by the
                                 HGT_M usgs_1s entry in wrf/wps/GEOGRID.TBL

A host that already carries a full convert_geotiff output set (mosaic + index +
tiles) in this script's format is reused as-is; pass --force to regenerate it
from the local tiles.

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

import argparse
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


def read_index_georef(text: str) -> tuple[float, float, float, float]:
    """(known_lat, known_lon, dx, dy) from a geogrid index, or SystemExit."""
    values = {}
    for key in ("known_lat", "known_lon", "dx", "dy"):
        match = re.search(rf"^{key} = ([-\d.eE]+)", text, flags=re.M)
        if not match:
            raise SystemExit(f"index is missing {key}")
        values[key] = float(match.group(1))
    return values["known_lat"], values["known_lon"], values["dx"], values["dy"]


def index_matches_mosaic(index_path: Path, mosaic: Path) -> bool:
    """True when an existing convert_geotiff output already matches this
    script's format: the index parses, its georeference agrees with the
    mosaic's own transform (the same assertion patch_index makes), and tiles
    are present. Lets a prepared host reuse the Mac-built terrain instead of
    re-running the tool."""
    if not (index_path.exists() and mosaic.exists() and OUT_DIR.is_dir()):
        return False
    try:
        lat, lon, dx, dy = read_index_georef(index_path.read_text())
        with rasterio.open(mosaic) as ds:
            left, top = ds.transform.c, ds.transform.f
            res_x, res_y = ds.transform.a, -ds.transform.e
    except (SystemExit, OSError, ValueError):
        return False
    if abs(lat - top) > 1e-4 or abs(lon - left) > 1e-4:
        return False
    if abs(dx - res_x) > 1e-9 or abs(dy - res_y) > 1e-9:
        return False
    return any(p.name[:1].isdigit() for p in OUT_DIR.iterdir())


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
    lat, lon, _, _ = read_index_georef(text)
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


def ensure_geog_symlink() -> None:
    # WPS resolves rel_path entries under geog_data_path (= /wrf/geog/WPS_GEOG),
    # while the converted tiles live at /wrf/geog/usgs_1s per the plan — a
    # symlink gives WPS the layout it needs without duplicating the tiles.
    link = ROOT / "geog" / "WPS_GEOG" / "usgs_1s"
    if not link.exists():
        link.symlink_to(OUT_DIR)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force",
        action="store_true",
        help="rebuild the mosaic and re-run convert_geotiff even when the "
        "existing output already matches this script's format",
    )
    args = parser.parse_args()

    index = OUT_DIR / "index"
    if not args.force and index_matches_mosaic(index, MOSAIC):
        print(f"reusing existing {index} + tiles in {OUT_DIR} (format matches; --force rebuilds)")
        ensure_geog_symlink()
        print("---- index ----")
        print(index.read_text())
        return 0

    if args.force or not MOSAIC.exists():
        mosaic = build_mosaic()
    else:
        print(f"reusing existing mosaic {MOSAIC} (regenerating only the geog tiles)")
        mosaic = MOSAIC
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
    if not index.exists():
        raise SystemExit("convert_geotiff did not write an index file")
    patch_index(index, mosaic)
    ensure_geog_symlink()
    n_tiles = len([p for p in OUT_DIR.iterdir() if p.name[0].isdigit()])
    print(f"usgs_1s: index + {n_tiles} tiles written to {OUT_DIR}")
    print("---- index ----")
    print(index.read_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
