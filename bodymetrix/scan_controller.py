"""Scanoprobe LED scan session — gain, HOLD lock, live mm (no device.py bloat)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from bodymetrix.bvalgo import envelope_from_payload
from bodymetrix.scan_scale import (
    DEFAULT_GAIN_INDEX,
    EMPTY_LED_ON,
    GAIN_STEPS,
    ScanScaleState,
    leds_for_slider,
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

    def _probe_usb_ready(self) -> bool:
        """Best-effort USB — gain must still update if the wand is unplugged."""
        try:
            self._probe.ensure_session()
            if not self._probe._pipes_configured:
                self._probe.bodyview_init()
            return True
        except Exception:
            return False

    def _apply_slider_leds(self) -> None:
        """Slider 0–50 directly sets how many LEDs are lit."""
        led_on = leds_for_slider(self._state.slider)
        reading = reading_from_led_on(
            led_on,
            self._state.gain,
            self._state.gain_index,
            self._last_env,
            slider=self._state.slider,
        )
        self._state.led_on = reading.led_on
        self._state.bracket = reading.bracket
        self._state.live_mm = reading.mm
        self._state.message = reading_hint(reading)

    def _discard_cached_echo(self) -> None:
        """Drop last site — never show a previous location after the wand moves."""
        self._last_env = None

    def _capture_at_gain(self, quick: bool = False) -> bytes:
        gain = self._state.gain
        self._probe.write_gain(gain)
        hold_s = 0.28 if quick else 0.45
        capture = self._probe._bodyview_button_read(hold_s=hold_s)
        if len(capture.payload) < 8 or is_placeholder_payload(capture.payload[:128]):
            read_ms = 300 if quick else 400
            capture = self._probe.write_gain_and_read(gain, read_ms=read_ms)
        return capture.payload

    def _read_at_gain(self, quick: bool = False) -> bool:
        """Read wand echo at the current gain (packet shape depends on gain byte)."""
        gain = self._state.gain
        try:
            payload = self._capture_at_gain(quick=quick)
        except Exception:
            return False
        if len(payload) < 8 or is_placeholder_payload(payload[:128]):
            return False
        return self._ingest_capture(payload, gain)

    def _ingest_capture(self, payload: bytes, gain: int) -> bool:
        """Decode echo → cache envelope; LEDs stay on slider count."""
        reading = scale_reading_from_payload(
            payload,
            gain_byte=gain,
            gain_index=self._state.gain_index,
            slider=self._state.slider,
        )
        if reading is None:
            return False
        try:
            self._last_env = envelope_from_payload(payload)
        except ValueError:
            return False
        self._state.bracket = reading.bracket
        self._state.live_mm = reading.mm
        self._apply_slider_leds()
        return True

    def begin(self, site: int) -> dict[str, Any]:
        self._last_env = None
        self._state = ScanScaleState(
            active=True,
            site=site,
            gain_index=DEFAULT_GAIN_INDEX,
            slider=0,
            led_on=EMPTY_LED_ON,
            message="Gel + hold SEND on BX wand. Slide right to light LEDs.",
        )
        self._probe_usb_ready()
        return self.state()

    def end(self) -> dict[str, Any]:
        self._last_env = None
        self._state = ScanScaleState()
        return self.state()

    def adjust_gain(self, delta: int, read_wand: bool = False) -> dict[str, Any]:
        if not self._state.active:
            raise BodyMetrixError("Scan not active.")
        if self._state.locked:
            raise BodyMetrixError("Release HOLD before changing gain.")
        return self.set_slider(self._state.slider + int(delta), read_wand=read_wand)

    def set_slider(self, slider: int, read_wand: bool = False) -> dict[str, Any]:
        """Slider 0–50 — that many LEDs light from the left."""
        if not self._state.active:
            raise BodyMetrixError("Scan not active.")
        if self._state.locked:
            raise BodyMetrixError("Release HOLD before changing gain.")

        self._state.set_slider(slider)
        self._apply_slider_leds()

        if self._state.slider <= 0:
            self._discard_cached_echo()
            if self._probe_usb_ready():
                try:
                    self._probe.write_gain(0)
                except Exception:
                    pass
            return self.state()

        usb_ok = self._probe_usb_ready()
        if usb_ok:
            try:
                self._probe.write_gain(self._state.gain)
            except Exception:
                usb_ok = False

        if read_wand and usb_ok:
            if not self._read_at_gain(quick=True):
                self._discard_cached_echo()
                self._apply_slider_leds()

        return self.state()

    def set_gain_index(self, index: int, read_wand: bool = False) -> dict[str, Any]:
        """Set wand gain index; slider follows."""
        if not self._state.active:
            raise BodyMetrixError("Scan not active.")
        if self._state.locked:
            raise BodyMetrixError("Release HOLD before changing gain.")
        self._state.set_gain_index(index)
        return self.set_slider(self._state.slider, read_wand=read_wand)

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
                    "No mm yet — dial gain until three fat LEDs show, then HOLD."
                )
            self._state.locked = True
            self._state.locked_mm = self._state.live_mm
            self._state.message = (
                f"LOCKED {self._state.locked_mm:g} mm — release HOLD for a new site."
            )
        return self.state()

    def tick(self) -> dict[str, Any]:
        if not self._state.active:
            raise BodyMetrixError("Scan not active.")
        if self._state.locked:
            return self.state()

        self._apply_slider_leds()

        if self._state.slider <= 0:
            return self.state()

        if not self._probe_usb_ready():
            self._discard_cached_echo()
            return self.state()

        if not self._read_at_gain(quick=False):
            self._discard_cached_echo()
            self._apply_slider_leds()

        return self.state()
