#!/usr/bin/env python3
"""Fetch HRRR pressure-level GRIB2 files for one cycle (runs inside the image).

Usage:
    fetch-hrrr.py <YYYYMMDD> <HH> --dest DIR [--hours 36]

Downloads hrrr.tHHz.wrfprsfFF.grib2 for FF = 00..hours from the anonymous
s3://noaa-hrrr-bdp-pds bucket via Herbie, with resume (existing files are
skipped) and a retry window for hours that have not posted yet — the camp
schedule fires shortly after the last hour lands. Exits non-zero if any hour is
still missing after the window, so a partial cycle can never start a run.

Only 00/06/12/18Z cycles carry long forecasts; this pipeline runs 36 h.
The pressure-level product (wrfprs) is the robust default; native levels
(wrfnat) are a possible later switch (see wrf/PLAN.md).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

RETRY_DELAY_S = 60
TRIES = 8


def fetch_one(cycle: str, hour: int, fxx: int, dest: Path) -> Path:
    from herbie import Herbie

    last_error = "unknown"
    for attempt in range(1, TRIES + 1):
        try:
            h = Herbie(
                f"{cycle} {hour:02d}:00",
                model="hrrr",
                product="wrfprs",
                fxx=fxx,
                save_dir=str(dest),
            )
            result = h.download(overwrite=False, verbose=False)
            path = Path(str(result))
            if path.exists() and path.stat().st_size > 0:
                return path
            last_error = f"empty file {path}"
        except Exception as exc:  # noqa: BLE001 — any herbie/network error means retry
            text = str(exc).strip()
            last_error = text.splitlines()[-1] if text else repr(exc)
        if attempt < TRIES:
            print(f"f{fxx:02d}: attempt {attempt} failed ({last_error}); retrying in {RETRY_DELAY_S}s")
            time.sleep(RETRY_DELAY_S)
    raise RuntimeError(f"f{fxx:02d}: {last_error}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("date", help="cycle date, YYYYMMDD")
    parser.add_argument("hour", type=int, help="cycle hour, UTC")
    parser.add_argument("--hours", type=int, default=36)
    parser.add_argument("--dest", required=True, help="directory for the GRIB files")
    args = parser.parse_args()

    dest = Path(args.dest).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    cycle = f"{args.date} {args.hour:02d}:00"

    failures = []
    for fxx in range(args.hours + 1):
        try:
            path = fetch_one(cycle, args.hour, fxx, dest)
        except RuntimeError as exc:
            print(f"f{fxx:02d}: FAILED — {exc}")
            failures.append(fxx)
            continue
        print(f"f{fxx:02d}: {path.name}  {path.stat().st_size / 1e6:.0f} MB")

    if failures:
        print(f"missing hours: {failures}", file=sys.stderr)
        return 1
    print(f"all {args.hours + 1} hours fetched to {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
