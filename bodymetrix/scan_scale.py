"""Scanoprobe 0–50 LED scale — follow the 1982 flow."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from bodymetrix.bvalgo import MM_PER_BIN, envelope_from_payload
from bodymetrix.bodyview_parse import is_bodyview_bx_packet
from bodymetrix.mm_bounds import SKIN_THICKNESS_MM, is_plausible_mm
from bodymetrix.scanoprobe import is_placeholder_payload

LED_COUNT = 50
SKIN_LEDS = int(round(SKIN_THICKNESS_MM))

GAIN_STEPS: tuple[int, ...] = tuple(range(0, 256, 2))
DEFAULT_GAIN_INDEX = 0
SLIDER_MAX = LED_COUNT
FULL_BAR_GAIN_INDEX = len(GAIN_STEPS) - 1
LISTEN_GAIN_INDEX = len(GAIN_STEPS) // 2
LISTEN_GAIN_BYTE = GAIN_STEPS[LISTEN_GAIN_INDEX]
EMPTY_LED_ON: tuple[bool, ...] = tuple([False] * LED_COUNT)


def gain_at_index(index: int) -> int:
    i = max(0, min(index, len(GAIN_STEPS) - 1))
    return GAIN_STEPS[i]


def gain_index_for_slider(slider: int) -> int:
    if slider <= 0:
        return 0
    idx = int(round((slider / float(SLIDER_MAX)) * FULL_BAR_GAIN_INDEX))
    return max(0, min(idx, FULL_BAR_GAIN_INDEX))


def slider_for_gain_index(gain_index: int) -> int:
    if gain_index <= 0:
        return 0
    return int(round((gain_index / float(FULL_BAR_GAIN_INDEX)) * SLIDER_MAX))


def rightmost_lit_led(led_on: tuple[bool, ...] | list[bool]) -> int:
    if not led_on or len(led_on) < LED_COUNT:
        return 0
    for i in range(LED_COUNT - 1, -1, -1):
        if led_on[i]:
            return i + 1
    return 0


@dataclass(frozen=True)
class ScaleReading:
    mm: float | None
    led_on: tuple[bool, ...]


def _envelope_at_mm(env: np.ndarray, mm: int) -> float:
    """Echo amplitude at this depth on the 1–50 mm bar."""
    bin_idx = int(round(mm / MM_PER_BIN))
    lo = max(0, bin_idx - 2)
    hi = min(len(env), bin_idx + 3)
    if lo >= hi:
        return 0.0
    return float(np.max(env[lo:hi]))


def leds_for_echo(env: np.ndarray, slider: int) -> tuple[bool, ...]:
    """
    1982 flow on cached wand echo:

    gain 0 → dark
    gain up → bar fills (all on at 50)
    gain down → threshold rises, LEDs drop where echo is weak
    """
    if slider <= 0 or len(env) < 32:
        return EMPTY_LED_ON
    if float(np.max(env)) < 2.0:
        return EMPTY_LED_ON
    if slider >= SLIDER_MAX:
        return tuple([True] * LED_COUNT)

    dial = slider / float(SLIDER_MAX)
    baseline = float(np.median(env[:16]))
    peak = float(np.max(env))
    span = max(1.0, peak - baseline)
    cut = peak - span * dial * 0.98

    on = [False] * LED_COUNT
    for mm in range(1, LED_COUNT + 1):
        if _envelope_at_mm(env, mm) > cut:
            on[mm - 1] = True
    return tuple(on)


def reading_from_echo(env: np.ndarray, slider: int) -> ScaleReading:
    led_on = leds_for_echo(env, slider)
    lcd = rightmost_lit_led(led_on)
    mm = float(lcd) if lcd > SKIN_LEDS and is_plausible_mm(float(lcd)) else None
    return ScaleReading(mm, led_on)


def scale_reading_from_payload(payload: bytes, slider: int = 0) -> ScaleReading | None:
    if not is_bodyview_bx_packet(payload) or is_placeholder_payload(payload):
        return None
    try:
        env = envelope_from_payload(payload)
    except ValueError:
        return None
    return reading_from_echo(env, slider)


def scale_mm_from_payload(
    payload: bytes,
    gain_byte: int = 0,
    gain_index: int = DEFAULT_GAIN_INDEX,
) -> float | None:
    slider = slider_for_gain_index(gain_index) if gain_index else 0
    reading = scale_reading_from_payload(payload, slider=slider)
    return reading.mm if reading else None


@dataclass
class ScanScaleState:
    active: bool = False
    site: int | None = None
    gain_index: int = DEFAULT_GAIN_INDEX
    slider: int = 0
    locked: bool = False
    locked_mm: float | None = None
    live_mm: float | None = None
    led_on: tuple[bool, ...] = EMPTY_LED_ON
    message: str = ""

    @property
    def gain(self) -> int:
        return gain_at_index(self.gain_index)

    def set_slider(self, slider: int) -> None:
        self.slider = max(0, min(int(slider), SLIDER_MAX))
        self.gain_index = gain_index_for_slider(self.slider)

    def to_dict(self) -> dict:
        mm = self.locked_mm if self.locked else self.live_mm
        return {
            "active": self.active,
            "site": self.site,
            "gain": self.gain,
            "gain_index": self.gain_index,
            "slider": self.slider,
            "slider_max": SLIDER_MAX,
            "locked": self.locked,
            "mm": mm,
            "live_mm": self.live_mm,
            "locked_mm": self.locked_mm,
            "led_on": list(self.led_on),
            "lcd": rightmost_lit_led(self.led_on),
            "message": self.message,
        }
