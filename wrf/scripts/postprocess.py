#!/usr/bin/env python3
"""Phase 5: turn wrfout_d02 into the site's JSON shapes.

Emits, into the run directory (or --output-dir):
  map-field.json             247 locations × map levels × times (Open-Meteo layout)
  cross-section-<az>.json    one per 5° bucket: 15 transect points × 12 levels
  wrf-wind.json              the WRF's own wind at the Glider Area, per frame, at
                             800/825/775/850/750/700 hPa — the axis the site's
                             cross-section and its caption must use in WRF mode
                             (live soundings cannot speak for an archive)
  run.json                   cycle/init/length/wall-time/terrain/status
  checks/w3km_<cycle>_v<valid-datetime>.png  hourly W at 3 km ASL for human
                                             verification

The grid contract (map grid, levels, transect definition) comes from
--contract JSON, generated from mtwashingtonsoaring/src/lib/wx-grid.ts by
wrf/scripts/export-grid.mts — never hardcoded here, so it cannot drift.

Usage:
  postprocess.py <cycle-dir> --contract contract.json \\
      [--output-dir DIR] [--cycle 20261006T12Z] [--wall-seconds N] [--forecast-hours N]
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import netCDF4
import xarray as xr

G = 9.81
GORHAM_SUMMIT = (44.2705, -71.3032)  # for the run.json terrain stamp
LOCAL_TZ = ZoneInfo("America/New_York")


def decode_times(ds: xr.Dataset) -> list[datetime]:
    """wrfout Times is a 19-char array ("2026-10-06_12:00:00"), not datetime64.

    (`Time`, singular, is the raw hours-since-init counter — not what we want.)
    """
    raw = ds["Times"].values
    out = []
    for row in raw:
        text = "".join(c.decode() if isinstance(c, bytes) else str(c) for c in np.atleast_1d(row))
        out.append(datetime.strptime(text, "%Y-%m-%d_%H:%M:%S").replace(tzinfo=timezone.utc))
    return out


# ------------------------------------------------------------------ geometry

def along_transect(lat: float, lon: float, azimuth_deg: float, d_km: float) -> tuple[float, float]:
    """The wx-datasets.ts alongTransect — identical formula, one definition away."""
    az = math.radians(azimuth_deg)
    return (
        lat + (math.cos(az) * d_km) / 111.0,
        lon + (math.sin(az) * d_km) / (111.0 * math.cos(math.radians(lat))),
    )


def bilinear(field: np.ndarray, x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """field: (ny, nx); x/y: fractional indices (west-east, south-north)."""
    ny, nx = field.shape
    x = np.clip(x, 0, nx - 1.001)
    y = np.clip(y, 0, ny - 1.001)
    x0 = np.floor(x).astype(int)
    y0 = np.floor(y).astype(int)
    fx = x - x0
    fy = y - y0
    v = (
        field[y0, x0] * (1 - fx) * (1 - fy)
        + field[y0, x0 + 1] * fx * (1 - fy)
        + field[y0 + 1, x0] * (1 - fx) * fy
        + field[y0 + 1, x0 + 1] * fx * fy
    )
    return v


def interp_level(field: np.ndarray, p: np.ndarray, target_pa: float) -> np.ndarray:
    """Linear-in-pressure interpolation of (nz, ny, nx) to a target pressure.

    Returns (ny, nx) with NaN where the target is below the surface.
    """
    nz, ny, nx = p.shape
    above = p <= target_pa
    k1 = np.argmax(above, axis=0)
    valid = np.any(above, axis=0) & (k1 > 0)
    k0 = np.clip(k1 - 1, 0, nz - 1)
    k1c = np.clip(k1, 0, nz - 1)
    yy, xx = np.meshgrid(np.arange(ny), np.arange(nx), indexing="ij")
    p0 = p[k0, yy, xx]
    p1 = p[k1c, yy, xx]
    f0 = field[k0, yy, xx]
    f1 = field[k1c, yy, xx]
    with np.errstate(divide="ignore", invalid="ignore"):
        wgt = np.where(p1 != p0, (target_pa - p0) / (p1 - p0), 0.0)
    return np.where(valid, f0 + wgt * (f1 - f0), np.nan)


def interp_height(field: np.ndarray, z: np.ndarray, target_m: float) -> np.ndarray:
    """Linear-in-height interpolation of (nz, ny, nx) to a target height (m)."""
    nz, ny, nx = z.shape
    above = z >= target_m
    k1 = np.argmax(above, axis=0)
    valid = np.any(above, axis=0) & (k1 > 0)
    k0 = np.clip(k1 - 1, 0, nz - 1)
    k1c = np.clip(k1, 0, nz - 1)
    yy, xx = np.meshgrid(np.arange(ny), np.arange(nx), indexing="ij")
    z0 = z[k0, yy, xx]
    z1 = z[k1c, yy, xx]
    f0 = field[k0, yy, xx]
    f1 = field[k1c, yy, xx]
    with np.errstate(divide="ignore", invalid="ignore"):
        wgt = np.where(z1 != z0, (target_m - z0) / (z1 - z0), 0.0)
    return np.where(valid, f0 + wgt * (f1 - f0), np.nan)


# ------------------------------------------------------------------- wrf data

class WrfDomain:
    def __init__(self, cycle_dir: Path):
        files = sorted(cycle_dir.glob("wrfout_d02_*"))
        if not files:
            raise SystemExit(f"no wrfout_d02_* in {cycle_dir}")
        self.files = files
        self.times_utc: list[datetime] = []
        self.w = []
        self.z = []
        self.p = []
        self.hgt = None
        self.xlat = None
        self.xlon = None
        for path in files:
            with xr.open_dataset(path) as ds:
                self.times_utc.extend(decode_times(ds))
                w_stag = ds["W"].values  # (time, nz+1, ny, nx)
                self.w.append(0.5 * (w_stag[:, :-1] + w_stag[:, 1:]))
                z_stag = (ds["PH"].values + ds["PHB"].values) / G
                self.z.append(0.5 * (z_stag[:, :-1] + z_stag[:, 1:]))
                self.p.append(ds["P"].values + ds["PB"].values)
                if self.hgt is None:
                    self.hgt = ds["HGT"].values[0] if ds["HGT"].ndim == 3 else ds["HGT"].values
                    self.xlat = ds["XLAT"].values[0] if ds["XLAT"].ndim == 3 else ds["XLAT"].values
                    self.xlon = ds["XLONG"].values[0] if ds["XLONG"].ndim == 3 else ds["XLONG"].values
        self.w = np.concatenate(self.w, axis=0)
        self.z = np.concatenate(self.z, axis=0)
        self.p = np.concatenate(self.p, axis=0)
        # ll_to_xy needs a netCDF4 handle (wrf-python rejects the xarray one)
        self._nc = netCDF4.Dataset(files[0])

    def points_xy(self, lats: np.ndarray, lons: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        import wrf

        xy = np.asarray(wrf.ll_to_xy(self._nc, latitude=lats, longitude=lons, as_int=False))
        x = np.atleast_1d(np.asarray(xy[0], dtype=float))
        y = np.atleast_1d(np.asarray(xy[1], dtype=float))
        if np.any(x < 0) or np.any(y < 0):
            raise SystemExit("a sample point falls outside the d02 domain")
        return x, y


# ------------------------------------------------------------------- shapes

def jsonable(values) -> list:
    """NaN/inf → None so the files are valid JSON."""
    return [None if (isinstance(v, float) and not np.isfinite(v)) else v for v in values]


def local_series(times_utc: list[datetime]) -> tuple[list[str], int]:
    local = [t.astimezone(LOCAL_TZ) for t in times_utc]
    offset = int(local[0].utcoffset().total_seconds())
    return [t.strftime("%Y-%m-%dT%H:%M") for t in local], offset


def build_map_field(domain: WrfDomain, contract: dict) -> list[dict]:
    levels = contract["map_levels_hpa"]
    points = np.array(contract["map_points"], dtype=float)
    x, y = domain.points_xy(points[:, 0], points[:, 1])
    times_local, offset = local_series(domain.times_utc)
    ntimes = len(times_local)

    series: dict[str, list[list]] = {f"vertical_velocity_{h}hPa": [] for h in levels}
    for h in levels:
        per_time = np.full((ntimes, len(points)), np.nan)
        for ti in range(ntimes):
            field = interp_level(domain.w[ti], domain.p[ti], h * 100.0)
            per_time[ti] = bilinear(field, x, y)
        series[f"vertical_velocity_{h}hPa"] = per_time

    locations = []
    for pi in range(len(points)):
        hourly: dict[str, list] = {"time": times_local}
        for h in levels:
            hourly[f"vertical_velocity_{h}hPa"] = jsonable(series[f"vertical_velocity_{h}hPa"][:, pi])
        locations.append({"utc_offset_seconds": offset, "hourly": hourly})
    return locations


def build_cross_sections(domain: WrfDomain, contract: dict, output_dir: Path) -> list[Path]:
    levels = contract["cross_levels_hpa"]
    distances = contract["model_distances_km"]
    glat, glon = contract["glider_area"]
    times_local, offset = local_series(domain.times_utc)
    ntimes = len(times_local)
    written = []

    for azimuth in contract["azimuth_buckets"]:
        pts = np.array(
            [along_transect(glat, glon, (azimuth + 180) % 360, d) for d in distances], dtype=float
        )
        x, y = domain.points_xy(pts[:, 0], pts[:, 1])

        w_series = {h: np.full((ntimes, len(pts)), np.nan) for h in levels}
        z_series = {h: np.full((ntimes, len(pts)), np.nan) for h in levels}
        for ti in range(ntimes):
            for h in levels:
                w_series[h][ti] = bilinear(interp_level(domain.w[ti], domain.p[ti], h * 100.0), x, y)
                z_series[h][ti] = bilinear(interp_level(domain.z[ti], domain.p[ti], h * 100.0), x, y)

        elevation = bilinear(domain.hgt, x, y)
        locations = []
        for pi in range(len(pts)):
            hourly: dict[str, list] = {"time": times_local}
            for h in levels:
                hourly[f"vertical_velocity_{h}hPa"] = jsonable(w_series[h][:, pi])
                hourly[f"geopotential_height_{h}hPa"] = jsonable(z_series[h][:, pi])
            locations.append(
                {"utc_offset_seconds": offset, "elevation": float(elevation[pi]), "hourly": hourly}
            )
        out = output_dir / f"cross-section-{azimuth}.json"
        out.write_text(json.dumps(locations, separators=(",", ":")))
        written.append(out)
    return written


WIND_LEVELS_HPA = [800, 825, 775, 850, 750, 700]  # the site's waveAzimuth scan order


def build_wind_series(domain: WrfDomain, contract: dict) -> dict:
    """The WRF's own wind at the Glider Area, per frame.

    The site orients the cross-section — and captions it — from this: the wind
    that actually modelled the wave. (A live sounding can never speak for an
    archive: it has no such hour, and clamping to "nearest available" produced
    a line drawn along today's wind across yesterday's field.)
    """
    glat, glon = contract["glider_area"]
    x, y = domain.points_xy(np.array([glat]), np.array([glon]))
    times_local, offset = local_series(domain.times_utc)
    directions: dict[int, list] = {h: [] for h in WIND_LEVELS_HPA}
    speeds: dict[int, list] = {h: [] for h in WIND_LEVELS_HPA}
    frame = 0
    for path in domain.files:
        with xr.open_dataset(path) as ds:
            for ti in range(ds.sizes["Time"]):
                stagger_u = ds["U"].values[ti]
                stagger_v = ds["V"].values[ti]
                u = 0.5 * (stagger_u[:, :, :-1] + stagger_u[:, :, 1:])
                v = 0.5 * (stagger_v[:, :-1, :] + stagger_v[:, 1:, :])
                p = domain.p[frame]
                for h in WIND_LEVELS_HPA:
                    uu = float(bilinear(interp_level(u, p, h * 100.0), x, y)[0])
                    vv = float(bilinear(interp_level(v, p, h * 100.0), x, y)[0])
                    if np.isfinite(uu) and np.isfinite(vv):
                        directions[h].append(round((math.degrees(math.atan2(-uu, -vv)) + 360.0) % 360.0, 1))
                        speeds[h].append(round(math.hypot(uu, vv), 2))
                    else:
                        directions[h].append(None)
                        speeds[h].append(None)
                frame += 1
    levels = [
        {"hPa": h, "wind_direction": directions[h], "wind_speed_ms": speeds[h]}
        for h in WIND_LEVELS_HPA
    ]
    return {"schema": 1, "utc_offset_seconds": offset, "times": times_local, "levels": levels}


def write_run_json(domain: WrfDomain, output_dir: Path, cycle: str, wall_seconds: int | None) -> Path:
    sx, sy = domain.points_xy(np.array([GORHAM_SUMMIT[0]]), np.array([GORHAM_SUMMIT[1]]))
    summit_hgt = float(np.atleast_1d(bilinear(domain.hgt, sx, sy))[0])
    payload = {
        "schema": 1,
        "cycle": cycle,
        "init_time": domain.times_utc[0].isoformat().replace("+00:00", "Z"),
        "forecast_hours": round((domain.times_utc[-1] - domain.times_utc[0]).total_seconds() / 3600.0, 2),
        "wall_seconds": wall_seconds,
        "summit_hgt_m": round(summit_hgt, 1),
        "domain_max_hgt_m": round(float(domain.hgt.max()), 1),
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "ok",
    }
    out = output_dir / "run.json"
    out.write_text(json.dumps(payload, indent=2) + "\n")
    return out


def write_check_pngs(domain: WrfDomain, output_dir: Path, cycle: str) -> list[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    checks = output_dir / "checks"
    checks.mkdir(parents=True, exist_ok=True)
    written = []
    for ti, t in enumerate(domain.times_utc):
        if t.minute != 0:
            continue
        w3 = interp_height(domain.w[ti], domain.z[ti], 3000.0)
        fig, ax = plt.subplots(figsize=(8, 7), dpi=120)
        mesh = ax.pcolormesh(domain.xlon, domain.xlat, w3, cmap="RdBu_r", vmin=-8, vmax=8, shading="auto")
        ax.set_title(f"W at 3000 m ASL — {cycle} valid {t.strftime('%Y-%m-%d %HZ')}")
        ax.set_xlabel("longitude")
        ax.set_ylabel("latitude")
        fig.colorbar(mesh, ax=ax, label="m/s")
        # Name by the VALID datetime, not hour-of-day: a 36-h run contains two
        # 20Z frames and the hour-only name silently overwrote the first with
        # the second (37 frames -> 24 names).
        out = checks / f"w3km_{cycle}_v{t.strftime('%Y-%m-%dT%HZ')}.png"
        fig.savefig(out, bbox_inches="tight")
        plt.close(fig)
        written.append(out)
    return written


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("cycle_dir")
    parser.add_argument("--contract", required=True)
    parser.add_argument("--output-dir")
    parser.add_argument("--cycle", default="unknown")
    parser.add_argument("--wall-seconds", type=int)
    args = parser.parse_args()

    cycle_dir = Path(args.cycle_dir)
    output_dir = Path(args.output_dir) if args.output_dir else cycle_dir
    contract = json.loads(Path(args.contract).read_text())

    domain = WrfDomain(cycle_dir)
    print(f"wrfout frames: {len(domain.times_utc)} times, {len(domain.files)} file(s)")
    print(f"  {domain.times_utc[0]} .. {domain.times_utc[-1]}")

    map_field = build_map_field(domain, contract)
    (output_dir / "map-field.json").write_text(json.dumps(map_field, separators=(",", ":")))
    print(f"map-field.json: {len(map_field)} locations × {len(contract['map_levels_hpa'])} levels")

    cross = build_cross_sections(domain, contract, output_dir)
    print(f"cross-section files: {len(cross)}")

    wind = build_wind_series(domain, contract)
    (output_dir / "wrf-wind.json").write_text(json.dumps(wind, separators=(",", ":")))
    print(f"wrf-wind.json: {len(wind['levels'])} levels × {len(wind['times'])} times at the Glider Area")

    run_json = write_run_json(domain, output_dir, args.cycle, args.wall_seconds)
    print(f"run.json: {run_json.read_text().strip()}")

    pngs = write_check_pngs(domain, output_dir, args.cycle)
    print(f"check PNGs: {len(pngs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
