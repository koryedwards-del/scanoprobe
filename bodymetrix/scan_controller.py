"""Scanoprobe session — SEND → echo cache → gain → LEDs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from bodymetrix.bvalgo import envelope_from_payload
from bodymetrix.scan_scale import (
    EMPTY_LED_ON,
    LISTEN_GAIN_BYTE,
    ScanScaleState,
    reading_from_echo,
)
from bodymetrix.scanoprobe import is_placeholder_payload

if TYPE_CHECKING:
    from bodymetrix.device import BodyMetrixProbe


class BodyMetrixError(RuntimeError):
    pass


class ScanController:
    def __init__(self, probe: BodyMetrixProbe) -> None:
        self._probe = probe
        self._state = ScanScaleState()
        self._last_env = None
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

    def _usb_ready(self) -> bool:
        try:
            self._probe.ensure_session()
            if not self._probe._pipes_configured:
                self._probe.bodyview_init()
            return True
        except Exception:
            return False

    def _read_echo(self, gain_byte: int) -> bytes | None:
        try:
            self._probe.write_gain(gain_byte)
            capture = self._probe._bodyview_button_read(hold_s=0.3)
            payload = capture.payload
            if len(payload) < 8 or is_placeholder_payload(payload[:128]):
                capture = self._probe.write_gain_and_read(gain_byte, read_ms=350)
                payload = capture.payload
            if len(payload) < 8 or is_placeholder_payload(payload[:128]):
                return None
            return payload
        except Exception:
            return None

    def _cache_payload(self, payload: bytes) -> None:
        try:
            self._last_env = envelope_from_payload(payload)
        except ValueError:
            pass

    def _paint(self) -> None:
        """Gain on cached echo → LEDs + LCD."""
        if self._state.slider <= 0 or self._last_env is None:
            self._state.led_on = EMPTY_LED_ON
            self._state.live_mm = None
            return
        reading = reading_from_echo(self._last_env, self._state.slider)
        self._state.led_on = reading.led_on
        self._state.live_mm = reading.mm

    def _reset(self) -> None:
        self._last_env = None
        self._state.locked = False
        self._state.locked_mm = None
        self._state.set_slider(0)
        self._state.led_on = EMPTY_LED_ON
        self._state.live_mm = None
        self._pending_new_send = True

    def begin(self, site: int) -> dict[str, Any]:
        self._last_env = None
        self._pending_new_send = False
        self._state = ScanScaleState(active=True, site=site)
        self._usb_ready()
        return self.state()

    def end(self) -> dict[str, Any]:
        self._last_env = None
        self._state = ScanScaleState()
        return self.state()

    def set_slider(
        self, slider: int, read_wand: bool = False, fast: bool = False
    ) -> dict[str, Any]:
        if not self._state.active:
            raise BodyMetrixError("Scan not active.")
        if self._state.locked:
            raise BodyMetrixError("Release HOLD before changing gain.")

        self._state.set_slider(slider)

        if self._state.slider <= 0:
            self._state.led_on = EMPTY_LED_ON
            self._state.live_mm = None
            return self.state()

        if not fast and read_wand and self._usb_ready():
            payload = self._read_echo(self._state.gain)
            if payload:
                self._cache_payload(payload)

        self._paint()
        return self.state()

    def adjust_gain(self, delta: int, read_wand: bool = False) -> dict[str, Any]:
        return self.set_slider(self._state.slider + int(delta), read_wand=read_wand)

    def set_gain_index(self, index: int, read_wand: bool = False) -> dict[str, Any]:
        from bodymetrix.scan_scale import slider_for_gain_index

        return self.set_slider(slider_for_gain_index(index), read_wand=read_wand)

    def toggle_hold(self) -> dict[str, Any]:
        if not self._state.active:
            raise BodyMetrixError("Scan not active.")
        if self._state.locked:
            self._state.locked = False
            self._state.locked_mm = None
        else:
            if self._state.live_mm is None:
                raise BodyMetrixError("No reading yet — tune gain on the bar.")
            self._state.locked = True
            self._state.locked_mm = self._state.live_mm
        return self.state()

    def tick(self) -> dict[str, Any]:
        if not self._state.active or self._state.locked:
            return self.state()

        if self._usb_ready():
            gain_byte = LISTEN_GAIN_BYTE if self._state.slider <= 0 else self._state.gain
            payload = self._read_echo(gain_byte)
            if payload:
                self._cache_payload(payload)

        self._paint()
        return self.state()
