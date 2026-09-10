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

# Fine dial: 128 steps (0, 2, 4, … 254) — like turning the 1982 gain knob.
GAIN_STEPS: tuple[int, ...] = tuple(range(0, 256, 2))
DEFAULT_GAIN_INDEX = 0
# Top of the dial (slider right) → all 50 LEDs on when echo is present.
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
    return float(np.max(env[lo:hi]))


def _eligible_echo_leds(env: np.ndarray) -> list[tuple[float, int]]:
    """Depth LEDs with real echo at this site — (amplitude, led number)."""
    if len(env) < 32 or float(np.max(env)) < 2.0:
        return []
    baseline = float(np.median(env[:16]))
    span = max(1.0, float(np.max(env)) - baseline)
    floor = baseline + 0.06 * span
    eligible: list[tuple[float, int]] = []
    for led in range(1, LED_COUNT + 1):
        amp = _envelope_at_led(env, led)
        if amp > floor:
            eligible.append((amp, led))
    return eligible


def _full_bar_gain(gain_byte: int, gain_index: int) -> bool:
    return gain_index >= FULL_BAR_GAIN_INDEX or gain_byte >= FULL_BAR_GAIN_BYTE


def _envelope_threshold_mask(
    env: np.ndarray, gain_byte: int, gain_index: int
) -> list[bool]:
    """
    Gain dial turns LEDs on/off at real echo depths.

    Top of dial → all 50 LEDs on (1982 bar full).
    Below that: + gain adds depths; − removes weakest-first.
    """
    if gain_index <= 0 or gain_byte <= 0 or len(env) < 32:
        return [False] * LED_COUNT
    if float(np.max(env)) < 2.0:
        return [False] * LED_COUNT
    if _full_bar_gain(gain_byte, gain_index):
        return [True] * LED_COUNT

    eligible = _eligible_echo_leds(env)
    if not eligible:
        return [False] * LED_COUNT

    dial = min(1.0, max(0.0, gain_byte / float(FULL_BAR_GAIN_BYTE)))
    eligible.sort(key=lambda item: item[0])  # weakest .. strongest
    n_lit = int(round(dial * len(eligible)))
    if dial > 0 and n_lit < 1:
        n_lit = 1

    on = [False] * LED_COUNT
    for _, led in eligible[-n_lit:]:
        on[led - 1] = True
    return on


def _bar_full(led_on: list[bool], env: np.ndarray, gain_byte: int) -> bool:
    """Bar full — all 50 LEDs lit at top gain."""
    return sum(led_on) >= LED_COUNT - 2 and gain_byte >= FULL_BAR_GAIN_BYTE


def leds_for_echo(
    env: np.ndarray,
    gain_byte: int,
    gain_index: int,
) -> tuple[bool, ...]:
    """Echo + gain → which depth LEDs light."""
    return tuple(_envelope_threshold_mask(env, gain_byte, gain_index))


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
    if gain_index <= 0:
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


def scale_reading_from_payload(
    payload: bytes,
    gain_byte: int = 0,
    gain_index: int = DEFAULT_GAIN_INDEX,
) -> ScaleReading | None:
    """
    Wand packet at this gain → LED pattern → mm when three fat LEDs remain.

    gain_byte is sent to the wand before read; it shapes the packet.
    """
    if not is_bodyview_bx_packet(payload):
        return None
    if is_placeholder_payload(payload):
        return None
    try:
        env = envelope_from_payload(payload)
    except ValueError:
        return None

    led_on = tuple(_envelope_threshold_mask(env, gain_byte, gain_index))
    return _reading_from_parts(led_on, gain_byte, gain_index, env)


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
    if reading.fat_leds_lit == 0:
        return "Gain 0 — dark. Press + with SEND held on gel."
    lit = sum(reading.led_on)
    return f"+ gain → LEDs appear ({lit} lit); − they fade; 0 = dark"


@dataclass
class ScanScaleState:
    active: bool = False
    site: int | None = None
    gain_index: int = DEFAULT_GAIN_INDEX
    locked: bool = False
    locked_mm: float | None = None
    live_mm: float | None = None
    led_on: tuple[bool, ...] = ()
    bracket: bool = False
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
            "bracket": self.bracket,
            "mm": mm,
            "live_mm": self.live_mm,
            "locked_mm": self.locked_mm,
            "led_on": list(self.led_on) if len(self.led_on) >= LED_COUNT else list(EMPTY_LED_ON),
            "led_level": led_level(mm),
            "led_max": LED_COUNT,
            "message": self.message,
        }
