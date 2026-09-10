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

    def _discard_cached_echo(self) -> None:
        """Drop last site — never show a previous location after the wand moves."""
        self._last_env = None

    def _clear_live(self, message: str) -> None:
        self._state.led_on = EMPTY_LED_ON
        self._state.bracket = False
        self._state.live_mm = None
        self._state.message = message

    def _apply_cached_leds(self) -> None:
        """Instant dial feedback — re-threshold last echo at the new gain byte."""
        if self._state.gain_index <= 0 or self._last_env is None:
            return
        led_on = leds_for_echo(
            self._last_env,
            self._state.gain,
            self._state.gain_index,
        )
        self._apply_reading(
            reading_from_led_on(led_on, self._state.gain, self._state.gain_index)
        )

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
        """Decode echo → cache envelope + LED bar. Returns True when echo accepted."""
        reading = scale_reading_from_payload(
            payload,
            gain_byte=gain,
            gain_index=self._state.gain_index,
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
            led_on=EMPTY_LED_ON,
            message="Gel + hold SEND on BX wand. No LEDs without gain — press +.",
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
        idx = self._state.gain_index + int(delta)
        return self.set_gain_index(idx, read_wand=read_wand)

    def set_gain_index(self, index: int, read_wand: bool = False) -> dict[str, Any]:
        """Dial gain — instant LED update; optional wand read when dial stops."""
        if not self._state.active:
            raise BodyMetrixError("Scan not active.")
        if self._state.locked:
            raise BodyMetrixError("Release HOLD before changing gain.")

        self._state.gain_index = max(0, min(int(index), len(GAIN_STEPS) - 1))
        if self._state.gain_index <= 0:
            self._discard_cached_echo()
            self._clear_live("Gain 0 — no LEDs. Press + with SEND held.")
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

        refreshed = False
        if read_wand and usb_ok:
            refreshed = self._read_at_gain(quick=True)

        if refreshed:
            pass
        elif self._last_env is not None:
            self._apply_cached_leds()
        else:
            self._clear_live(
                f"GAIN {self._state.gain} — hold SEND on gel."
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

        if self._state.gain_index <= 0:
            self._state.led_on = EMPTY_LED_ON
            self._state.bracket = False
            self._state.live_mm = None
            self._state.message = "Gain 0 — no LEDs. Press + with SEND held."
            return self.state()

        if not self._probe_usb_ready():
            self._discard_cached_echo()
            self._clear_live(
                f"GAIN {self._state.gain_index} — probe not ready."
            )
            return self.state()

        if not self._read_at_gain(quick=False):
            self._discard_cached_echo()
            self._clear_live(
                f"GAIN {self._state.gain_index} — hold SEND on gel (new site)."
            )

        return self.state()
