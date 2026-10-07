#!/usr/bin/env python3
"""Fetch only the soil messages (SOILW/TSOIL, all depths) from a cycle's HRRR
pressure files, via .idx byte ranges.

Why: HRRR's native files (the only product that reaches the model's ~15 hPa
top) carry almost no soil state, while the pressure files carry all nine
levels. Pulling just those ~18 messages per hour costs ~40 MB per cycle
instead of the full ~15 GB pressure-file set.

Usage: fetch-soil.py <YYYYMMDD> <HH> --dest DIR [--hours 36]
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.request
from pathlib import Path

BASE = "https://noaa-hrrr-bdp-pds.s3.amazonaws.com"
TARGETS = ("SOILW", "TSOIL")
RETRY_DELAY_S = 60
TRIES = 8


def head_size(url: str) -> int:
    request = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(request, timeout=30) as response:
        return int(response.headers["Content-Length"])


def ranges_from_idx(idx_text: str, total_size: int) -> list[tuple[int, int, str]]:
    records: list[tuple[int, str]] = []
    for line in idx_text.splitlines():
        parts = line.split(":")
        if len(parts) < 6:
            continue
        records.append((int(parts[1]), parts[3]))
    records.sort()
    out = []
    for i, (offset, name) in enumerate(records):
        end = records[i + 1][0] if i + 1 < len(records) else total_size
        if name in TARGETS:
            out.append((offset, end, name))
    return out


def fetch_range(url: str, start: int, end: int) -> bytes:
    request = urllib.request.Request(url, headers={"Range": f"bytes={start}-{end - 1}"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def fetch_one(date: str, hour: int, fxx: int, dest: Path) -> Path:
    base_name = f"hrrr.t{hour:02d}z.wrfprsf{fxx:02d}.grib2"
    url = f"{BASE}/hrrr.{date}/conus/{base_name}"
    out = dest / f"hrrr.t{hour:02d}z.soilf{fxx:02d}.grib2"
    last_error = "unknown"
    for attempt in range(1, TRIES + 1):
        try:
            total = head_size(url)
            with urllib.request.urlopen(url + ".idx", timeout=30) as response:
                idx = response.read().decode()
            ranges = ranges_from_idx(idx, total)
            if len(ranges) < 18:
                raise RuntimeError(f"only {len(ranges)} soil records in idx")
            blob = b"".join(fetch_range(url, start, end) for start, end, _ in ranges)
            out.write_bytes(blob)
            return out
        except Exception as exc:  # noqa: BLE001 — retry until the file is posted
            last_error = str(exc).strip().splitlines()[-1] if str(exc).strip() else repr(exc)
            if attempt < TRIES:
                time.sleep(RETRY_DELAY_S)
    raise RuntimeError(f"f{fxx:02d}: {last_error}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("date")
    parser.add_argument("hour", type=int)
    parser.add_argument("--hours", type=int, default=36)
    parser.add_argument("--dest", required=True)
    args = parser.parse_args()

    dest = Path(args.dest).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    failures = []
    for fxx in range(args.hours + 1):
        try:
            path = fetch_one(args.date, args.hour, fxx, dest)
        except RuntimeError as exc:
            print(f"f{fxx:02d}: FAILED — {exc}", flush=True)
            failures.append(fxx)
            continue
        print(f"f{fxx:02d}: {path.name}  {path.stat().st_size / 1e6:.1f} MB", flush=True)
    if failures:
        print(f"missing hours: {failures}", file=sys.stderr)
        return 1
    print(f"all {args.hours + 1} soil subsets fetched to {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
