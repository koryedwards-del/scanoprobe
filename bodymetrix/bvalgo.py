"""BodyView BVAlgo thickness decode (from BodyViewPersonal binary symbols).

Binary call chain (confirmed by mine-decode):
  readbxMultipleSignals → average signal → GetThicknessMeasurementfromAverageSignal
  → BVAlgo GetEstimatedThickness / FindPeaks / findFirstPeakinArray
  → BVthicknessMeasurement.fatThicknessMeasurement (Edwards site mm)
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from bodymetrix.mm_bounds import (
    MAX_PLAUSIBLE_MM,
    MIN_PLAUSIBLE_MM,
    SKIN_THICKNESS_MM,
    is_plausible_mm,
)

# Graph X-axis: ~0.1 mm per bin after 4-byte USB header (BX2000 / BodyView).
MM_PER_BIN = 0.1
ENVELOPE_OFFSET = 4
ENVELOPE_WIDTH = 1024

# initthicknessParms / peak globals — refine when disasm confirms exact values.
PEAK_SEARCH_START_BIN = 5
PEAK_SEARCH_END_BIN = 500


@dataclass(frozen=True)
class BVThicknessMeasurement:
    """Matches BodyView BVthicknessMeasurement."""

    fat_thickness_mm: float
    muscle_thickness_mm: float
    valid: bool
    index_at_maximum_thickness: int
    method: str
    confidence: float


def envelope_from_payload(payload: bytes) -> np.ndarray:
    end = min(len(payload), ENVELOPE_OFFSET + ENVELOPE_WIDTH)
    raw = np.frombuffer(payload[ENVELOPE_OFFSET:end], dtype=np.uint8).astype(np.float64)
    if len(raw) < 32:
        raise ValueError("Envelope too short.")
    return raw


def find_peaks(env: np.ndarray) -> list[tuple[int, float]]:
    """BVAlgo FindPeaks — local maxima above adaptive threshold."""
    baseline = float(np.median(env[: max(16, len(env) // 32)]))
    span = float(np.max(env) - baseline)
    threshold = baseline + 0.15 * span
    peaks: list[tuple[int, float]] = []
    for i in range(PEAK_SEARCH_START_BIN, len(env) - 2):
        if env[i] < threshold:
            continue
        if env[i] >= env[i - 1] and env[i] >= env[i + 1]:
            peaks.append((i, float(env[i])))
    return peaks


def find_first_peak_in_array(
    env: np.ndarray, start: int, end: int, threshold: float
) -> int | None:
    """BVAlgo findFirstPeakinArray — first peak in [start, end)."""
    end = min(end, len(env) - 1)
    for i in range(max(1, start), end):
        if env[i] < threshold:
            continue
        if env[i] >= env[i - 1] and env[i] >= env[i + 1]:
            return i
    return None


def index_at_maximum_thickness(env: np.ndarray) -> int:
    """BV2DView indexatMaximumThickness — strongest bin in search window."""
    window = env[PEAK_SEARCH_START_BIN:PEAK_SEARCH_END_BIN]
    if len(window) == 0:
        return int(np.argmax(env))
    return PEAK_SEARCH_START_BIN + int(np.argmax(window))


def get_estimated_thickness(env: np.ndarray) -> BVThicknessMeasurement:
    """
    BVAlgo GetEstimatedThickness + GetThicknessMeasurementfromAverageSignal.

    fatThicknessMeasurement = subcutaneous fat (Edwards site reading).
    muscleThicknessMeasurement = depth to fat–muscle boundary.
    """
    peaks = find_peaks(env)
    baseline = float(np.median(env[:16]))
    span = max(1.0, float(np.max(env) - baseline))
    threshold = baseline + 0.12 * span

    skin_bin = int(round(SKIN_THICKNESS_MM / MM_PER_BIN))

    # Skin interface: first peak in early window.
    skin_idx = find_first_peak_in_array(env, PEAK_SEARCH_START_BIN, skin_bin + 15, threshold)
    if skin_idx is None and peaks:
        early = [p for p in peaks if p[0] <= skin_bin + 10]
        skin_idx = max(early, key=lambda t: t[1])[0] if early else peaks[0][0]

    # Fat–muscle: first peak after skin band (findFirstPeakinArray past skin).
    muscle_idx = find_first_peak_in_array(
        env, skin_bin + 5 if skin_idx is None else skin_idx + 5, PEAK_SEARCH_END_BIN, threshold
    )
    if muscle_idx is None and peaks:
        after_skin = [p for p in peaks if p[0] > (skin_idx or skin_bin)]
        if after_skin:
            muscle_idx = max(after_skin, key=lambda t: t[1])[0]

    max_idx = index_at_maximum_thickness(env)

    if muscle_idx is not None:
        muscle_mm = round(muscle_idx * MM_PER_BIN, 1)
        if skin_idx is not None:
            skin_mm = round(skin_idx * MM_PER_BIN, 1)
            fat_mm = round(max(0.1, muscle_mm - skin_mm), 1)
            method = "bvalgo/fat=muscle-skin"
        else:
            fat_mm = muscle_mm
            method = "bvalgo/muscle-peak"
        valid = is_plausible_mm(fat_mm)
        conf = 0.92 if valid and not (skin_idx and muscle_idx) else 0.75
        return BVThicknessMeasurement(
            fat_thickness_mm=fat_mm,
            muscle_thickness_mm=muscle_mm,
            valid=valid,
            index_at_maximum_thickness=max_idx,
            method=method,
            confidence=conf,
        )

    # Fallback: indexatMaximumThickness only (weaker).
    mm = round(max_idx * MM_PER_BIN, 1)
    return BVThicknessMeasurement(
        fat_thickness_mm=mm,
        muscle_thickness_mm=mm,
        valid=is_plausible_mm(mm) and not (mm <= SKIN_THICKNESS_MM + 0.5),
        index_at_maximum_thickness=max_idx,
        method="bvalgo/index-at-max",
        confidence=0.4,
    )


def thickness_from_packet(payload: bytes) -> BVThicknessMeasurement | None:
    """Full BodyView-style decode from USB bulk packet."""
    if len(payload) < ENVELOPE_OFFSET + 32:
        return None
    try:
        env = envelope_from_payload(payload)
    except ValueError:
        return None
    return get_estimated_thickness(env)
