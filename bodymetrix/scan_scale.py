"""Scanoprobe 0–50 LED scale — gain + echo threshold → LEDs; 3 fat LEDs → mm."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from bodymetrix.bvalgo import MM_PER_BIN, envelope_from_payload
from bodymetrix.bodyview_parse import is_bodyview_bx_packet
from bodymetrix.mm_bounds import is_plausible_mm
from bodymetrix.scanoprobe import is_placeholder_payload

LED_COUNT = 50
SKIN_LEDS = 3
BRACKET_LEDS = 3

# Internal wand gain bytes; UI slider is 0–50 (matches depth bar).
GAIN_STEPS: tuple[int, ...] = tuple(range(0, 256, 2))
DEFAULT_GAIN_INDEX = 0
SLIDER_MAX = LED_COUNT
FULL_BAR_GAIN_INDEX = len(GAIN_STEPS) - 1
FULL_BAR_GAIN_BYTE = GAIN_STEPS[FULL_BAR_GAIN_INDEX]
EMPTY_LED_ON: tuple[bool, ...] = tuple([False] * LED_COUNT)


def gain_at_index(index: int) -> int:
    i = max(0, min(index, len(GAIN_STEPS) - 1))
    return GAIN_STEPS[i]


def index_for_gain(gain: int) -> int:
    for i, g in enumerate(GAIN_STEPS):
        if g >= gain:
            return i
    return len(GAIN_STEPS) - 1


def gain_index_for_slider(slider: int) -> int:
    """Map UI slider 0–50 → wand gain index."""
    if slider <= 0:
        return 0
    idx = int(round((slider / float(SLIDER_MAX)) * FULL_BAR_GAIN_INDEX))
    return max(0, min(idx, FULL_BAR_GAIN_INDEX))


def slider_for_gain_index(gain_index: int) -> int:
    """Map wand gain index → UI slider 0–50."""
    if gain_index <= 0:
        return 0
    return int(round((gain_index / float(FULL_BAR_GAIN_INDEX)) * SLIDER_MAX))


def rightmost_lit_led(led_on: tuple[bool, ...] | list[bool]) -> int:
    """Rightmost lit LED position 1–50, or 0 if none."""
    if not led_on or len(led_on) < LED_COUNT:
        return 0
    for i in range(LED_COUNT - 1, -1, -1):
        if led_on[i]:
            return i + 1
    return 0


def leds_for_slider(slider: int) -> tuple[bool, ...]:
    """Slider 0–50 → that many LEDs on (1..N). Far left 0, far right 50."""
    n = max(0, min(SLIDER_MAX, int(slider)))
    on = [False] * LED_COUNT
    for led in range(1, n + 1):
        on[led - 1] = True
    return tuple(on)


@dataclass(frozen=True)
class ScaleReading:
    """mm when gain + echo leave exactly three consecutive fat LEDs (ignore 1–3)."""

    mm: float | None
    led_on: tuple[bool, ...]
    bracket: bool
    fat_leds_lit: int
    method: str


def _bin_for_led(led: int) -> int:
    return int(round(led / MM_PER_BIN))


def _envelope_at_led(env: np.ndarray, led: int) -> float:
    """Peak envelope near this depth LED (1–50 mm axis)."""
    bin_idx = _bin_for_led(led)
    lo = max(0, bin_idx - 2)
    hi = min(len(env), bin_idx + 3)
    if lo >= hi:
        return 0.0
    return float(np.max(env[lo:hi]))


def _dial_fraction(slider: int) -> float:
    """UI slider 0–50 → 0.0–1.0 software gain along the depth bar."""
    if slider <= 0:
        return 0.0
    return min(1.0, int(slider) / float(SLIDER_MAX))


def _envelope_threshold_mask(
    env: np.ndarray,
    gain_byte: int,
    gain_index: int,
    slider: int = 0,
) -> list[bool]:
    """
    1982 gain on cached echo: slider opens sensitivity shallow → deep.

    Software threshold on the envelope (BX packet); wand gain byte is separate.
    Bar fills contiguously from LED 1; slide left peels from the deep end.
    """
    if slider <= 0 or len(env) < 32:
        return [False] * LED_COUNT
    if float(np.max(env)) < 2.0:
        return [False] * LED_COUNT

    dial = _dial_fraction(slider)
    if dial >= 1.0:
        return [True] * LED_COUNT

    baseline = float(np.median(env[:16]))
    peak = float(np.max(env))
    span = max(1.0, peak - baseline)
    floor = baseline + 0.05 * span
    fill_to = max(0, int(round(dial * LED_COUNT)))
    threshold = peak - span * dial * 0.98

    rightmost = 0
    for led in range(1, fill_to + 1):
        if _envelope_at_led(env, led) > max(floor, threshold):
            rightmost = led

    on = [False] * LED_COUNT
    for led in range(1, rightmost + 1):
        on[led - 1] = True
    return on


def _bar_full(led_on: list[bool], env: np.ndarray, gain_byte: int) -> bool:
    """Bar full — all 50 LEDs lit at top gain."""
    return sum(led_on) >= LED_COUNT - 2 and gain_byte >= FULL_BAR_GAIN_BYTE


def leds_for_echo(
    env: np.ndarray,
    gain_byte: int,
    gain_index: int,
    slider: int = 0,
) -> tuple[bool, ...]:
    """Cached echo + software gain (slider) → which depth LEDs light."""
    return tuple(_envelope_threshold_mask(env, gain_byte, gain_index, slider))


def _fat_zone_runs(led_on: list[bool]) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for led in range(SKIN_LEDS + 1, LED_COUNT + 1):
        if led_on[led - 1]:
            if start is None:
                start = led
        elif start is not None:
            runs.append((start, led - 1))
            start = None
    if start is not None:
        runs.append((start, LED_COUNT))
    return runs


def _fat_leds_lit(led_on: list[bool]) -> int:
    return sum(1 for i in range(SKIN_LEDS, LED_COUNT) if led_on[i])


def _mm_from_gain_leds(led_on: list[bool], gain_index: int) -> float | None:
    """
    True mm when this gain leaves exactly three consecutive fat LEDs.

    Not a separate mode — gain sets the threshold; three lit fat LEDs = reading.
    Ignore skin LEDs 1–3.
    """
    if gain_index <= 0:
        return None
    if _fat_leds_lit(led_on) != BRACKET_LEDS:
        return None
    for start, end in reversed(_fat_zone_runs(led_on)):
        if end - start + 1 == BRACKET_LEDS and start > SKIN_LEDS:
            mm = round((start + end) / 2.0, 1)
            if is_plausible_mm(mm):
                return mm
    return None


def _reading_from_parts(
    led_on: tuple[bool, ...],
    gain_byte: int,
    gain_index: int,
    env: np.ndarray | None = None,
) -> ScaleReading:
    if gain_index <= 0 or gain_byte <= 0:
        dark = tuple([False] * LED_COUNT)
        return ScaleReading(None, dark, False, 0, "gain0")

    led_list = list(led_on)
    mm = _mm_from_gain_leds(led_list, gain_index)
    fat_lit = _fat_leds_lit(led_list)
    bracket = mm is not None
    if bracket:
        method = f"3led@{mm}g{gain_byte}"
    elif env is not None and _bar_full(led_list, env, gain_byte):
        method = f"full-bar/g{gain_byte}"
    elif fat_lit == 0:
        method = f"no-signal/g{gain_byte}"
    else:
        method = f"gain{gain_index}/lit{sum(led_on)}g{gain_byte}"
    return ScaleReading(mm, led_on, bracket, fat_lit, method)


def reading_from_led_on(
    led_on: tuple[bool, ...],
    gain_byte: int,
    gain_index: int = DEFAULT_GAIN_INDEX,
    env: np.ndarray | None = None,
) -> ScaleReading:
    return _reading_from_parts(led_on, gain_byte, gain_index, env)


def reading_from_echo(
    env: np.ndarray,
    gain_byte: int,
    gain_index: int,
    slider: int = 0,
) -> ScaleReading:
    """Software gain on cached echo → LED bar; LCD = rightmost lit."""
    led_on = leds_for_echo(env, gain_byte, gain_index, slider)
    return reading_from_led_on(led_on, gain_byte, gain_index, env)


def scale_reading_from_payload(
    payload: bytes,
    gain_byte: int = 0,
    gain_index: int = DEFAULT_GAIN_INDEX,
    slider: int = 0,
) -> ScaleReading | None:
    """
    Wand packet at this gain → echo threshold → LEDs → mm when three fat LEDs.

    gain_byte is sent to the wand before read; it shapes echo amplitude.
    """
    if not is_bodyview_bx_packet(payload):
        return None
    if is_placeholder_payload(payload):
        return None
    try:
        env = envelope_from_payload(payload)
    except ValueError:
        return None

    return reading_from_echo(env, gain_byte, gain_index, slider)


def scale_mm_from_payload(
    payload: bytes,
    gain_byte: int = 0,
    gain_index: int = DEFAULT_GAIN_INDEX,
) -> float | None:
    reading = scale_reading_from_payload(payload, gain_byte, gain_index)
    return reading.mm if reading else None


def led_level(mm: float | None) -> int:
    if mm is None:
        return 0
    return max(0, min(LED_COUNT, int(round(mm))))


def reading_hint(reading: ScaleReading) -> str:
    if reading.mm is not None:
        return f"{reading.mm:g} mm — HOLD to lock"
    if sum(reading.led_on) >= LED_COUNT - 2:
        return "Bar full — dial − until three fat LEDs remain"
    if sum(reading.led_on) == 0:
        return "Slider left — no LEDs. Slide right to light the bar."
    lit = sum(reading.led_on)
    return f"{lit} LEDs lit — slide to tune"


@dataclass
class ScanScaleState:
    active: bool = False
    site: int | None = None
    gain_index: int = DEFAULT_GAIN_INDEX
    slider: int = 0
    locked: bool = False
    locked_mm: float | None = None
    live_mm: float | None = None
    led_on: tuple[bool, ...] = ()
    bracket: bool = False
    message: str = ""

    @property
    def gain(self) -> int:
        return gain_at_index(self.gain_index)

    def set_slider(self, slider: int) -> None:
        self.slider = max(0, min(int(slider), SLIDER_MAX))
        self.gain_index = gain_index_for_slider(self.slider)

    def set_gain_index(self, index: int) -> None:
        self.gain_index = max(0, min(int(index), len(GAIN_STEPS) - 1))
        self.slider = slider_for_gain_index(self.gain_index)

    def to_dict(self) -> dict:
        mm = self.locked_mm if self.locked else self.live_mm
        return {
            "active": self.active,
            "site": self.site,
            "gain": self.gain,
            "gain_index": self.gain_index,
            "slider": self.slider,
            "slider_max": SLIDER_MAX,
            "gain_steps": len(GAIN_STEPS),
            "locked": self.locked,
            "bracket": self.bracket,
            "mm": mm,
            "live_mm": self.live_mm,
            "locked_mm": self.locked_mm,
            "led_on": list(self.led_on) if len(self.led_on) >= LED_COUNT else list(EMPTY_LED_ON),
            "lcd": rightmost_lit_led(self.led_on),
            "led_level": led_level(mm),
            "led_max": LED_COUNT,
            "message": self.message,
        }
