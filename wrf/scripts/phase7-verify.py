#!/usr/bin/env python3
"""Phase 7 verification: the 2026-10-06 12Z run, 16:00 EDT, 3,000 m ASL.

Prints the numbers the report needs, plainly — it does not tune anything:

  * dominant wavelength of W along the 315° transect through the Glider Area
    centre (peak of the 1-D power spectrum),
  * sink over the Mt Washington crest and the primary lift's position relative
    to the summit (plus any secondary cells near Route 113),
  * peak |W| at 3 km,
  * the summit-level (1,917 m) wind,
  * the 3000 m wind (for the "bands perpendicular to a 300-315° flow" check).

Usage (inside the image, from the cycle directory):
    python /wrf/scripts/phase7-verify.py [--time 2026-10-06_20:00:00]
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import netCDF4
import numpy as np
import xarray as xr
import wrf

SUMMIT = (44.2705, -71.3032)  # Mt Washington summit
SUMMIT_ASL = 1917.0
KT = 1.94384
G = 9.81


def decode_times(ds: xr.Dataset) -> list[str]:
    out = []
    for row in ds["Times"].values:
        out.append("".join(c.decode() if isinstance(c, bytes) else str(c) for c in np.atleast_1d(row)))
    return out


def destagger_z(field: np.ndarray) -> np.ndarray:
    return 0.5 * (field[:-1] + field[1:])


def interp_z(field: np.ndarray, z: np.ndarray, target: float) -> np.ndarray:
    """Linear-in-height interpolation of (nz, ny, nx) to target m ASL."""
    above = z >= target
    k1 = np.argmax(above, axis=0)
    valid = np.any(above, axis=0) & (k1 > 0)
    k0 = np.clip(k1 - 1, 0, z.shape[0] - 1)
    k1c = np.clip(k1, 0, z.shape[0] - 1)
    yy, xx = np.meshgrid(np.arange(z.shape[1]), np.arange(z.shape[2]), indexing="ij")
    z0, z1 = z[k0, yy, xx], z[k1c, yy, xx]
    f0, f1 = field[k0, yy, xx], field[k1c, yy, xx]
    with np.errstate(divide="ignore", invalid="ignore"):
        wgt = np.where(z1 != z0, (target - z0) / (z1 - z0), 0.0)
    return np.where(valid, f0 + wgt * (f1 - f0), np.nan)


def bilinear(field: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    ny, nx = field.shape
    x = np.clip(x, 0, nx - 1.001)
    y = np.clip(y, 0, ny - 1.001)
    x0 = np.floor(x).astype(int)
    y0 = np.floor(y).astype(int)
    fx = x - x0
    fy = y - y0
    return (
        field[y0, x0] * (1 - fx) * (1 - fy)
        + field[y0, x0 + 1] * fx * (1 - fy)
        + field[y0 + 1, x0] * (1 - fx) * fy
        + field[y0 + 1, x0 + 1] * fx * fy
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--time", default="2026-10-06_20:00:00", help="UTC valid time to verify")
    parser.add_argument("--case", default=".")
    args = parser.parse_args()
    case = Path(args.case).resolve()

    contract = json.loads((case / "grid.json").read_text())
    glat, glon = contract["glider_area"]

    files = sorted(case.glob("wrfout_d02_*"))
    ds = xr.open_dataset(files[0])
    times = decode_times(ds)
    ti = times.index(args.time)
    print(f"domain: {files[0].name}; frames {len(times)}; verifying {args.time} (index {ti})")

    w = destagger_z(ds["W"].values[ti])
    z = destagger_z(ds["PH"].values[ti] + ds["PHB"].values[ti]) / G
    u = 0.5 * (ds["U"].values[ti, :, :, :-1] + ds["U"].values[ti, :, :, 1:])
    v = 0.5 * (ds["V"].values[ti, :, :-1, :] + ds["V"].values[ti, :, 1:, :])
    xlat = ds["XLAT"].values[0]
    xlon = ds["XLONG"].values[0]

    nc = netCDF4.Dataset(files[0])
    def to_xy(lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        xy = np.asarray(wrf.ll_to_xy(nc, latitude=np.atleast_1d(lat), longitude=np.atleast_1d(lon), as_int=False))
        return np.atleast_1d(xy[0].astype(float)), np.atleast_1d(xy[1].astype(float))

    w3 = interp_z(w, z, 3000.0)

    # ---- 2-D picture ------------------------------------------------------
    smax = float(np.nanmax(w3))
    smin = float(np.nanmin(w3))
    print(f"\n3 km W over the full d02: max {smax:+.2f} m/s, min {smin:+.2f} m/s")
    sx, sy = to_xy(*SUMMIT)
    sx, sy = float(sx[0]), float(sy[0])
    yy, xx = np.meshgrid(np.arange(w3.shape[0]), np.arange(w3.shape[1]), indexing="ij")
    dist_km = np.hypot((xx - sx), (yy - sy))  # ~1 km cells
    near = dist_km <= 30.0
    print(f"within 30 km of the summit: max {np.nanmax(w3[near]):+.2f} m/s, min {np.nanmin(w3[near]):+.2f} m/s")
    print(f"W at the summit at 3 km: {float(bilinear(w3, np.array([sx]), np.array([sy]))[0]):+.2f} m/s")

    # strongest lift cells within 30 km (local maxima, spaced)
    masked = np.where(near & np.isfinite(w3), w3, -np.inf)
    picks = []
    for _ in range(3):
        idx = np.unravel_index(np.argmax(masked), masked.shape)
        iy, ix = int(idx[0]), int(idx[1])
        clat, clon = float(xlat[iy, ix]), float(xlon[iy, ix])
        brg = (math.degrees(math.atan2((ix - sx), (iy - sy))) + 360) % 360
        picks.append((float(masked[iy, ix]), clat, clon, brg, float(dist_km[iy, ix])))
        masked[max(0, iy - 8):iy + 8, max(0, ix - 8):ix + 8] = -np.inf
    for j, (val, clat, clon, brg, dist) in enumerate(picks, 1):
        print(f"lift cell {j}: {val:+.2f} m/s at ({clat:.3f}, {clon:.3f}), {dist:.1f} km bearing {brg:.0f}° from the summit")

    # sink over the crest: minimum within 5 km
    crest = dist_km <= 5.0
    print(f"strongest sink within 5 km of the summit: {np.nanmin(np.where(crest, w3, np.nan)):+.2f} m/s")

    # ---- transect + spectrum ---------------------------------------------
    d_km = np.arange(-75.0, 75.0001, 0.5)
    az = math.radians(135.0)  # the 315/135 axis: along a 315° flow
    tlat = glat + (math.cos(az) * d_km) / 111.0
    tlon = glon + (math.sin(az) * d_km) / (111.0 * math.cos(math.radians(glat)))
    tx, ty = to_xy(tlat, tlon)
    inside = (tx >= 0) & (tx <= w3.shape[1] - 1.001) & (ty >= 0) & (ty <= w3.shape[0] - 1.001)
    print(f"\n315° transect through the Glider Area centre: {int(inside.sum())} of {len(d_km)} samples inside d02 ({d_km[inside][0]:+.0f} .. {d_km[inside][-1]:+.0f} km along the line; + is SE)")
    wline = bilinear(w3, tx[inside], ty[inside])
    dline = d_km[inside]
    print(f"transect W: max {np.nanmax(wline):+.2f} m/s at {dline[np.nanargmax(wline)]:+.1f} km, min {np.nanmin(wline):+.2f} m/s at {dline[np.nanargmin(wline)]:+.1f} km")

    detrended = wline - np.polyval(np.polyfit(dline, wline, 1), dline)
    window = np.hanning(len(detrended))
    power = np.abs(np.fft.rfft(detrended * window)) ** 2
    freq = np.fft.rfftfreq(len(detrended), d=0.5)
    with np.errstate(divide="ignore"):
        lam = 1.0 / freq[1:]
    power = power[1:]
    band = (lam >= 4.0) & (lam <= 60.0)
    lam_b, power_b = lam[band], power[band]
    order = np.argsort(power_b)[::-1][:3]
    print("spectrum peaks (wavelength, relative power):")
    for k in order:
        print(f"   {lam_b[k]:6.1f} km   {100 * power_b[k] / power_b.max():5.1f}% of peak")
    print(f"dominant wavelength: {lam_b[order[0]]:.1f} km")

    # ---- winds ------------------------------------------------------------
    for label, target in (("3,000 m", 3000.0), ("1,917 m (summit level)", SUMMIT_ASL)):
        uu = float(bilinear(interp_z(u, z, target), np.array([sx]), np.array([sy]))[0])
        vv = float(bilinear(interp_z(v, z, target), np.array([sx]), np.array([sy]))[0])
        spd = math.hypot(uu, vv)
        print(f"summit-column wind at {label}: {spd * KT:.1f} kt, from {(math.degrees(math.atan2(-uu, -vv)) + 360) % 360:.0f}°")
    u3, v3 = interp_z(u, z, 3000.0), interp_z(v, z, 3000.0)
    uu = float(np.nanmedian(u3[near])); vv = float(np.nanmedian(v3[near]))
    print(f"median 3 km wind within 30 km of the summit: {math.hypot(uu, vv) * KT:.1f} kt, from {(math.degrees(math.atan2(-uu, -vv)) + 360) % 360:.0f}°")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
