#!/usr/bin/env python3
"""Print the model level heights real.exe generated, and gate the Rayleigh sponge.

Usage: check-levels.py <cycle-dir> [--sponge-depth 5000] [--min-levels 5] [--head 20]

Reads the "Full level index = k   Height = … m   Thickness = … m" table that
real.exe prints (rsl.out.0000, falling back to rsl.error.0000) and:
  * prints the first `head` levels (the Phase 4 gate wants the first 20),
  * reports the total count, the top height, and how many levels lie within the
    top `sponge-depth` metres — the damp_opt=3 Rayleigh layer must be resolved,
  * exits non-zero when fewer than `min-levels` levels sit in the sponge.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

LINE = re.compile(r"Full level index =\s*(\d+)\s+Height =\s*(-?[\d.]+) m(?:\s+Thickness =\s*(-?[\d.]+) m)?")


def parse_levels(cycle_dir: Path) -> list[tuple[float, float | None]]:
    for name in ("rsl.out.0000", "rsl.error.0000"):
        path = cycle_dir / name
        if not path.exists():
            continue
        levels = []
        for line in path.read_text(errors="replace").splitlines():
            match = LINE.search(line)
            if match:
                index = int(match.group(1))
                if index == 1 and levels:
                    break  # a second domain's table starts here
                height = float(match.group(2))
                thickness = float(match.group(3)) if match.group(3) else None
                levels.append((height, thickness))
        if levels:
            return levels
    raise SystemExit(f"no 'Full level index' table in {cycle_dir}/rsl.out.0000")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("cycle_dir")
    parser.add_argument("--sponge-depth", type=float, default=5000.0)
    parser.add_argument("--min-levels", type=int, default=5)
    parser.add_argument("--head", type=int, default=20)
    args = parser.parse_args()
    cycle_dir = Path(args.cycle_dir)

    levels = parse_levels(cycle_dir)
    print(f"levels printed by real.exe: {len(levels)}")
    print(f"  first {args.head} level heights (m):")
    for i, (height, thickness) in enumerate(levels[: args.head], start=1):
        suffix = f"   (thickness {thickness:.0f} m)" if thickness is not None else ""
        print(f"    {i:3d}  {height:8.1f}{suffix}")

    top = levels[-1][0]
    sponge_bottom = top - args.sponge_depth
    in_sponge = [h for h, _ in levels if h >= sponge_bottom]
    print(
        f"  top height {top:.0f} m; Rayleigh sponge = top {args.sponge_depth:.0f} m "
        f"({sponge_bottom:.0f}..{top:.0f} m); levels inside: {len(in_sponge)}"
    )
    if len(in_sponge) < args.min_levels:
        print(f"FAIL: only {len(in_sponge)} levels in the sponge (need >= {args.min_levels})", file=sys.stderr)
        return 1
    print(f"PASS: {len(in_sponge)} levels in the Rayleigh sponge")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
