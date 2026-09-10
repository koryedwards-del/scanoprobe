"""Scanoprobe LED scan session — gain, HOLD lock, live mm (no device.py bloat)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from bodymetrix.bvalgo import envelope_from_payload
from bodymetrix.scan_scale import (
    DEFAULT_GAIN_INDEX,
    GAIN_STEPS,
    ScanScaleState,
    led_mask_for_gain,
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

    def state(self) -> dict[str, Any]:
        return self._state.to_dict()

    def _sync_leds(self, env: Any = None, gain_byte: int | None = None) -> None:
        gain = gain_byte if gain_byte is not None else self._state.gain
        self._state.led_on = led_mask_for_gain(
            self._state.gain_index,
            self._state.peak_gain_index,
            env=env,
            gain_byte=gain,
        )

    def begin(self, site: int) -> dict[str, Any]:
        self._state = ScanScaleState(
            active=True,
            site=site,
            gain_index=DEFAULT_GAIN_INDEX,
            message="Hold SEND on gelled skin, then press + to fill the LED bar.",
        )
        self._probe.ensure_session()
        self._sync_leds()
        return self._state.to_dict()

    def end(self) -> dict[str, Any]:
        self._state = ScanScaleState()
        return self._state.to_dict()

    def adjust_gain(self, delta: int) -> dict[str, Any]:
        if not self._state.active:
            raise BodyMetrixError("Scan not active.")
        if self._state.locked:
            raise BodyMetrixError("Release HOLD before changing gain.")
        idx = self._state.gain_index + int(delta)
        return self.set_gain_index(idx)

    def set_gain_index(self, index: int) -> dict[str, Any]:
        if not self._state.active:
            raise BodyMetrixError("Scan not active.")
        if self._state.locked:
            raise BodyMetrixError("Release HOLD before changing gain.")
        self._state.gain_index = max(0, min(int(index), len(GAIN_STEPS) - 1))
        self._state.peak_gain_index = max(
            self._state.peak_gain_index, self._state.gain_index
        )
        self._sync_leds()
        return self.tick()

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
        return self._state.to_dict()

    def tick(self) -> dict[str, Any]:
        if not self._state.active:
            raise BodyMetrixError("Scan not active.")
        if self._state.locked:
            return self._state.to_dict()

        probe = self._probe
        probe.ensure_session()
        if not probe._pipes_configured:
            probe.bodyview_init()

        gain = self._state.gain
        capture = probe.write_gain_and_read(gain, read_ms=450)
        if len(capture.payload) < 8:
            capture = probe._bodyview_button_read(hold_s=0.35)

        env = None
        reading = scale_reading_from_payload(
            capture.payload,
            gain_byte=gain,
            gain_index=self._state.gain_index,
            peak_gain_index=self._state.peak_gain_index,
        )
        if reading is not None:
            try:
                env = envelope_from_payload(capture.payload)
            except ValueError:
                env = None
            self._state.bracket = reading.bracket
            self._state.live_mm = reading.mm
            self._state.message = reading_hint(reading)
        else:
            self._state.bracket = False
            self._state.live_mm = None
            if is_placeholder_payload(capture.payload):
                self._state.message = (
                    "No wand signal — gel, hold SEND, then press + to fill LEDs."
                )
            else:
                self._state.message = "Press + to fill LEDs, then − to three-LED bracket."

        self._sync_leds(env=env, gain_byte=gain)

        return self._state.to_dict()
