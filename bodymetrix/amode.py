"""A-mode ultrasound signal processing: waveform samples → tissue thickness (mm)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ThicknessResult:
    thickness_mm: float
    skin_depth_mm: float
    fat_muscle_depth_mm: float
    confidence: float


def _envelope(signal: np.ndarray) -> np.ndarray:
    rectified = np.abs(signal.astype(np.float64))
    kernel = max(3, len(signal) // 80)
    kernel = kernel if kernel % 2 == 1 else kernel + 1
    pad = kernel // 2
    padded = np.pad(rectified, (pad, pad), mode="edge")
    return np.convolve(padded, np.ones(kernel) / kernel, mode="valid")


def _find_peaks(envelope: np.ndarray, min_distance: int, min_prominence: float) -> list[int]:
    peaks: list[int] = []
    for idx in range(1, len(envelope) - 1):
        if envelope[idx] < envelope[idx - 1] or envelope[idx] < envelope[idx + 1]:
            continue
        left = max(0, idx - min_distance)
        right = min(len(envelope), idx + min_distance + 1)
        neighborhood = envelope[left:right]
        prominence = envelope[idx] - float(np.min(neighborhood))
        if prominence < min_prominence:
            continue
        if peaks and idx - peaks[-1] < min_distance:
            if envelope[idx] > envelope[peaks[-1]]:
                peaks[-1] = idx
            continue
        peaks.append(idx)
    return peaks


def samples_to_thickness_mm(
    samples: np.ndarray,
    sample_rate_hz: float,
    sound_speed_m_s: float = 1540.0,
) -> ThicknessResult:
    """Convert raw A-scan samples to subcutaneous fat thickness in mm."""
    if len(samples) < 32:
        raise ValueError("Need at least 32 samples for thickness calculation.")
    if sample_rate_hz <= 0:
        raise ValueError("sample_rate_hz must be positive.")

    signal = samples.astype(np.float64)
    signal = signal - np.mean(signal)
    peak = np.max(np.abs(signal))
    if peak > 0:
        signal = signal / peak

    envelope = _envelope(signal)
    min_distance = max(4, int(sample_rate_hz * 1e-6))  # ~1 µs between peaks
    min_prominence = max(0.05, float(np.max(envelope)) * 0.08)
    peaks = _find_peaks(envelope, min_distance=min_distance, min_prominence=min_prominence)

    if len(peaks) < 2:
        raise ValueError("Could not find at least two tissue interfaces in waveform.")

    # Scanoprobe / BodyMetrix: first peak = skin entry; second = fat–muscle interface.
    skin_idx, fat_idx = peaks[0], peaks[1]
    seconds_per_sample = 1.0 / sample_rate_hz
    skin_depth_mm = skin_idx * seconds_per_sample * sound_speed_m_s * 0.5 * 1000.0
    fat_muscle_depth_mm = fat_idx * seconds_per_sample * sound_speed_m_s * 0.5 * 1000.0
    thickness_mm = max(0.1, fat_muscle_depth_mm - skin_depth_mm)

    second_peak = float(envelope[fat_idx]) if fat_idx < len(envelope) else 0.0
    confidence = min(1.0, second_peak)

    return ThicknessResult(
        thickness_mm=round(thickness_mm, 1),
        skin_depth_mm=round(skin_depth_mm, 1),
        fat_muscle_depth_mm=round(fat_muscle_depth_mm, 1),
        confidence=round(confidence, 2),
    )
