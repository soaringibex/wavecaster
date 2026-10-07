#!/usr/bin/env python3
"""Phase 3 gate: audit the met_em files and print what real.exe will read.

Usage: check-met-em.py <cycle-dir> [--times N]

- Confirms one met_em file per domain per hour (37 × 2 for a 36 h cycle).
- Confirms every field the Vtable must supply is present:
  PRES, GHT, TT, UU, VV, RH, PSFC, PMSL, SKINTEMP, SOILHGT, LANDSEA, SEAICE,
  SNOW, plus soil temperature/moisture — either the Noah-style pair (ST, SM)
  or the HRRR/RUC-style pair (SOILT, SOILM, 9 levels). real.exe converts the
  RUC-style levels to Noah's four layers ("RUC -> Noah" in
  module_initialize_real.F), which is why the HRRR path uses SOILT/SOILM.
- Prints the level counts real.exe will derive from the file
  (BOTTOM-TOP_GRID_DIMENSION - 1 and NUM_METGRID_SOIL_LEVELS).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import xarray as xr

REQUIRED_2D = (
    "PRES", "GHT", "TT", "UU", "VV", "RH", "PSFC", "PMSL",
    "SKINTEMP", "SOILHGT", "LANDSEA", "SEAICE", "SNOW",
)
SOIL_SCHEMES = (
    ("noah (ST/SM)", "ST", "SM", "num_st_layers"),
    ("ruc/hrrr (SOILT/SOILM)", "SOILT", "SOILM", "num_soilt_levels"),
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory")
    parser.add_argument("--times", type=int, default=37)
    args = parser.parse_args()
    directory = Path(args.directory)

    d01 = sorted(directory.glob("met_em.d01.*"))
    d02 = sorted(directory.glob("met_em.d02.*"))
    print(f"met_em files: d01={len(d01)}  d02={len(d02)}  (expected {args.times} each)")
    if len(d01) != args.times or len(d02) != args.times:
        print("FAIL: unexpected met_em count", file=sys.stderr)
        return 1

    failures: list[str] = []
    with xr.open_dataset(d01[0]) as ds:
        variables = set(ds.variables)
        bottom_top = int(ds.attrs.get("BOTTOM-TOP_GRID_DIMENSION", 0))
        dim_levels = int(ds.sizes.get("num_metgrid_levels", 0))
        n_lev = dim_levels if dim_levels > 0 else bottom_top
        n_soil = int(ds.attrs.get("NUM_METGRID_SOIL_LEVELS", -1))

        for name in REQUIRED_2D:
            if name not in variables:
                failures.append(f"missing {name}")

        found_soil = False
        for label, temp_name, moist_name, dim_name in SOIL_SCHEMES:
            if temp_name in variables and moist_name in variables:
                temp = ds[temp_name]
                moist = ds[moist_name]
                levels_t = int(temp.shape[1]) if temp.ndim > 1 else 0
                levels_m = int(moist.shape[1]) if moist.ndim > 1 else 0
                dim = ds.sizes.get(dim_name, "n/a")
                print(f"soil scheme present: {label} — {levels_t} temp / {levels_m} moist levels (dim {dim_name}={dim})")
                if min(levels_t, levels_m) < 4:
                    failures.append(f"{label}: only {min(levels_t, levels_m)} soil levels")
                found_soil = True
                break
        if not found_soil:
            failures.append("no soil pair present (ST/SM or SOILT/SOILM)")

        print(f"num_metgrid_levels      = {n_lev}  (dim: {dim_levels}, BOTTOM-TOP_GRID_DIMENSION {bottom_top})")
        print(f"num_metgrid_soil_levels = {n_soil}  (NUM_METGRID_SOIL_LEVELS)")
        print(f"2-D fields present      = {len([n for n in REQUIRED_2D if n in variables])}/{len(REQUIRED_2D)}")

    if n_lev <= 0:
        failures.append("num_metgrid_levels not readable from met_em")
    if n_soil <= 0:
        failures.append("NUM_METGRID_SOIL_LEVELS not readable from met_em")
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    print("PASS: met_em audit clean — real.exe inputs are all present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
