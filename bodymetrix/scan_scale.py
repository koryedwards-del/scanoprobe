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


def gain_at_index(index: int) -> int:
    i = max(0, min(index, len(GAIN_STEPS) - 1))
    return GAIN_STEPS[i]


def index_for_gain(gain: int) -> int:
    for i, g in enumerate(GAIN_STEPS):
        if g >= gain:
            return i
    return len(GAIN_STEPS) - 1


def _bin_for_led(led: int) -> int:
    return min(int(round(led / MM_PER_BIN)), 1023)


@dataclass(frozen=True)
class ScaleReading:
    """mm is set only when gain has narrowed to a 3-LED fat bracket."""

    mm: float | None
    led_on: tuple[bool, ...]
    bracket: bool
    fat_leds_lit: int
    method: str


def _led_mask(env: np.ndarray) -> list[bool]:
    """
    Which LEDs light from this gain-adjusted envelope.

    The wand gain byte (write_gain_and_read) already shapes the packet —
    we apply a fixed display threshold, same as BodyView on screen.
    """
    baseline = float(np.median(env[:16]))
    span = max(1.0, float(np.max(env) - baseline))
    threshold = baseline + 0.12 * span
    skin_floor = baseline + 0.05 * span

    on = [False] * LED_COUNT
    for led in range(1, LED_COUNT + 1):
        b = _bin_for_led(led)
        if b >= len(env):
            continue
        amp = float(env[b])
        if led <= SKIN_LEDS:
            on[led - 1] = amp > skin_floor
        else:
            on[led - 1] = amp > threshold
    return on


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
    """True mm only when exactly three consecutive fat-zone LEDs (e.g. 14–16)."""
    for start, end in reversed(_fat_zone_runs(led_on)):
        if end - start + 1 == BRACKET_LEDS:
            center = (start + end) / 2.0
            mm = round(center, 1)
            if is_plausible_mm(mm):
                return mm
    return None


def _fat_leds_lit(led_on: list[bool]) -> int:
    return sum(1 for i in range(SKIN_LEDS, LED_COUNT) if led_on[i])


def scale_reading_from_payload(payload: bytes, gain_byte: int = 0) -> ScaleReading | None:
    """
    Wand packet at this gain → LED pattern.

    No true mm without gain control: mm is returned only in the 3-LED bracket state.
    gain_byte is sent to the wand before read (write_gain_and_read); it shapes the packet.
    """
    if not is_bodyview_bx_packet(payload):
        return None
    # Real BX packets are 2048 bytes with trailing zeros — check header+envelope only.
    if is_placeholder_payload(payload[:128]):
        return None
    try:
        env = envelope_from_payload(payload)
    except ValueError:
        return None

    led_on = _led_mask(env)
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


def scale_mm_from_payload(payload: bytes, gain_byte: int = 0) -> float | None:
    reading = scale_reading_from_payload(payload, gain_byte)
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
        return "No fat signal — dial + gain"
    return "Dial gain to three-LED bracket"


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
            "led_on": list(self.led_on),
            "led_level": led_level(mm),
            "led_max": LED_COUNT,
            "message": self.message,
        }
