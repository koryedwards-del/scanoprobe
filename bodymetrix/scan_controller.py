"""Scanoprobe LED scan session — gain, HOLD lock, live mm (no device.py bloat)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from bodymetrix.bvalgo import envelope_from_payload
from bodymetrix.scan_scale import (
    DEFAULT_GAIN_INDEX,
    EMPTY_LED_ON,
    FULL_BAR_GAIN_INDEX,
    GAIN_STEPS,
    ScanScaleState,
    leds_for_echo,
    reading_from_led_on,
    reading_hint,
    scale_reading_from_payload,
)
from bodymetrix.scanoprobe import is_placeholder_payload

if TYPE_CHECKING:
    from bodymetrix.device import BodyMetrixProbe


class BodyMetrixError(RuntimeError):
    pass


class ScanController:
    """0–50 LED scale session using an open BodyMetrixProbe."""

    def __init__(self, probe: BodyMetrixProbe) -> None:
        self._probe = probe
        self._state = ScanScaleState()
        self._last_env: np.ndarray | None = None

    def state(self) -> dict[str, Any]:
        out = self._state.to_dict()
        out["has_echo"] = self._last_env is not None
        return out

    def _apply_cached_leds(self) -> None:
        """Instant LED update from last echo — gain changes without waiting on USB."""
        if self._last_env is None:
            return
        self._state.led_on = leds_for_echo(
            self._last_env,
            self._state.gain,
            self._state.gain_index,
            self._state.peak_gain_index,
        )
        reading = reading_from_led_on(self._state.led_on, self._state.gain)
        self._state.bracket = reading.bracket
        self._state.live_mm = reading.mm
        self._state.message = reading_hint(reading)

    def _ingest_capture(self, payload: bytes, gain: int) -> bool:
        """Decode echo → cache envelope + LED bar. Returns True when echo accepted."""
        reading = scale_reading_from_payload(
            payload,
            gain_byte=gain,
            gain_index=self._state.gain_index,
            peak_gain_index=self._state.peak_gain_index,
        )
        if reading is None:
            return False
        try:
            self._last_env = envelope_from_payload(payload)
        except ValueError:
            return False
        self._state.led_on = reading.led_on
        self._state.bracket = reading.bracket
        self._state.live_mm = reading.mm
        self._state.message = reading_hint(reading)
        return True

    def begin(self, site: int) -> dict[str, Any]:
        self._last_env = None
        self._state = ScanScaleState(
            active=True,
            site=site,
            gain_index=DEFAULT_GAIN_INDEX,
            led_on=EMPTY_LED_ON,
            message="Gel + hold SEND on BX wand. No LEDs without gain — press +.",
        )
        self._probe.ensure_session()
        return self.state()

    def end(self) -> dict[str, Any]:
        self._last_env = None
        self._state = ScanScaleState()
        return self.state()

    def adjust_gain(self, delta: int) -> dict[str, Any]:
        if not self._state.active:
            raise BodyMetrixError("Scan not active.")
        if self._state.locked:
            raise BodyMetrixError("Release HOLD before changing gain.")
        idx = self._state.gain_index + int(delta)
        return self.set_gain_index(idx)

    def set_gain_index(self, index: int) -> dict[str, Any]:
        """Fast gain step — write to wand, update LEDs from cached echo (no USB wait)."""
        if not self._state.active:
            raise BodyMetrixError("Scan not active.")
        if self._state.locked:
            raise BodyMetrixError("Release HOLD before changing gain.")
        self._state.gain_index = max(0, min(int(index), len(GAIN_STEPS) - 1))
        self._state.peak_gain_index = max(
            self._state.peak_gain_index, self._state.gain_index
        )
        probe = self._probe
        probe.ensure_session()
        if not probe._pipes_configured:
            probe.bodyview_init()
        probe.write_gain(self._state.gain)
        if self._last_env is not None:
            self._apply_cached_leds()
        elif self._state.gain_index > 0:
            self._state.message = (
                f"Gain {self._state.gain_index} — hold SEND on gel for LEDs to fill."
            )
        return self.state()

    def toggle_hold(self) -> dict[str, Any]:
        if not self._state.active:
            raise BodyMetrixError("Scan not active.")
        if self._state.locked:
            self._state.locked = False
            self._state.locked_mm = None
            self._state.message = "HOLD released — adjust gain or re-lock."
        else:
            if self._state.live_mm is None:
                raise BodyMetrixError(
                    "No true mm yet — + fill bar, − to three-LED bracket, then HOLD."
                )
            self._state.locked = True
            self._state.locked_mm = self._state.live_mm
            self._state.message = (
                f"LOCKED {self._state.locked_mm:g} mm — put down wand, then save."
            )
        return self.state()

    def tick(self) -> dict[str, Any]:
        if not self._state.active:
            raise BodyMetrixError("Scan not active.")
        if self._state.locked:
            return self.state()

        probe = self._probe
        probe.ensure_session()
        if not probe._pipes_configured:
            probe.bodyview_init()

        gain = self._state.gain
        probe.write_gain(gain)
        # Proven BX path: OUT a001 while SEND is held (same as successful captures).
        capture = probe._bodyview_button_read(hold_s=0.45)
        if len(capture.payload) < 8 or is_placeholder_payload(capture.payload[:128]):
            capture = probe.write_gain_and_read(gain, read_ms=400)

        if not self._ingest_capture(capture.payload, gain):
            if self._last_env is not None:
                self._apply_cached_leds()
                self._state.message = (
                    f"Gain {self._state.gain_index} — hold SEND; "
                    f"{'bar full' if self._state.gain_index >= FULL_BAR_GAIN_INDEX else 'tuning'}."
                )
            else:
                self._state.led_on = EMPTY_LED_ON
                self._state.bracket = False
                self._state.live_mm = None
                if self._state.gain_index > 0:
                    self._state.message = (
                        f"Gain {self._state.gain_index} — hold SEND on gel, then LEDs fill."
                    )
                else:
                    self._state.message = (
                        "Hold SEND on gel, then press + — no LEDs without echo + gain."
                    )

        return self.state()
