"""Scanoprobe LED scan session — gain amplitude, echo → LEDs, live mm."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import numpy as np

from bodymetrix.bvalgo import envelope_from_payload
from bodymetrix.scan_scale import (
    DEFAULT_GAIN_INDEX,
    EMPTY_LED_ON,
    LISTEN_GAIN_BYTE,
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

    # Gap between good reads while scanning → SEND released, next read = new site.
    NEW_SEND_GAP_SEC = 1.2

    def __init__(self, probe: BodyMetrixProbe) -> None:
        self._probe = probe
        self._state = ScanScaleState()
        self._last_env: np.ndarray | None = None
        self._site_engaged = False
        self._last_good_at: float | None = None
        self._pending_new_send = False

    def state(self) -> dict[str, Any]:
        out = self._state.to_dict()
        out["has_echo"] = self._last_env is not None
        if self._last_env is not None:
            out["envelope"] = [int(x) for x in self._last_env[:600]]
        if self._pending_new_send:
            out["new_send"] = True
            self._pending_new_send = False
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
        self._state.live_mm = reading.mm
        self._state.message = reading_hint(reading)

    def _clear_leds(self) -> None:
        self._state.led_on = EMPTY_LED_ON
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

    def _reset_for_new_send(self) -> None:
        """Fresh SEND press — dark bar, gain 0, ready for new site."""
        self._discard_cached_echo()
        self._state.locked = False
        self._state.locked_mm = None
        self._state.set_slider(0)
        self._clear_leds()
        self._site_engaged = False
        self._last_good_at = None
        self._pending_new_send = True

    def _capture_at_gain(self, gain_byte: int, quick: bool = False) -> bytes:
        self._probe.write_gain(gain_byte)
        hold_s = 0.28 if quick else 0.45
        capture = self._probe._bodyview_button_read(hold_s=hold_s)
        if len(capture.payload) < 8 or is_placeholder_payload(capture.payload[:128]):
            read_ms = 300 if quick else 400
            capture = self._probe.write_gain_and_read(gain_byte, read_ms=read_ms)
        return capture.payload

    def _read_at_gain(self, quick: bool = False, listen: bool = False) -> bool:
        """Read wand echo. listen=True uses mid wand gain while UI gain is 0."""
        if listen:
            gain_byte = LISTEN_GAIN_BYTE
        else:
            gain_byte = self._state.gain
        try:
            payload = self._capture_at_gain(gain_byte, quick=quick)
        except Exception:
            return False
        if len(payload) < 8 or is_placeholder_payload(payload[:128]):
            return False

        now = time.monotonic()
        gap = (now - self._last_good_at) if self._last_good_at else 0.0
        if (
            self._site_engaged
            and self._last_good_at is not None
            and gap >= self.NEW_SEND_GAP_SEC
        ):
            self._reset_for_new_send()

        if self._state.slider > 0:
            self._last_good_at = now

        return self._ingest_capture(payload, gain_byte)

    def _ingest_capture(self, payload: bytes, gain_byte: int) -> bool:
        """Cache envelope; paint bar only when UI gain > 0."""
        reading = scale_reading_from_payload(
            payload,
            gain_byte=gain_byte,
            gain_index=self._state.gain_index,
            slider=self._state.slider,
        )
        if reading is None:
            return False
        try:
            self._last_env = envelope_from_payload(payload)
        except ValueError:
            return False
        if self._state.slider <= 0:
            self._clear_leds()
            return True
        self._apply_reading(reading)
        return True

    def begin(self, site: int) -> dict[str, Any]:
        self._last_env = None
        self._site_engaged = False
        self._last_good_at = None
        self._pending_new_send = False
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
        self._site_engaged = False
        self._last_good_at = None
        self._state = ScanScaleState()
        return self.state()

    def adjust_gain(self, delta: int, read_wand: bool = False) -> dict[str, Any]:
        if not self._state.active:
            raise BodyMetrixError("Scan not active.")
        if self._state.locked:
            raise BodyMetrixError("Release HOLD before changing gain.")
        return self.set_slider(self._state.slider + int(delta), read_wand=read_wand)

    def set_slider(
        self, slider: int, read_wand: bool = False, fast: bool = False
    ) -> dict[str, Any]:
        """Slider sets software gain; LEDs from cached echo. USB only on release/read."""
        if not self._state.active:
            raise BodyMetrixError("Scan not active.")
        if self._state.locked:
            raise BodyMetrixError("Release HOLD before changing gain.")

        self._state.set_slider(slider)
        if self._state.slider > 0:
            self._site_engaged = True

        if self._state.slider <= 0:
            self._clear_leds()
            if not fast and self._probe_usb_ready():
                try:
                    self._probe.write_gain(0)
                except Exception:
                    pass
            return self.state()

        if fast:
            self._apply_echo_leds()
            return self.state()

        usb_ok = self._probe_usb_ready()
        if usb_ok:
            try:
                self._probe.write_gain(self._state.gain)
            except Exception:
                usb_ok = False

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
                    "No mm yet — tune gain until the fascia depth shows on the bar."
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

        if not self._probe_usb_ready():
            if self._state.gain_index > 0:
                self._apply_echo_leds()
            else:
                self._clear_leds()
            return self.state()

        listen = self._state.gain_index <= 0
        self._read_at_gain(quick=True, listen=listen)

        if self._state.gain_index <= 0:
            self._clear_leds()
        else:
            self._apply_echo_leds()
        return self.state()
