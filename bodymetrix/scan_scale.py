"""Scanoprobe-style 0–50 LED scale: gain fine-tunes mm (no waveform graph)."""

from __future__ import annotations

from dataclasses import dataclass

from bodymetrix.bodyview_parse import header_byte3_mm, is_bodyview_bx_packet
from bodymetrix.mm_bounds import MAX_PLAUSIBLE_MM, MIN_PLAUSIBLE_MM, is_plausible_mm
from bodymetrix.scanoprobe import is_placeholder_payload

LED_MAX_MM = 50
LED_COUNT = 50

# Scanoprobe gain dial steps (uchar); coarse clicks on the wand.
GAIN_STEPS: tuple[int, ...] = (
    0,
    8,
    16,
    24,
    32,
    40,
    48,
    56,
    64,
    72,
    80,
    88,
    96,
    104,
    112,
    128,
    144,
    160,
    176,
    192,
    208,
    224,
    240,
    255,
)
DEFAULT_GAIN_INDEX = 0  # gain 0 — operator cranks up, then dials back


def gain_at_index(index: int) -> int:
    i = max(0, min(index, len(GAIN_STEPS) - 1))
    return GAIN_STEPS[i]


def index_for_gain(gain: int) -> int:
    for i, g in enumerate(GAIN_STEPS):
        if g >= gain:
            return i
    return len(GAIN_STEPS) - 1


def scale_mm_from_payload(payload: bytes) -> float | None:
    """
    LED scale mm — firmware byte 3 on BX packets (00 00 00 XX).
    Gain moves which peak/threshold fires → different mm on the 0–50 bar.
    """
    if is_placeholder_payload(payload):
        return None
    if is_bodyview_bx_packet(payload):
        mm = header_byte3_mm(payload)
        if mm is not None:
            return round(mm, 1)
    return None


def led_level(mm: float | None) -> int:
    """How many LEDs (1–50) to light; 0 = no reading."""
    if mm is None:
        return 0
    return max(0, min(LED_COUNT, int(round(mm))))


@dataclass
class ScanScaleState:
    active: bool = False
    site: int | None = None
    gain_index: int = DEFAULT_GAIN_INDEX
    locked: bool = False
    locked_mm: float | None = None
    live_mm: float | None = None
    message: str = ""

    @property
    def gain(self) -> int:
        return gain_at_index(self.gain_index)

    def to_dict(self) -> dict:
        mm = self.locked_mm if self.locked else self.live_mm
        return {
            "active": self.active,
            "site": self.site,
            "gain": self.gain,
            "gain_index": self.gain_index,
            "gain_steps": len(GAIN_STEPS),
            "locked": self.locked,
            "mm": mm,
            "live_mm": self.live_mm,
            "locked_mm": self.locked_mm,
            "led_level": led_level(mm),
            "led_max": LED_COUNT,
            "message": self.message,
        }
