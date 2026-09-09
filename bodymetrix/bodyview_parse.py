"""Decode mm from BodyMetrix BX2000 USB packets (BodyView-style)."""

from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

from bodymetrix.mm_bounds import (
    MAX_PLAUSIBLE_MM,
    MAX_PLAUSIBLE_TENTHS,
    MIN_PLAUSIBLE_MM,
    MIN_PLAUSIBLE_TENTHS,
    SKIN_THICKNESS_MM,
    is_likely_skin_reading,
    is_plausible_mm,
)
from bodymetrix.bvalgo import thickness_from_packet
from bodymetrix.scanoprobe import ScanoprobeResult

# BodyView graph: ~0.1 mm per envelope bin after 4-byte header (empirical / BX2000).
MM_PER_BIN = 0.1
ENVELOPE_OFFSET = 4
ENVELOPE_WIDTH = 1024


def is_bodyview_bx_packet(payload: bytes) -> bool:
    """True for BX2000 BodyView envelope packets (header 00 00 00 XX + waveform)."""
    return len(payload) >= 8 and payload[:3] == b"\x00\x00\x00" and payload[3] != 0


def header_byte3_mm(payload: bytes) -> float | None:
    """Firmware thickness in byte 3 when header is 00 00 00 XX."""
    if not is_bodyview_bx_packet(payload):
        return None
    mm = float(payload[3])
    return mm if is_plausible_mm(mm) else None


@dataclass(frozen=True)
class MmCandidate:
    thickness_mm: float
    method: str
    confidence: float


def list_mm_candidates(payload: bytes) -> list[MmCandidate]:
    """Every plausible mm interpretation — for debugging wrong reads."""
    out: list[MmCandidate] = []
    if len(payload) < 8:
        return out

    # Pattern 0: BodyView BVAlgo (FindPeaks → fatThicknessMeasurement).
    bvm = thickness_from_packet(payload)
    if bvm and bvm.valid and is_plausible_mm(bvm.fat_thickness_mm):
        out.append(
            MmCandidate(
                bvm.fat_thickness_mm,
                f"bvalgo/{bvm.method}",
                bvm.confidence,
            )
        )
        if is_plausible_mm(bvm.muscle_thickness_mm):
            out.append(
                MmCandidate(
                    bvm.muscle_thickness_mm,
                    "bvalgo/muscleThicknessMeasurement",
                    bvm.confidence * 0.85,
                )
            )

    # Pattern A: 00 00 00 XX — firmware thickness in whole mm (e.g. 0c → 12).
    if payload[:3] == b"\x00\x00\x00" and payload[3]:
        mm = float(payload[3])
        if is_plausible_mm(mm):
            out.append(MmCandidate(mm, "header-byte3-int", 0.9))

    # Pattern B: u16 BE @2 in tenths (e.g. 0x0078 → 12.0 mm) — not u16le@2.
    if len(payload) >= 4:
        tenths_be = struct.unpack(">H", payload[2:4])[0]
        if MIN_PLAUSIBLE_TENTHS <= tenths_be <= MAX_PLAUSIBLE_TENTHS:
            out.append(MmCandidate(round(tenths_be / 10.0, 1), "header-u16be-tenths@2", 0.75))

    # Pattern C: envelope peak depth — BodyView first major peak × 0.1 mm/bin.
    env = np.frombuffer(
        payload[ENVELOPE_OFFSET : ENVELOPE_OFFSET + ENVELOPE_WIDTH], dtype=np.uint8
    ).astype(np.float64)
    if len(env) >= 32:
        baseline = float(np.median(env[:16]))
        threshold = baseline + 0.2 * (float(np.max(env)) - baseline)
        peaks: list[tuple[int, float]] = []
        for i in range(5, len(env) - 2):
            if env[i] < threshold:
                continue
            if env[i] >= env[i - 1] and env[i] >= env[i + 1]:
                peaks.append((i, float(env[i])))
        if peaks:
            # Fat–muscle boundary is past skin (~3 mm); skip skin echo at bin 30.
            skin_bin = int(round(SKIN_THICKNESS_MM / MM_PER_BIN))
            in_range = [(i, a) for i, a in peaks if i > skin_bin]
            pool = in_range if in_range else peaks
            peak_idx, _ = max(pool, key=lambda t: t[1])
            mm = round(peak_idx * MM_PER_BIN, 1)
            if is_plausible_mm(mm):
                out.append(
                    MmCandidate(mm, f"envelope-peak@{peak_idx}x{MM_PER_BIN}", 0.85)
                )
            # Early peak (skin / noise) — lower confidence.
            early = [p for p in peaks if p[0] <= skin_bin]
            if early:
                ei, _ = max(early, key=lambda t: t[1])
                emm = round(ei * MM_PER_BIN, 1)
                if is_plausible_mm(emm):
                    out.append(
                        MmCandidate(emm, f"envelope-early@{ei}x{MM_PER_BIN}", 0.35)
                    )

    # Pattern D: float32 in first 16 bytes.
    for off in (0, 4, 8):
        if off + 4 <= len(payload):
            for fmt, label in (("<f", "f32le"), (">f", "f32be")):
                try:
                    val = struct.unpack(fmt, payload[off : off + 4])[0]
                except struct.error:
                    continue
                if is_plausible_mm(val):
                    out.append(MmCandidate(round(val, 1), f"{label}@{off}", 0.5))

    # De-dupe similar values, keep highest confidence.
    out.sort(key=lambda c: (-c.confidence, -c.thickness_mm))
    seen: list[float] = []
    unique: list[MmCandidate] = []
    for c in out:
        if any(abs(c.thickness_mm - s) < 0.15 for s in seen):
            continue
        seen.append(c.thickness_mm)
        unique.append(c)
    return unique


def bodyview_packet_to_mm(payload: bytes) -> ScanoprobeResult:
    candidates = [c for c in list_mm_candidates(payload) if is_plausible_mm(c.thickness_mm)]
    if not candidates:
        raise ValueError(
            f"No plausible mm in packet (valid range {MIN_PLAUSIBLE_MM:g}–{MAX_PLAUSIBLE_MM:g} mm)."
        )

    # Prefer BVAlgo fatThicknessMeasurement (matches BodyView Edwards path).
    bvalgo = [c for c in candidates if c.method.startswith("bvalgo/")]
    header = [c for c in candidates if "header-byte3" in c.method]
    if bvalgo and header:
        # If firmware header and BVAlgo agree (~2 mm), trust header (device value).
        h = header[0].thickness_mm
        b = bvalgo[0].thickness_mm
        if abs(h - b) <= 2.0:
            chosen = header[0]
        else:
            chosen = bvalgo[0]
    elif bvalgo:
        chosen = bvalgo[0]
    else:
        fat_layer = [c for c in candidates if not is_likely_skin_reading(c.thickness_mm)]
        pool = fat_layer if fat_layer else candidates
        chosen = pool[0]
        for c in pool:
            if c.confidence > chosen.confidence:
                chosen = c
            elif c.confidence == chosen.confidence and "envelope-peak" in c.method:
                chosen = c

    if not is_plausible_mm(chosen.thickness_mm):
        raise ValueError(
            f"Decoded {chosen.thickness_mm} mm outside "
            f"{MIN_PLAUSIBLE_MM:g}–{MAX_PLAUSIBLE_MM:g} mm."
        )

    return ScanoprobeResult(
        thickness_mm=chosen.thickness_mm,
        method=chosen.method,
        sample_rate_hz=0.0,
        confidence=chosen.confidence,
    )
