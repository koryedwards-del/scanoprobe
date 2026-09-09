#!/usr/bin/env python3
"""USB diagnostics for BodyMetrix probe — Scanoprobe-style SEND button flow.

Usage:
  python3 scripts/probe_usb.py status
  python3 scripts/probe_usb.py describe
  python3 scripts/probe_usb.py send --seconds 30    # wait for SEND on wand
  python3 scripts/probe_usb.py measure              # SEND → mm
  python3 scripts/probe_usb.py listen --seconds 30  # alias for send (saves capture)
  python3 scripts/probe_usb.py dump
  python3 scripts/probe_usb.py brute
  python3 scripts/probe_usb.py hunt    # find OUT command (hold SEND on skin)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from bodymetrix.device import BodyMetrixError, load_config, probe_from_config


def _probe() -> object:
    cfg_path = ROOT / "config.json"
    if not cfg_path.exists():
        cfg_path = ROOT / "config.example.json"
    return probe_from_config(load_config(cfg_path))


def cmd_status(probe) -> int:
    s = probe.status()
    print(f"Connected: {s.connected}")
    print(f"Mode:      {probe.measurement_mode}")
    print(f"VID:PID:   {s.vendor_id}:{s.product_id}")
    print(f"Message:   {s.message}")
    if not s.connected:
        print("\nTips:")
        print("  - Plug probe directly into Mac (not through a flaky hub)")
        print("  - Run: ./fix-usb.sh")
    return 0 if s.connected else 1


def cmd_describe(probe) -> int:
    try:
        info = probe.describe()
    except BodyMetrixError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Manufacturer: {info.get('manufacturer')}")
    print(f"Product:      {info.get('product')}")
    print(f"Serial:       {info.get('serial')}")
    print("Endpoints:")
    for ep in info.get("endpoints", []):
        print(f"  {ep['address']} {ep['direction']} type={ep['type']} max={ep['max_packet']}")
    return 0


def cmd_dump(probe) -> int:
    try:
        data = probe.dump_usb()
    except BodyMetrixError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(data, indent=2))
    return 0


def cmd_passive(probe, seconds: float) -> int:
    print("═" * 50)
    print("  PASSIVE LISTEN — gel, skin, press SEND anytime")
    print(f"  ({seconds:.0f} seconds, no command spam)")
    print("═" * 50)
    try:
        result = probe.passive_listen(duration_s=seconds)
    except BodyMetrixError as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 1
    print(f"\nReceived {len(result.payload)} bytes via {result.method}")
    print(f"Hex: {result.payload[:64].hex()}")
    try:
        reading = probe.parse_measurement_packet(result.payload)
        print(f"Thickness: {reading.mm} mm ({reading.method})")
    except BodyMetrixError as exc:
        print(f"Parse: {exc}")
    return 0


def cmd_init(probe) -> int:
    print("═" * 50)
    print("  BODYVIEW INIT — pipe setup + readinInfoString")
    print("  (from disasm 0x10002d401)")
    print("═" * 50)
    try:
        probe.connect()
        result = probe.bodyview_init()
    except BodyMetrixError as exc:
        print(f"Init failed: {exc}", file=sys.stderr)
        return 1
    print(f"Pipes configured: {result['pipes_configured']}")
    print(f"Connected flag:   {result['connected']}")
    print(f"Info string:      {result['info_bytes']} bytes")
    if result["info_hex"]:
        print(f"Hex:              {result['info_hex']}")
    if result["notes"]:
        print("Notes:")
        for n in result["notes"][:10]:
            print(f"  - {n}")
    if result["connected"]:
        print("\nPipes armed (connected=1). Info string optional on BodyView success path.")
        print("Next: .venv/bin/python scripts/probe_usb.py bx")
        return 0
    print("\nPipe setup failed — probe not armed.")
    return 1


def cmd_diagnose(probe) -> int:
    print("═" * 50)
    print("  USB DIAGNOSE — all init read paths")
    print("═" * 50)
    try:
        result = probe.bodyview_diagnose()
    except BodyMetrixError as exc:
        print(f"Diagnose failed: {exc}", file=sys.stderr)
        return 1
    print(f"Pipes configured: {result['pipes_configured']}")
    print(f"Connected:        {result['connected']}")
    if not result["hits"]:
        print("\nNo data on any path (all 0 bytes).")
        return 1
    print("\nHits:")
    for h in result["hits"]:
        print(f"  {h['path']}: {h['bytes']} bytes  {h['hex']}")
    return 0


def cmd_iokit(subcmd: str, seconds: float) -> int:
    import subprocess

    root = ROOT
    bin_path = root / "scripts" / "iokit_bx"
    if not bin_path.exists():
        print("Building native IOKit tool (first time only)…")
        build = subprocess.run(["bash", str(root / "scripts" / "build-iokit.sh")], cwd=root)
        if build.returncode != 0 or not bin_path.exists():
            print("IOKit build failed — see clang errors above.", file=sys.stderr)
            print("Try: xcode-select --install", file=sys.stderr)
            return 1

    if subcmd == "bx":
        print("═" * 50)
        print("  IOKIT BX — same USB stack as BodyViewPersonal")
        print(f"  Gel + skin + HOLD SEND {seconds:.0f}s")
        print("═" * 50)
    else:
        print("═" * 50)
        print(f"  IOKIT {subcmd.upper()} — native macOS USB (not libusb)")
        print("═" * 50)

    return subprocess.run([str(bin_path), subcmd], cwd=root).returncode


def cmd_bx(probe, seconds: float) -> int:
    print("═" * 50)
    print("  BODYVIEW BX PROTOCOL — gel, skin, HOLD SEND")
    print("  Uses bytes found in binary: 0xA0 0x01")
    print("═" * 50)
    try:
        probe.connect()
        init = probe.bodyview_init()
        print(f"Init: connected={init['connected']} info={init['info_bytes']} bytes")
        if init["info_hex"]:
            print(f"Info hex: {init['info_hex'][:64]}")
        print(f"HOLD SEND on wand for {seconds:.0f}s…")
        result = probe._bodyview_button_read(hold_s=seconds)
    except BodyMetrixError as exc:
        print(f"Failed: {exc}", file=sys.stderr)
        return 1
    print(f"\nReceived {len(result.payload)} bytes")
    if result.payload:
        print(f"Hex: {result.payload[:64].hex()}")
        try:
            reading = probe.parse_measurement_packet(result.payload)
            print(f"Thickness: {reading.mm} mm ({reading.method})")
        except BodyMetrixError as exc:
            print(f"Parse: {exc}")
    else:
        print("No bulk data.")
        return 1
    return 0


def cmd_gain(probe) -> int:
    print("═" * 50)
    print("  BODYVIEW GAIN SCAN — gel, skin, HOLD SEND")
    print("  Mimics writebxGainandRead from BodyViewPersonal binary")
    print("═" * 50)
    try:
        probe.connect()
        hits = probe.try_bodyview_gain_scan()
    except BodyMetrixError as exc:
        print(f"Gain scan failed: {exc}", file=sys.stderr)
        return 1
    if not hits:
        print("No bulk data at any gain level.")
        return 1
    for h in hits[:10]:
        print(f"  gain={h['gain']} → {h['bytes']} bytes  {h['hex']}")
    return 0


def cmd_hunt(probe) -> int:
    print("═" * 50)
    print("  WAND HUNT — gel, skin, HOLD SEND entire time")
    print("  Trying OUT commands until bulk data appears…")
    print("═" * 50)
    try:
        probe.connect()
        hits = probe.hunt_wand()
    except BodyMetrixError as exc:
        print(f"Hunt failed: {exc}", file=sys.stderr)
        return 1
    if not hits:
        print("No bulk echo found. Keep SEND held; try again on thigh with more gel.")
        return 1
    print(f"\nFound {len(hits)} hit(s):")
    for h in hits[:10]:
        print(f"  OUT {h['out_hex']} → {h['in_bytes']} bytes on {h['endpoint']}")
        print(f"    hex: {h['in_hex']}")
    return 0


def cmd_brute(probe) -> int:
    print("Trying init patterns — press SEND on wand if you have gel handy…")
    try:
        probe.connect()
        hits = probe.brute_init()
    except BodyMetrixError as exc:
        print(f"Brute failed: {exc}", file=sys.stderr)
        return 1
    if not hits:
        print("No USB responses (normal until SEND is pressed during a pattern).")
        return 0
    for h in hits:
        print(f"{h['init']}: {h['length']} bytes  hex={h['hex']}")
    return 0


def _banner(seconds: float) -> None:
    print("═" * 50)
    print("  SCANOPROBE MODE — press SEND on the wand")
    print("  Gel → skin → hold SEND 3–5 seconds")
    print(f"  ({seconds:.0f} second timeout)")
    print("═" * 50)


def cmd_send(probe, seconds: float, out_dir: Path, save: bool) -> int:
    _banner(seconds)
    try:
        probe.connect()
        result = probe.wait_for_send(duration_s=seconds)
    except BodyMetrixError as exc:
        print(f"\nNo echo: {exc}", file=sys.stderr)
        return 1

    print(f"\nReceived {len(result.payload)} bytes via {result.method} {result.endpoint}")
    print(f"Hex: {result.payload[:64].hex()}")

    try:
        reading = probe.parse_measurement_packet(result.payload)
        print(f"Thickness: {reading.mm} mm ({reading.method}, confidence {reading.confidence})")
    except BodyMetrixError as exc:
        print(f"Parse: {exc}")

    if save:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        bin_path, meta_path = probe.save_capture(result, out_dir, stamp)
        print(f"\nSaved:")
        print(f"  {bin_path}")
        print(f"  {meta_path}")

    if result.notes:
        print("Events:")
        for n in result.notes[:12]:
            print(f"  - {n}")
    return 0


def cmd_measure(probe, seconds: float) -> int:
    _banner(seconds)
    try:
        probe.connect()
        reading = probe.measure(timeout_ms=int(seconds * 1000))
    except BodyMetrixError as exc:
        print(f"\nMeasure failed: {exc}", file=sys.stderr)
        return 1
    print(f"\n{reading.mm} mm")
    print(f"Method: {reading.method}")
    print(f"Confidence: {reading.confidence}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="BodyMetrix USB — Scanoprobe-style SEND button capture"
    )
    parser.add_argument(
        "command",
        choices=["status", "describe", "init", "diagnose", "iokit", "send", "measure", "listen", "capture", "dump", "brute", "hunt", "gain", "bx", "passive", "scan"],
        help="What to do",
    )
    parser.add_argument("--seconds", type=float, default=30.0, help="SEND wait timeout")
    parser.add_argument("--timeout", type=float, default=30.0, help="Measure timeout (seconds)")
    parser.add_argument(
        "iokit_cmd",
        nargs="?",
        default="bx",
        choices=["init", "bx", "diagnose"],
        help="Subcommand for iokit (default: bx)",
    )
    args = parser.parse_args()

    probe = _probe()
    if args.command == "status":
        return cmd_status(probe)
    if args.command == "describe":
        return cmd_describe(probe)
    if args.command == "init":
        return cmd_init(probe)
    if args.command == "diagnose":
        return cmd_diagnose(probe)
    if args.command == "iokit":
        return cmd_iokit(args.iokit_cmd, args.seconds)
    if args.command == "dump":
        return cmd_dump(probe)
    if args.command == "brute":
        return cmd_brute(probe)
    if args.command == "hunt":
        return cmd_hunt(probe)
    if args.command == "gain":
        return cmd_gain(probe)
    if args.command == "bx":
        return cmd_bx(probe, args.seconds)
    if args.command == "passive":
        return cmd_passive(probe, args.seconds)
    if args.command == "scan":
        try:
            probe.connect()
            hits = probe.scan()
        except BodyMetrixError as exc:
            print(f"Scan failed: {exc}", file=sys.stderr)
            return 1
        if not hits:
            print("No immediate data — press SEND during send/measure.")
            return 0
        for h in hits:
            print(f"{h['method']} {h['endpoint']}: {h['length']} bytes  hex={h['hex']}")
        return 0
    if args.command == "measure":
        return cmd_measure(probe, args.timeout)
    if args.command in ("send", "listen", "capture"):
        seconds = args.seconds if args.command != "capture" else args.timeout
        return cmd_send(probe, seconds, args.out_dir, save=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
