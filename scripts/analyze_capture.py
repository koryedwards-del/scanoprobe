#!/usr/bin/env python3
"""Inspect a saved probe capture and try to extract mm."""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bodymetrix.scanoprobe import echo_to_thickness_mm


def hexdump(data: bytes, width: int = 16) -> str:
    lines = []
    for i in range(0, len(data), width):
        chunk = data[i : i + width]
        hexpart = " ".join(f"{b:02x}" for b in chunk)
        asciipart = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        lines.append(f"{i:06x}  {hexpart:<{width * 3}}  {asciipart}")
    return "\n".join(lines)


def try_floats(data: bytes) -> list[tuple[str, float]]:
    hits: list[tuple[str, float]] = []
    for offset in range(0, min(len(data) - 3, 256)):
        for fmt, label in (("<f", "f32le"), (">f", "f32be"), ("<H", "u16le"), (">H", "u16be")):
            size = struct.calcsize(fmt)
            if offset + size > len(data):
                continue
            try:
                val = struct.unpack(fmt, data[offset : offset + size])[0]
            except struct.error:
                continue
            if isinstance(val, float) and 0.5 <= val <= 80.0:
                hits.append((f"@{offset} {label}", round(val, 2)))
            elif isinstance(val, int) and 1 <= val <= 800:  # tenths of mm?
                hits.append((f"@{offset} {label}", round(val / 10.0, 2)))
    return hits[:20]


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze BodyMetrix USB capture")
    parser.add_argument("path", type=Path, help="captures/*.bin file")
    args = parser.parse_args()

    if not args.path.exists():
        print(f"Not found: {args.path}", file=sys.stderr)
        return 1

    data = args.path.read_bytes()
    print(f"File: {args.path}")
    print(f"Size: {len(data)} bytes")
    print()
    print(hexdump(data[:256]))
    if len(data) > 256:
        print(f"... ({len(data) - 256} more bytes)")

    floats = try_floats(data)
    if floats:
        print("\nPossible mm values (heuristic):")
        for loc, val in floats:
            print(f"  {loc}: {val} mm")

    try:
        parsed = echo_to_thickness_mm(data)
        print(f"\nScanoprobe parser: {parsed.thickness_mm} mm")
        print(f"  method: {parsed.method}")
        print(f"  confidence: {parsed.confidence}")
    except ValueError as exc:
        print(f"\nParser: {exc}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
