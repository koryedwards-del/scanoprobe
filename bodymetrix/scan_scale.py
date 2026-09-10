"""Scanoprobe 0–50 LED scale — true mm only after gain brackets the fascia."""

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
DEFAULT_GAIN_INDEX = 0
# Top gain steps fill all 50 LEDs (+ on dial); dialing − collapses to 3-LED bracket.
FULL_BAR_GAIN_INDEX = len(GAIN_STEPS) - 4
EMPTY_LED_ON: tuple[bool, ...] = tuple([False] * LED_COUNT)


def gain_at_index(index: int) -> int:
    i = max(0, min(index, len(GAIN_STEPS) - 1))
    return GAIN_STEPS[i]


def index_for_gain(gain: int) -> int:
    for i, g in enumerate(GAIN_STEPS):
        if g >= gain:
            return i
    return len(GAIN_STEPS) - 1


def _led_for_bin(bin_idx: int) -> int | None:
    """Envelope bin index → LED number (1–50) on depth axis."""
    if bin_idx < 1:
        return None
    led = max(1, min(LED_COUNT, round(bin_idx * MM_PER_BIN)))
    return led


@dataclass(frozen=True)
class ScaleReading:
    """mm is set only when gain has narrowed to a 3-LED fat bracket."""

    mm: float | None
    led_on: tuple[bool, ...]
    bracket: bool
    fat_leds_lit: int
    method: str


def bracket_mode_active(gain_index: int, peak_gain_index: int) -> bool:
    """Bracket collapse only after the bar has filled (+ to top), then dial −."""
    return (
        peak_gain_index >= FULL_BAR_GAIN_INDEX
        and gain_index < FULL_BAR_GAIN_INDEX
    )


def _progressive_fill_mask(gain_index: int) -> list[bool]:
    """Gain + fills LEDs 1..N until the bar is full at FULL_BAR_GAIN_INDEX."""
    if gain_index >= FULL_BAR_GAIN_INDEX:
        return [True] * LED_COUNT
    fill_to = min(
        LED_COUNT,
        max(0, int(round((gain_index / FULL_BAR_GAIN_INDEX) * LED_COUNT))),
    )
    on = [False] * LED_COUNT
    for led in range(1, fill_to + 1):
        on[led - 1] = True
    return on


def _envelope_bracket_mask(env: np.ndarray, gain_byte: int) -> list[bool]:
    """Skin (1–3) + three fat LEDs around envelope fascia peak."""
    peak = float(np.max(env))
    if peak < 2.0:
        return [False] * LED_COUNT

    gain_frac = max(0.0, min(1.0, gain_byte / 255.0))
    threshold = peak * (0.92 - 0.88 * gain_frac)
    skin_threshold = peak * (0.82 - 0.72 * gain_frac)

    center = 0
    for led in range(LED_COUNT, SKIN_LEDS, -1):
        bin_idx = int(round(led / MM_PER_BIN))
        if bin_idx < len(env) and float(env[bin_idx]) > threshold:
            center = led
            break

    on = [False] * LED_COUNT
    for led in range(1, SKIN_LEDS + 1):
        bin_idx = int(round(led / MM_PER_BIN))
        if bin_idx < len(env) and float(env[bin_idx]) > skin_threshold:
            on[led - 1] = True

    if center >= SKIN_LEDS + 1:
        for led in range(center - 1, center + 2):
            if 1 <= led <= LED_COUNT:
                on[led - 1] = True
    return on


def leds_for_echo(
    env: np.ndarray,
    gain_byte: int,
    gain_index: int,
    peak_gain_index: int,
) -> tuple[bool, ...]:
    """1982 LED bar from last echo envelope + current gain."""
    bracket_mode = bracket_mode_active(gain_index, peak_gain_index)
    return tuple(_led_mask(env, gain_byte, gain_index, bracket_mode))


def reading_from_led_on(
    led_on: tuple[bool, ...], gain_byte: int
) -> ScaleReading:
    """Bracket/mm state from an LED pattern."""
    led_list = list(led_on)
    mm = _bracket_mm(led_list)
    fat_lit = _fat_leds_lit(led_list)
    bracket = mm is not None
    if bracket:
        method = f"bracket@{mm}g{gain_byte}"
    elif fat_lit >= LED_COUNT - SKIN_LEDS - 2:
        method = f"full-bar/g{gain_byte}"
    elif fat_lit == 0:
        method = f"no-signal/g{gain_byte}"
    else:
        method = f"tuning/g{gain_byte}/lit{fat_lit}"
    return ScaleReading(mm, led_on, bracket, fat_lit, method)


def _led_mask(
    env: np.ndarray,
    gain_byte: int,
    gain_index: int,
    bracket_mode: bool,
) -> list[bool]:
    """
    Gain + always grows the bar (progressive fill).

    After the bar has filled once, dialing − collapses to a 3-LED fascia bracket.
    """
    if gain_index >= FULL_BAR_GAIN_INDEX:
        return [True] * LED_COUNT
    if not bracket_mode:
        return _progressive_fill_mask(gain_index)
    mask = _envelope_bracket_mask(env, gain_byte)
    if sum(mask) == 0:
        return _progressive_fill_mask(gain_index)
    return mask


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


def _bracket_mm(led_on: list[bool]) -> float | None:
    """True mm = center of three fat-zone LEDs (e.g. 14–16 → 15)."""
    for start, end in reversed(_fat_zone_runs(led_on)):
        if end - start + 1 == BRACKET_LEDS:
            center = (start + end) / 2.0
            mm = round(center, 1)
            if is_plausible_mm(mm):
                return mm
    return None


def _fat_leds_lit(led_on: list[bool]) -> int:
    return sum(1 for i in range(SKIN_LEDS, LED_COUNT) if led_on[i])


def scale_reading_from_payload(
    payload: bytes,
    gain_byte: int = 0,
    gain_index: int = DEFAULT_GAIN_INDEX,
    peak_gain_index: int = DEFAULT_GAIN_INDEX,
) -> ScaleReading | None:
    """
    Wand packet at this gain → LED pattern.

    No true mm without gain control: mm is returned only in the 3-LED bracket state.
    gain_byte is sent to the wand before read (write_gain_and_read); it shapes the packet.
    """
    if not is_bodyview_bx_packet(payload):
        return None
    # Real BX packets are 2048 bytes with trailing zeros — check header+envelope only.
    if is_placeholder_payload(payload):
        return None
    try:
        env = envelope_from_payload(payload)
    except ValueError:
        return None

    bracket_mode = bracket_mode_active(gain_index, peak_gain_index)
    led_on = _led_mask(env, gain_byte, gain_index, bracket_mode)
    mm = _bracket_mm(led_on)
    fat_lit = _fat_leds_lit(led_on)
    bracket = mm is not None

    if bracket:
        method = f"bracket@{mm}g{gain_byte}"
    elif fat_lit >= LED_COUNT - SKIN_LEDS - 2:
        method = f"full-bar/g{gain_byte}"
    elif fat_lit == 0:
        method = f"no-signal/g{gain_byte}"
    else:
        method = f"tuning/g{gain_byte}/lit{fat_lit}"

    return ScaleReading(mm, tuple(led_on), bracket, fat_lit, method)


def scale_mm_from_payload(
    payload: bytes,
    gain_byte: int = 0,
    gain_index: int = DEFAULT_GAIN_INDEX,
    peak_gain_index: int = DEFAULT_GAIN_INDEX,
) -> float | None:
    reading = scale_reading_from_payload(
        payload, gain_byte, gain_index, peak_gain_index
    )
    return reading.mm if reading else None


def led_level(mm: float | None) -> int:
    if mm is None:
        return 0
    return max(0, min(LED_COUNT, int(round(mm))))


def reading_hint(reading: ScaleReading) -> str:
    if reading.bracket and reading.mm is not None:
        return f"{reading.mm:g} mm — HOLD to lock"
    if reading.fat_leds_lit >= LED_COUNT - SKIN_LEDS - 2:
        return "Bar full — dial − to bracket"
    if reading.fat_leds_lit == 0:
        return "No LEDs at this gain — press + (BX: hold SEND on skin)"
    return "Dial gain to three-LED bracket"


@dataclass
class ScanScaleState:
    active: bool = False
    site: int | None = None
    gain_index: int = DEFAULT_GAIN_INDEX
    peak_gain_index: int = DEFAULT_GAIN_INDEX
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
