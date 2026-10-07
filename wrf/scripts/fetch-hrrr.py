#!/usr/bin/env python3
"""Fetch HRRR GRIB2 files for one cycle (runs inside the image).

Usage:
    fetch-hrrr.py <YYYYMMDD> <HH> --dest DIR [--hours 36] [--product prs|nat|sfc]

Downloads `hrrr.tHHz.wrfprs|wrfprs...` — herbie's product names `prs` (pressure
files), `nat` (native hybrid levels; the only product reaching HRRR's ~17 hPa
model top) and `sfc` — from the anonymous s3://noaa-hrrr-bdp-pds bucket via
Herbie, with resume (existing files are skipped) and a retry window for hours
that have not posted yet — the camp schedule fires shortly after the last hour
lands. Exits non-zero if any hour is still missing after the window, so a
partial cycle can never start a run.

The pipeline runs `--product nat` (atmosphere) plus the soil subset from the
pressure files (`fetch-soil.py`) — see wrf/README.md.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

RETRY_DELAY_S = 60
TRIES = 8


def fetch_one(cycle: str, hour: int, fxx: int, dest: Path, product: str) -> Path:
    from herbie import Herbie

    last_error = "unknown"
    for attempt in range(1, TRIES + 1):
        try:
            h = Herbie(
                f"{cycle} {hour:02d}:00",
                model="hrrr",
                product=product,  # herbie names: prs / nat / sfc
                fxx=fxx,
                save_dir=str(dest),
            )
            result = h.download(overwrite=False, verbose=False)
            path = Path(str(result))
            if path.exists() and path.stat().st_size > 0:
                return path
            last_error = f"empty file {path}"
        except Exception as exc:  # noqa: BLE001 — any herbie/network error means retry
            if isinstance(exc, (AssertionError, KeyError, TypeError, ValueError)):
                # deterministic configuration error — retrying cannot help
                raise RuntimeError(f"f{fxx:02d}: configuration error — {exc}") from exc
            text = str(exc).strip()
            last_error = text.splitlines()[-1] if text else repr(exc)
        if attempt < TRIES:
            print(
                f"f{fxx:02d}: attempt {attempt} failed ({last_error}); retrying in {RETRY_DELAY_S}s",
                flush=True,
            )
            time.sleep(RETRY_DELAY_S)
    raise RuntimeError(f"f{fxx:02d}: {last_error}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("date", help="cycle date, YYYYMMDD")
    parser.add_argument("hour", type=int, help="cycle hour, UTC")
    parser.add_argument("--hours", type=int, default=36)
    parser.add_argument("--product", default="prs", choices=["prs", "nat", "sfc"])
    parser.add_argument("--dest", required=True, help="directory for the GRIB files")
    args = parser.parse_args()

    dest = Path(args.dest).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    cycle = f"{args.date} {args.hour:02d}:00"

    failures = []
    for fxx in range(args.hours + 1):
        try:
            path = fetch_one(cycle, args.hour, fxx, dest, args.product)
        except RuntimeError as exc:
            print(f"f{fxx:02d}: FAILED — {exc}", flush=True)
            failures.append(fxx)
            continue
        print(f"f{fxx:02d}: {path.name}  {path.stat().st_size / 1e6:.0f} MB", flush=True)

    if failures:
        print(f"missing hours: {failures}", file=sys.stderr)
        return 1
    print(f"all {args.hours + 1} hours fetched to {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
