#!/usr/bin/env python3
"""Phase 2 gate: prove the 1 km domain resolves the Presidentials.

Usage: check-geogrid.py <cycle-dir>

Reads geo_em.d01*.nc / geo_em.d02*.nc from the directory, then:
  - asserts max HGT_M on d02 >= 1750 m (default 30″ terrain gives ~1400 m),
  - prints the HGT_M value at the summit (44.2705 N, 71.3032 W),
  - prints d01's max for comparison,
  - writes /wrf/out/checks/hgt_d02.png so a person can see the Notches.

Exit code is non-zero when the non-negotiable is not met.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import xarray as xr

SUMMIT_LAT, SUMMIT_LON = 44.2705, -71.3032
CHECK_DIR = Path("/wrf/out/checks")
MIN_BEST_HGT = 1750.0


def find_one(directory: Path, pattern: str) -> Path:
    matches = sorted(directory.glob(pattern))
    if not matches:
        raise SystemExit(f"no {pattern} in {directory}")
    return matches[-1]


def terrain_stats(path: Path, lat: float, lon: float) -> dict:
    with xr.open_dataset(path) as ds:
        hgt = ds["HGT_M"].isel(Time=0).values
        lats = ds["XLAT_M"].isel(Time=0).values
        lons = ds["XLONG_M"].isel(Time=0).values
    flat = np.argwhere(hgt == hgt.max())[0]
    dist = (lats - lat) ** 2 + (lons - lon) ** 2
    j, i = np.unravel_index(np.argmin(dist), dist.shape)
    return {
        "path": path,
        "max_m": float(hgt.max()),
        "max_latlon": (float(lats[flat[0], flat[1]]), float(lons[flat[0], flat[1]])),
        "summit_m": float(hgt[j, i]),
        "summit_grid": (float(lats[j, i]), float(lons[j, i])),
        "hgt": hgt,
        "lats": lats,
        "lons": lons,
    }


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    directory = Path(sys.argv[1])

    d02 = terrain_stats(find_one(directory, "geo_em.d02*.nc"), SUMMIT_LAT, SUMMIT_LON)
    d01 = terrain_stats(find_one(directory, "geo_em.d01*.nc"), SUMMIT_LAT, SUMMIT_LON)

    print(f"d01 max HGT_M : {d01['max_m']:.1f} m at {d01['max_latlon'][0]:.4f}, {d01['max_latlon'][1]:.4f}")
    print(f"d02 max HGT_M : {d02['max_m']:.1f} m at {d02['max_latlon'][0]:.4f}, {d02['max_latlon'][1]:.4f}")
    print(f"d02 @ summit  : {d02['summit_m']:.1f} m (grid point {d02['summit_grid'][0]:.4f}, {d02['summit_grid'][1]:.4f})")

    CHECK_DIR.mkdir(parents=True, exist_ok=True)
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 7), dpi=140)
    mesh = ax.pcolormesh(d02["lons"], d02["lats"], d02["hgt"], cmap="terrain", shading="auto")
    ax.plot(SUMMIT_LON, SUMMIT_LAT, "k*", ms=12, label="Mt Washington summit")
    ax.set_title(f"HGT_M on d02 (1 km) — max {d02['max_m']:.0f} m")
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    ax.legend(loc="upper left")
    fig.colorbar(mesh, ax=ax, label="m")
    out = CHECK_DIR / "hgt_d02.png"
    fig.savefig(out, bbox_inches="tight")
    print(f"wrote {out}")

    if d02["max_m"] < MIN_BEST_HGT:
        print(f"FAIL: d02 max HGT_M {d02['max_m']:.1f} < {MIN_BEST_HGT} m", file=sys.stderr)
        return 1
    print(f"PASS: d02 max HGT_M {d02['max_m']:.1f} >= {MIN_BEST_HGT} m")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
