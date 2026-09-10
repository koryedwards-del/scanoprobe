"""Scanoprobe 0–50 LED scale — echo + gain, no imposed pattern."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from bodymetrix.bvalgo import (
    MM_PER_BIN,
    PEAK_SEARCH_START_BIN,
    envelope_from_payload,
    find_first_peak_in_array,
)
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


def border_led(led_on: tuple[bool, ...] | list[bool]) -> int:
    """
    f/m border depth — rightmost lit LED past skin, only after a dark fat gap.

    Thin fat may show four dark LEDs then one solid border; thicker sites show
    a longer dark run. No fixed gap length — the echo sets how many stay dark.
    """
    if not led_on or len(led_on) < LED_COUNT:
        return 0
    right = rightmost_lit_led(led_on)
    if right <= SKIN_LEDS:
        return 0
    # Require at least one dark LED between skin (1–3) and the border.
    for i in range(SKIN_LEDS, right - 1):
        if not led_on[i]:
            return right
    return 0


@dataclass(frozen=True)
class ScaleReading:
    mm: float | None
    led_on: tuple[bool, ...]


def _find_skin_peak_bin(env: np.ndarray) -> int | None:
    """First tissue peak in the wand echo — skin resistance on contact."""
    head = env[: max(16, len(env) // 32)]
    baseline = float(np.median(head))
    span = max(1.0, float(np.max(env)) - baseline)
    threshold = baseline + 0.08 * span
    skin_search = int(round(SKIN_THICKNESS_MM / MM_PER_BIN)) + 50
    return find_first_peak_in_array(
        env, PEAK_SEARCH_START_BIN, min(len(env) - 2, skin_search), threshold
    )


def _depth_anchor(skin_bin: int) -> int:
    """Map measured skin peak to the 1–3 LED zone (skin reading = source of truth)."""
    return max(0, skin_bin - int(round(2.0 / MM_PER_BIN)))


def _envelope_at_mm(env: np.ndarray, mm: int, anchor: int) -> float:
    bin_idx = anchor + int(round(mm / MM_PER_BIN))
    lo = max(0, bin_idx - 3)
    hi = min(len(env), bin_idx + 4)
    if lo >= hi:
        return 0.0
    return float(np.max(env[lo:hi]))


def _gain_cut(env: np.ndarray, anchor: int, skin_amp: float, dial: float) -> float:
    """
    Threshold from skin resistance upward.

    Low gain  → cut ≈ skin amplitude (only 1–2–3 stay lit)
    Gain up   → cut drops; next density lights; fat gap stays dark
    Too high  → cut reaches weak fat echoes (pinch LEDs light — back off)
    """
    tail = env[anchor : min(len(env), anchor + 550)]
    if len(tail) < 8:
        tail = env
    baseline = float(np.median(tail[: max(8, len(tail) // 8)]))
    floor = min(skin_amp, baseline + 0.05 * max(1.0, skin_amp - baseline))
    return floor + (1.0 - dial) * max(0.0, skin_amp - floor) * 0.98


def leds_for_echo(env: np.ndarray, slider: int) -> tuple[bool, ...]:
    """
    LEDs mirror the echo at each mm depth. No pattern imposed.

    Wand on skin: low gain lights 1–2–3 (resistance), dark fat gap, border
    lights as gain opens. Too much gain lights the fat gap too.
    """
    if slider <= 0 or len(env) < 32:
        return EMPTY_LED_ON
    if float(np.max(env)) < 2.0:
        return EMPTY_LED_ON
    if slider >= SLIDER_MAX:
        return tuple([True] * LED_COUNT)

    skin_bin = _find_skin_peak_bin(env)
    if skin_bin is None:
        anchor = 0
        skin_amp = float(np.max(env[: max(32, len(env) // 16)]))
    else:
        anchor = _depth_anchor(skin_bin)
        lo = max(0, skin_bin - 3)
        hi = min(len(env), skin_bin + 4)
        skin_amp = float(np.max(env[lo:hi]))

    dial = slider / float(SLIDER_MAX)
    cut = _gain_cut(env, anchor, skin_amp, dial)

    on = [False] * LED_COUNT
    for mm in range(1, LED_COUNT + 1):
        if _envelope_at_mm(env, mm, anchor) > cut:
            on[mm - 1] = True
    return tuple(on)


def reading_from_echo(env: np.ndarray, slider: int) -> ScaleReading:
    led_on = leds_for_echo(env, slider)
    border = border_led(led_on)
    mm = float(border) if border > 0 and is_plausible_mm(float(border)) else None
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
            "lcd": border_led(self.led_on),
            "message": self.message,
        }
