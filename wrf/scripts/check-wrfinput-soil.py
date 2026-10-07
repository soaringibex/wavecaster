#!/usr/bin/env python3
"""Phase 3 gate: prove real.exe produced sane soil fields from the RUC-style
9-level SOILT/SOILM met_em input — the classic way a soil-field merge looks
complete and isn't.

Usage: check-wrfinput-soil.py <cycle-dir>

For every wrfinput_d0* in the directory:
  * num_soil_layers must be 4 (the 9 RUC levels converted to Noah layers);
  * SMOIS must be volumetric (m3 m-3) — roughly 0.02–0.6; values in the
    tens-to-hundreds mean the RUC rows carried kg m-3 and nothing converted;
  * TSLB must be plausible for early October (~275–295 K expected).
Prints per-layer means and overall ranges; exits non-zero on failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import xarray as xr

SMOIS_BAND = (0.02, 0.60)      # volumetric m3/m3, expected
SMOIS_FAIL_MAX = 1.0           # above this is definitely not volumetric
TSLB_BAND = (275.0, 295.0)     # expected early-October band
TSLB_FAIL = (240.0, 320.0)


def check(path: Path) -> bool:
    print(f"== {path.name} ==")
    with xr.open_dataset(path) as ds:
        if "SMOIS" not in ds or "TSLB" not in ds:
            print("  FAIL: SMOIS/TSLB missing")
            return False
        smois = ds["SMOIS"].values
        tslb = ds["TSLB"].values
        n_layers = int(smois.shape[1])

    ok = True
    if n_layers != 4:
        print(f"  FAIL: {n_layers} soil layers (expect 4 — RUC 9-level input)")
        ok = False
    else:
        print("  soil layers: 4 (RUC 9-level input converted to Noah)")

    means = ", ".join(f"{float(np.mean(smois[:, k, :, :])):.4f}" for k in range(n_layers))
    print(f"  SMOIS layer means: {means}")
    print(
        f"  SMOIS min {float(smois.min()):.4f}  max {float(smois.max()):.4f}  "
        f"mean {float(smois.mean()):.4f}  (volumetric ~{SMOIS_BAND[0]}–{SMOIS_BAND[1]} m3/m3)"
    )
    print(
        f"  TSLB  min {float(tslb.min()):.2f}  max {float(tslb.max()):.2f}  "
        f"mean {float(tslb.mean()):.2f}  (expect ~{TSLB_BAND[0]}–{TSLB_BAND[1]} K)"
    )

    if float(smois.max()) > SMOIS_FAIL_MAX or float(smois.min()) < 0.0:
        print("  FAIL: SMOIS is not volumetric (kg/m3 leak from the RUC rows?)")
        ok = False
    outside = int(((smois < SMOIS_BAND[0]) | (smois > SMOIS_BAND[1])).sum())
    if outside:
        print(f"  WARN: {outside} SMOIS cells outside the expected band (water/snow columns are normal)")
    if not (TSLB_FAIL[0] <= float(tslb.min()) and float(tslb.max()) <= TSLB_FAIL[1]):
        print("  FAIL: TSLB outside plausible range")
        ok = False
    return ok


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    directory = Path(sys.argv[1])
    files = sorted(directory.glob("wrfinput_d0*"))
    if not files:
        raise SystemExit(f"no wrfinput_d0* in {directory}")
    results = [check(f) for f in files]
    if all(results):
        print("PASS: soil fields are volumetric and sane")
        return 0
    print("FAIL: soil assertion failed", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
