"""Scanoprobe session — SEND → ms-rate drain → averaged echo → gain → LEDs."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np

from bodymetrix.bvalgo import envelope_from_payload
from bodymetrix.envelope_avg import (
    MAX_AVERAGE_SAMPLES,
    MISS_TICKS_TO_CLEAR,
    TICK_DRAIN_MS,
    average_envelopes,
)
from bodymetrix.scan_scale import (
    EMPTY_LED_ON,
    LISTEN_GAIN_BYTE,
    ScanScaleState,
    reading_from_echo,
)

if TYPE_CHECKING:
    from bodymetrix.device import BodyMetrixProbe


class BodyMetrixError(RuntimeError):
    pass


class ScanController:
    def __init__(self, probe: BodyMetrixProbe) -> None:
        self._probe = probe
        self._state = ScanScaleState()
        self._last_env: np.ndarray | None = None
        self._env_samples: list[np.ndarray] = []
        self._miss_ticks = 0
        self._pending_new_send = False
        self._last_tick_shots = 0

    def state(self) -> dict[str, Any]:
        out = self._state.to_dict()
        out["has_echo"] = self._last_env is not None
        out["avg_samples"] = len(self._env_samples)
        out["avg_target"] = MAX_AVERAGE_SAMPLES
        out["tick_shots"] = self._last_tick_shots
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

    def _drain_packets(self, gain_byte: int) -> list[bytes]:
        try:
            return self._probe.readbx_multiple_packets(gain_byte, window_ms=TICK_DRAIN_MS)
        except Exception:
            return []

    def _clear_average(self, new_send: bool = False) -> None:
        self._env_samples.clear()
        self._last_env = None
        self._last_tick_shots = 0
        self._miss_ticks = 0
        if new_send:
            self._pending_new_send = True
            self._state.set_slider(0)
            self._state.led_on = EMPTY_LED_ON
            self._state.live_mm = None
            self._state.message = "Hold SEND — move wand in a small circle"

    def _ingest_envelope(self, env: np.ndarray) -> bool:
        self._env_samples.append(env)
        if len(self._env_samples) > MAX_AVERAGE_SAMPLES:
            self._env_samples = self._env_samples[-MAX_AVERAGE_SAMPLES:]
        averaged = average_envelopes(self._env_samples)
        if averaged is None:
            return False
        self._last_env = averaged
        n = len(self._env_samples)
        shots = self._last_tick_shots
        if n < MAX_AVERAGE_SAMPLES:
            self._state.message = (
                f"Averaging {n}/{MAX_AVERAGE_SAMPLES}"
                + (f" ({shots} shots)" if shots else "")
                + " — small circle on skin"
            )
        else:
            self._state.message = "Averaged — tune gain, then HOLD"
        return True

    def _ingest_tick_packets(self, packets: list[bytes]) -> bool:
        """Mean all ms-rate packets from one tick, then add to rolling average."""
        envs: list[np.ndarray] = []
        for payload in packets:
            try:
                envs.append(envelope_from_payload(payload))
            except ValueError:
                continue
        if not envs:
            return False
        frame = average_envelopes(envs)
        if frame is None:
            return False
        self._last_tick_shots = len(envs)
        return self._ingest_envelope(frame)

    def _on_tick_miss(self) -> None:
        self._miss_ticks += 1
        self._last_tick_shots = 0
        if self._miss_ticks >= MISS_TICKS_TO_CLEAR and self._env_samples:
            self._clear_average(new_send=True)

    def _on_tick_hit(self) -> None:
        self._miss_ticks = 0

    def _read_burst(self, gain_byte: int) -> None:
        packets = self._drain_packets(gain_byte)
        if packets:
            self._ingest_tick_packets(packets)

    def _paint(self) -> None:
        """Gain on averaged echo → LEDs + LCD."""
        if self._state.slider <= 0 or self._last_env is None:
            self._state.led_on = EMPTY_LED_ON
            self._state.live_mm = None
            if self._last_env is None and not self._env_samples:
                self._state.message = "Hold SEND — move wand in a small circle"
            return
        reading = reading_from_echo(self._last_env, self._state.slider)
        self._state.led_on = reading.led_on
        self._state.live_mm = reading.mm

    def begin(self, site: int) -> dict[str, Any]:
        self._clear_average(new_send=False)
        self._pending_new_send = False
        self._state = ScanScaleState(
            active=True,
            site=site,
            message="Hold SEND — move wand in a small circle",
        )
        self._usb_ready()
        return self.state()

    def end(self) -> dict[str, Any]:
        self._clear_average(new_send=False)
        self._state = ScanScaleState()
        return self.state()

    def set_slider(
        self, slider: int, read_wand: bool = False, fast: bool = False
    ) -> dict[str, Any]:
        if not self._state.active:
            raise BodyMetrixError("Scan not active.")
        if self._state.locked:
            raise BodyMetrixError("Release HOLD before changing gain.")

        old_gain_index = self._state.gain_index
        self._state.set_slider(slider)
        if self._state.gain_index != old_gain_index:
            self._env_samples.clear()
            self._last_env = None
            self._last_tick_shots = 0

        if self._state.slider <= 0:
            self._state.led_on = EMPTY_LED_ON
            self._state.live_mm = None
            return self.state()

        if not fast and read_wand and self._usb_ready():
            self._read_burst(self._state.gain)

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
            self._state.message = "HOLD released — adjust gain or re-lock"
        else:
            if self._state.live_mm is None:
                raise BodyMetrixError("No reading yet — tune gain on the bar.")
            self._state.locked = True
            self._state.locked_mm = self._state.live_mm
            self._state.message = f"LOCKED {self._state.locked_mm:g} mm"
        return self.state()

    def tick(self) -> dict[str, Any]:
        if not self._state.active or self._state.locked:
            return self.state()

        if self._usb_ready():
            gain_byte = LISTEN_GAIN_BYTE if self._state.slider <= 0 else self._state.gain
            packets = self._drain_packets(gain_byte)
            if packets:
                self._on_tick_hit()
                self._ingest_tick_packets(packets)
            else:
                self._on_tick_miss()

        self._paint()
        return self.state()
