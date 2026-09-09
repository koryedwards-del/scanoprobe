"""Scanoprobe-style measurement: SEND button → raw echo → mm in our code."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Iterable

import numpy as np

from bodymetrix.amode import ThicknessResult, samples_to_thickness_mm
from bodymetrix.mm_bounds import (
    MAX_PLAUSIBLE_MM,
    MAX_PLAUSIBLE_TENTHS,
    MIN_PLAUSIBLE_MM,
    MIN_PLAUSIBLE_TENTHS,
    is_plausible_mm,
)

# BX2000 uses a 2.5 MHz A-mode transducer; digitizer rate is unknown until captured.
DEFAULT_SAMPLE_RATES_HZ = (
    5_000_000,
    10_000_000,
    20_000_000,
    25_000_000,
    33_300_000,
    40_000_000,
    50_000_000,
)

# Common USB buffer fills — not a real A-scan.
_PLACEHOLDER_BYTES = frozenset({0x00, 0x63, 0xCC, 0xFF})


def payload_quality(payload: bytes) -> float:
    """Score 0–1: higher means more likely real echo data (not padding)."""
    if len(payload) < 8:
        return 0.0

    unique = len(set(payload))
    if unique <= 2:
        return 0.05

    counts = np.bincount(np.frombuffer(payload, dtype=np.uint8), minlength=256)
    top = int(np.max(counts))
    if top / len(payload) > 0.85:
        return 0.1

    arr = np.frombuffer(payload, dtype=np.uint8).astype(np.float64)
    std = float(np.std(arr))
    if std < 2.0:
        return 0.15

    return min(1.0, std / 50.0 + unique / 128.0)


def is_placeholder_payload(payload: bytes) -> bool:
    if len(payload) < 8:
        return True
    if payload_quality(payload) < 0.2:
        return True
    sample = payload[: min(64, len(payload))]
    if all(b in _PLACEHOLDER_BYTES for b in sample) and len(set(sample)) <= 2:
        return True
    return False


@dataclass(frozen=True)
class ScanoprobeResult:
    thickness_mm: float
    method: str
    sample_rate_hz: float
    confidence: float
    skin_depth_mm: float | None = None
    fat_muscle_depth_mm: float | None = None


def _decode_sample_arrays(payload: bytes) -> list[tuple[str, np.ndarray]]:
    """Turn a USB payload into candidate A-scan sample arrays."""
    out: list[tuple[str, np.ndarray]] = []
    if len(payload) < 32:
        return out

    # Raw uint8 waveform (most common for embedded A-scans).
    raw = np.frombuffer(payload, dtype=np.uint8).astype(np.float64)
    out.append(("uint8", raw))

    # Skip a short header, then uint8 body.
    for skip in (2, 4, 8, 16, 32):
        if len(payload) > skip + 32:
            out.append((f"uint8@{skip}", raw[skip:]))

    # int16 little/big endian.
    if len(payload) >= 64 and len(payload) % 2 == 0:
        for endian, label in (("<i2", "int16le"), (">i2", "int16be")):
            try:
                arr = np.frombuffer(payload, dtype=endian).astype(np.float64)
                if len(arr) >= 32:
                    out.append((label, arr))
            except ValueError:
                continue
        for skip in (2, 4, 8, 16):
            chunk = payload[skip:]
            if len(chunk) >= 64 and len(chunk) % 2 == 0:
                for endian, label in (("<i2", f"int16le@{skip}"), (">i2", f"int16be@{skip}")):
                    try:
                        arr = np.frombuffer(chunk, dtype=endian).astype(np.float64)
                        if len(arr) >= 32:
                            out.append((label, arr))
                    except ValueError:
                        continue

    return out


def _try_embedded_mm(payload: bytes) -> ScanoprobeResult | None:
    """If the wand already computed mm, use it (BodyView-style packet)."""
    for offset in (0, 2, 4, 8, 12, 16, 20, 24):
        if offset + 4 > len(payload):
            break
        for fmt, label in (("<f", "f32le"), (">f", "f32be")):
            try:
                value = struct.unpack(fmt, payload[offset : offset + 4])[0]
            except struct.error:
                continue
            if is_plausible_mm(value):
                return ScanoprobeResult(
                    thickness_mm=round(float(value), 1),
                    method=f"embedded-{label}@{offset}",
                    sample_rate_hz=0.0,
                    confidence=1.0,
                )
        if offset + 2 <= len(payload):
            for fmt, label in (("<H", "u16le"), (">H", "u16be")):
                try:
                    value = struct.unpack(fmt, payload[offset : offset + 2])[0]
                except struct.error:
                    continue
                if MIN_PLAUSIBLE_TENTHS <= value <= MAX_PLAUSIBLE_TENTHS:
                    return ScanoprobeResult(
                        thickness_mm=round(value / 10.0, 1),
                        method=f"embedded-{label}@{offset}",
                        sample_rate_hz=0.0,
                        confidence=1.0,
                    )
    return None


def echo_to_thickness_mm(
    payload: bytes,
    *,
    sound_speed_m_s: float = 1540.0,
    sample_rates_hz: Iterable[float] = DEFAULT_SAMPLE_RATES_HZ,
    prefer_ascan: bool = True,
) -> ScanoprobeResult:
    """
    Scanoprobe philosophy: thickness comes from *our* peak picking on the echo,
    not from reverse-engineering BodyView packets.
    """
    if len(payload) < 2:
        raise ValueError(f"Payload too short ({len(payload)} bytes).")

    from bodymetrix.bodyview_parse import (
        bodyview_packet_to_mm,
        header_byte3_mm,
        is_bodyview_bx_packet,
    )

    # BodyView BX2000 packet — never fall through to wrong a-scan int16 guess.
    if is_bodyview_bx_packet(payload):
        try:
            return bodyview_packet_to_mm(payload)
        except ValueError:
            quick = header_byte3_mm(payload)
            if quick is not None:
                return ScanoprobeResult(
                    thickness_mm=quick,
                    method="header-byte3-int",
                    sample_rate_hz=0.0,
                    confidence=0.9,
                )
            raise ValueError(
                f"BodyView packet but no mm in {MIN_PLAUSIBLE_MM:g}–{MAX_PLAUSIBLE_MM:g} range."
            )

    if is_placeholder_payload(payload):
        raise ValueError(
            f"Payload looks like USB padding ({len(payload)} bytes), not echo data. "
            "Unplug wand, replug, hold SEND on gelled skin and try again."
        )

    try:
        return bodyview_packet_to_mm(payload)
    except ValueError:
        pass

    embedded = _try_embedded_mm(payload)
    if embedded and not prefer_ascan:
        return embedded

    best: ScanoprobeResult | None = None
    for label, samples in _decode_sample_arrays(payload):
        for rate in sample_rates_hz:
            try:
                result = samples_to_thickness_mm(
                    samples,
                    sample_rate_hz=float(rate),
                    sound_speed_m_s=sound_speed_m_s,
                )
            except ValueError:
                continue
            candidate = ScanoprobeResult(
                thickness_mm=result.thickness_mm,
                method=f"ascan/{label}@{rate/1e6:.1f}MHz",
                sample_rate_hz=float(rate),
                confidence=result.confidence,
                skin_depth_mm=result.skin_depth_mm,
                fat_muscle_depth_mm=result.fat_muscle_depth_mm,
            )
            if not is_plausible_mm(candidate.thickness_mm):
                continue
            if best is None or candidate.confidence > best.confidence:
                best = candidate

    if best is not None:
        return best

    if embedded is not None and is_plausible_mm(embedded.thickness_mm):
        return embedded

    raise ValueError(
        f"Could not read mm from {len(payload)} bytes "
        f"(valid range {MIN_PLAUSIBLE_MM:g}–{MAX_PLAUSIBLE_MM:g} mm). "
        "Press SEND on the wand while on skin — then run: "
        "python3 scripts/probe_usb.py send"
    )
