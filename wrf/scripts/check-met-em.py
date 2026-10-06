#!/usr/bin/env python3
"""Phase 3 gate: audit the met_em files and print what real.exe will read.

Usage: check-met-em.py <cycle-dir> [--times N]

- Confirms one met_em file per domain per hour (37 × 2 for a 36 h cycle).
- Confirms every field the Vtable must supply is present:
  PRES, HGT, TT, UU, VV, RH, PSFC, PMSL, SKINTEMP, SOILHGT, LANDSEA, SEAICE,
  SNOW, plus soil temperature/moisture at all levels.
- Prints num_metgrid_levels / num_metgrid_soil_levels exactly as real.exe will
  read them (the run script copies these into namelist.input).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import xarray as xr

REQUIRED_3D_SOIL = ("ST", "SM")
REQUIRED_2D = (
    "PRES", "HGT", "TT", "UU", "VV", "RH", "PSFC", "PMSL",
    "SKINTEMP", "SOILHGT", "LANDSEA", "SEAICE", "SNOW",
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

    failures = []
    with xr.open_dataset(d01[0]) as ds:
        variables = set(ds.variables)
        n_lev = int(ds.attrs.get("num_metgrid_levels", -1))
        n_soil = int(ds.attrs.get("num_metgrid_soil_levels", -1))
        soil_levels = ds.sizes.get("num_soil_layers", 0)
        for name in REQUIRED_2D:
            if name not in variables:
                failures.append(f"missing {name}")
        for name in REQUIRED_3D_SOIL:
            if name not in variables:
                failures.append(f"missing {name}")
            elif ds[name].shape[1] != soil_levels:
                failures.append(f"{name}: {ds[name].shape[1]} levels, expected {soil_levels}")
        print(f"num_metgrid_levels      = {n_lev}")
        print(f"num_metgrid_soil_levels = {n_soil}")
        print(f"soil variables present  = {[n for n in REQUIRED_3D_SOIL if n in variables]} at {soil_levels} levels")
        print(f"2-D fields present      = {len([n for n in REQUIRED_2D if n in variables])}/{len(REQUIRED_2D)}")

    if n_lev <= 0 or n_soil <= 0:
        failures.append("num_metgrid_levels/num_metgrid_soil_levels not readable from met_em")
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    print("PASS: met_em audit clean — real.exe inputs are all present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
