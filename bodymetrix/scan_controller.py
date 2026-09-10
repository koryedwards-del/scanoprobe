"""Scanoprobe LED scan session — gain amplitude, echo → LEDs, live mm."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from bodymetrix.bvalgo import envelope_from_payload
from bodymetrix.scan_scale import (
    DEFAULT_GAIN_INDEX,
    EMPTY_LED_ON,
    GAIN_STEPS,
    ScanScaleState,
    reading_from_echo,
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

    def _apply_reading(self, reading) -> None:
        self._state.led_on = reading.led_on
        self._state.bracket = reading.bracket
        self._state.live_mm = reading.mm
        self._state.message = reading_hint(reading)

    def _clear_leds(self) -> None:
        self._state.led_on = EMPTY_LED_ON
        self._state.bracket = False
        self._state.live_mm = None
        self._state.message = ""

    def _apply_echo_leds(self) -> None:
        """Gain amplitude re-thresholds last echo — LEDs + LCD from echo, not slider."""
        if self._state.gain_index <= 0:
            self._clear_leds()
            return
        if self._last_env is None:
            self._clear_leds()
            return
        self._apply_reading(
            reading_from_echo(
                self._last_env,
                self._state.gain,
                self._state.gain_index,
                self._state.slider,
            )
        )

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
        """Decode echo at this gain → cache envelope + LED bar."""
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
        self._apply_reading(reading)
        return True

    def begin(self, site: int) -> dict[str, Any]:
        self._last_env = None
        self._state = ScanScaleState(
            active=True,
            site=site,
            gain_index=DEFAULT_GAIN_INDEX,
            slider=0,
            led_on=EMPTY_LED_ON,
            message="",
        )
        self._probe_usb_ready()
        return self.state()

    def end(self) -> dict[str, Any]:
        self._last_env = None
        self._state = ScanScaleState()
        return self.state()

    def clear_reading(self) -> dict[str, Any]:
        """Clear echo + bar for a retest; stay on the same site."""
        if not self._state.active:
            raise BodyMetrixError("Scan not active.")
        self._discard_cached_echo()
        self._state.locked = False
        self._state.locked_mm = None
        self._state.set_slider(0)
        self._clear_leds()
        if self._probe_usb_ready():
            try:
                self._probe.write_gain(0)
            except Exception:
                pass
        return self.state()

    def adjust_gain(self, delta: int, read_wand: bool = False) -> dict[str, Any]:
        if not self._state.active:
            raise BodyMetrixError("Scan not active.")
        if self._state.locked:
            raise BodyMetrixError("Release HOLD before changing gain.")
        return self.set_slider(self._state.slider + int(delta), read_wand=read_wand)

    def set_slider(self, slider: int, read_wand: bool = False) -> dict[str, Any]:
        """Slider sets wand gain amplitude; LEDs come from echo at that gain."""
        if not self._state.active:
            raise BodyMetrixError("Scan not active.")
        if self._state.locked:
            raise BodyMetrixError("Release HOLD before changing gain.")

        self._state.set_slider(slider)

        if self._state.slider <= 0:
            self._discard_cached_echo()
            self._clear_leds()
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

        # Re-threshold cached echo at new gain; read wand when asked or no cache yet.
        if usb_ok and (read_wand or self._last_env is None):
            self._read_at_gain(quick=True)
        self._apply_echo_leds()
        return self.state()

    def set_gain_index(self, index: int, read_wand: bool = False) -> dict[str, Any]:
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
            self._state.message = ""
        else:
            if self._state.live_mm is None:
                raise BodyMetrixError(
                    "No mm yet — tune gain until three fat LEDs show the fascia border."
                )
            self._state.locked = True
            self._state.locked_mm = self._state.live_mm
            self._state.message = ""
        return self.state()

    def tick(self) -> dict[str, Any]:
        if not self._state.active:
            raise BodyMetrixError("Scan not active.")
        if self._state.locked:
            return self.state()

        # Gain at 0 — dark screen; SEND alone does not display anything.
        if self._state.gain_index <= 0:
            self._clear_leds()
            return self.state()

        if not self._probe_usb_ready():
            self._apply_echo_leds()
            return self.state()

        # Best-effort refresh; keep last good echo if SEND drops briefly.
        self._read_at_gain(quick=False)
        self._apply_echo_leds()
        return self.state()
