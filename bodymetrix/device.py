"""USB communication with BodyMetrix handheld probe (04D8:FBB7)."""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bodymetrix.scan_scale import (
    DEFAULT_GAIN_INDEX,
    GAIN_STEPS,
    ScanScaleState,
    scale_mm_from_payload,
)
from bodymetrix.scanoprobe import (
    DEFAULT_SAMPLE_RATES_HZ,
    ScanoprobeResult,
    echo_to_thickness_mm,
    is_placeholder_payload,
    payload_quality,
)

VENDOR_ID = 0x04D8
PRODUCT_ID = 0xFBB7
DEFAULT_SAMPLE_RATE_HZ = 33_300_000
MEASUREMENT_MODE_SCANOPROBE = "scanoprobe"
MEASUREMENT_MODE_BODYVIEW = "bodyview"


@dataclass
class DeviceStatus:
    connected: bool
    mode: str
    message: str
    vendor_id: str
    product_id: str


@dataclass
class CaptureResult:
    payload: bytes
    method: str
    endpoint: str = ""
    notes: list[str] = field(default_factory=list)


@dataclass
class MeasurementResult:
    mm: float
    source: str
    method: str
    confidence: float
    bytes_received: int


class BodyMetrixError(RuntimeError):
    pass


def _import_usb():
    try:
        import usb.core
        import usb.util
    except ImportError as exc:
        raise BodyMetrixError(
            "pyusb is not installed. Run: pip install -r requirements.txt"
        ) from exc
    return usb.core, usb.util


_usb_backend: Any = None


def _get_usb_backend() -> Any:
    global _usb_backend
    if _usb_backend is not None:
        return _usb_backend

    import usb.backend.libusb1

    backend = usb.backend.libusb1.get_backend()
    if backend is not None:
        _usb_backend = backend
        return backend

    try:
        import libusb_package

        for finder in (
            getattr(libusb_package, "get_library_path", None),
            getattr(libusb_package, "find_library", None),
        ):
            if finder is None:
                continue
            try:
                lib_path = finder()
            except TypeError:
                lib_path = finder("usb-1.0")  # type: ignore[misc]
            if not lib_path:
                continue
            backend = usb.backend.libusb1.get_backend(find_library=lambda _: lib_path)
            if backend is not None:
                _usb_backend = backend
                return backend
    except Exception:  # noqa: BLE001
        pass

    try:
        import ctypes.util

        lib_path = ctypes.util.find_library("usb-1.0")
        if lib_path:
            backend = usb.backend.libusb1.get_backend(find_library=lambda _: lib_path)
            if backend is not None:
                _usb_backend = backend
                return backend
    except Exception:  # noqa: BLE001
        pass

    if sys.platform == "darwin":
        for path in (
            "/opt/homebrew/lib/libusb-1.0.dylib",
            "/usr/local/lib/libusb-1.0.dylib",
        ):
            if os.path.exists(path):
                backend = usb.backend.libusb1.get_backend(find_library=lambda _: path)
                if backend is not None:
                    _usb_backend = backend
                    return backend

    raise BodyMetrixError(
        "USB driver missing. In Terminal run: cd ~/scanoprobe && ./fix-usb.sh"
    )


def _find_device(vendor_id: int, product_id: int) -> Any:
    usb_core, _ = _import_usb()
    backend = _get_usb_backend()
    return usb_core.find(idVendor=vendor_id, idProduct=product_id, backend=backend)


def _usb_error_message(exc: Exception) -> str:
    text = str(exc)
    if "No backend available" in text:
        return (
            "USB driver missing. In Terminal run: "
            "cd ~/scanoprobe && ./install.sh then restart the app."
        )
    return f"USB scan failed: {text}"


class BodyMetrixProbe:
    """Scanoprobe-style USB: open link, wait for SEND, decode echo in our code."""

    def __init__(
        self,
        vendor_id: int = VENDOR_ID,
        product_id: int = PRODUCT_ID,
        sound_speed_m_s: float = 1540.0,
        sample_rate_hz: float = DEFAULT_SAMPLE_RATE_HZ,
        measurement_mode: str = MEASUREMENT_MODE_SCANOPROBE,
        sample_rates_hz: tuple[float, ...] | None = None,
    ) -> None:
        self.vendor_id = vendor_id
        self.product_id = product_id
        self.sound_speed_m_s = sound_speed_m_s
        self.sample_rate_hz = sample_rate_hz
        self.measurement_mode = measurement_mode
        self.sample_rates_hz = sample_rates_hz or DEFAULT_SAMPLE_RATES_HZ
        self._device: Any = None
        self._read_endpoints: list[Any] = []
        self._write_endpoints: list[Any] = []
        self._session_open = False
        self._session_notes: list[str] = []
        self._pipes_configured = False
        self._write_timeout_ms = 20
        self._read_timeout_ms = 50
        self._bodyview_connected = False
        self._scan = ScanScaleState()

    def status(self) -> DeviceStatus:
        try:
            device = _find_device(self.vendor_id, self.product_id)
        except Exception as exc:  # noqa: BLE001
            return DeviceStatus(
                connected=False,
                mode="error",
                message=_usb_error_message(exc),
                vendor_id=f"0x{self.vendor_id:04X}",
                product_id=f"0x{self.product_id:04X}",
            )
        if device is None:
            return DeviceStatus(
                connected=False,
                mode="disconnected",
                message="Probe not found. Plug in the BodyMetrix wand via USB.",
                vendor_id=f"0x{self.vendor_id:04X}",
                product_id=f"0x{self.product_id:04X}",
            )
        return DeviceStatus(
            connected=True,
            mode="idle",
            message="Probe ready — gel, place on skin, press SEND on wand",
            vendor_id=f"0x{self.vendor_id:04X}",
            product_id=f"0x{self.product_id:04X}",
        )

    def connect(self) -> None:
        _, usb_util = _import_usb()
        device = _find_device(self.vendor_id, self.product_id)
        if device is None:
            raise BodyMetrixError(
                f"Probe not found ({self.vendor_id:04X}:{self.product_id:04X}). "
                "Plug in USB and run: python3 scripts/probe_usb.py status"
            )

        try:
            if device.is_kernel_driver_active(0):
                device.detach_kernel_driver(0)
        except (NotImplementedError, Exception):  # noqa: BLE001
            pass

        try:
            device.set_configuration()
        except Exception:  # noqa: BLE001
            pass

        cfg = device.get_active_configuration()
        self._read_endpoints = []
        self._write_endpoints = []
        for intf in cfg:
            try:
                usb_util.claim_interface(device, intf)
            except Exception:  # noqa: BLE001
                continue
            for ep in intf:
                if usb_util.endpoint_direction(ep.bEndpointAddress) == usb_util.ENDPOINT_IN:
                    self._read_endpoints.append(ep)
                else:
                    self._write_endpoints.append(ep)
        self._device = device
        self._session_open = True
        self._open_session()

    def _bodyview_configure_pipes(
        self, write_timeout_ms: int = 20, read_timeout_ms: int = 50
    ) -> list[str]:
        """
        Mirror IOKit SetPipeProperties from readinInfoString / _bxbuttonPressed:
        pipe=1, type=2 (bulk), timeouts 0x14 (20) and 0x32 (50) ms.
        """
        if self._device is None:
            return []
        _, usb_util = _import_usb()
        notes: list[str] = []
        for ep in self._read_endpoints + self._write_endpoints:
            addr = ep.bEndpointAddress
            try:
                usb_util.clear_halt(self._device, addr)
                notes.append(f"clear_halt 0x{addr:02X}")
            except Exception:  # noqa: BLE001
                continue
        # Success path in disasm: two pipe ops (esi=2 then esi=1) before I/O.
        for addr in (0x02, 0x01, 0x82, 0x81):
            try:
                usb_util.clear_halt(self._device, addr)
            except Exception:  # noqa: BLE001
                pass
        self._write_timeout_ms = write_timeout_ms
        self._read_timeout_ms = read_timeout_ms
        self._pipes_configured = True
        return notes

    def bodyview_init(self) -> dict[str, Any]:
        """Full BodyView arm sequence: configure pipes → readinInfoString → connected."""
        if self._device is None:
            self.connect()
        notes = self._bodyview_configure_pipes(20, 50)
        # Disasm success path: pipe setup OK → connected=1 (no 128-byte read required).
        if self._pipes_configured:
            self._bodyview_connected = True
            notes.append("pipe setup OK → connected=1 (BodyView success path)")
        info = self._bodyview_read_info_string()
        notes.extend(info.notes)
        if len(info.payload) >= 6:
            self._bodyview_connected = True
        return {
            "pipes_configured": self._pipes_configured,
            "connected": self._bodyview_connected,
            "info_bytes": len(info.payload),
            "info_hex": info.payload[:64].hex() if info.payload else "",
            "notes": notes,
        }

    def bodyview_diagnose(self) -> dict[str, Any]:
        """Probe every init read path — for debugging 0-byte info string."""
        if self._device is None:
            self.connect()
        self._bodyview_configure_pipes(20, 50)
        if self._pipes_configured:
            self._bodyview_connected = True
        hits: list[dict[str, Any]] = []

        def record(label: str, data: bytes) -> None:
            if data:
                hits.append({"path": label, "bytes": len(data), "hex": data[:48].hex()})

        for out_label, out_payload in (
            ("bulk IN (no OUT)", None),
            ("OUT 01 → IN", b"\x01"),
            ("OUT 02 → IN", b"\x02"),
            ("OUT a001 → IN", b"\xa0\x01"),
            ("OUT 00 → IN", b"\x00"),
        ):
            if out_payload is not None:
                for ep in self._write_endpoints:
                    try:
                        ep.write(out_payload, self._write_timeout_ms)
                    except Exception:  # noqa: BLE001
                        pass
                time.sleep(0.03)
            record(out_label, self._read_bulk_up_to(0x80, 200))

        for req_type, req, val, idx in (
            (0xC0, 0x01, 0x0300, 0),
            (0xC0, 0x02, 0x0300, 0),
            (0xC0, 0x03, 0x0300, 0),
            (0x80, 0x06, 0x0300, 0),
            (0x80, 0x06, 0x0303, 0x0409),
            (0xC0, 0x01, 0, 0),
            (0xC0, 0x01, 0, 0x0300),
        ):
            try:
                data = bytes(
                    self._device.ctrl_transfer(req_type, req, val, idx, 0x80, 250)
                )
            except Exception:  # noqa: BLE001
                continue
            record(f"ctrl {req_type:02X}/{req:02X} v={val:04X} i={idx:04X}", data)

        for r in self._try_control_reads():
            record(f"ctrl scan {r.endpoint}", r.payload)

        return {
            "pipes_configured": self._pipes_configured,
            "connected": self._bodyview_connected,
            "hits": hits,
        }

    def _open_session(self) -> None:
        """Mirror BodyView initDevice + readinInfoString — arm wand on connect."""
        if self._device is None:
            return
        init = self.bodyview_init()
        self._session_notes = init["notes"]
        if init["info_bytes"] >= 6:
            self._session_notes.append(
                f"readinInfoString: {init['info_bytes']} bytes {init['info_hex'][:32]}"
            )

    def _bodyview_read_info_string(self) -> CaptureResult:
        """
        From disasm 0x10002d401: IOKit ReadPipe (bulk), up to 0x80 bytes.
        wValue 0x0300 is stored in a local buffer for IOKit — not a USB ctrl wValue.
        """
        if self._device is None:
            return CaptureResult(payload=b"", method="none")
        notes: list[str] = []
        timeout_pairs = ((20, 50), (100, 100))

        for write_ms, read_ms in timeout_pairs:
            self._write_timeout_ms = write_ms
            self._read_timeout_ms = read_ms
            if write_ms == 100:
                self._bodyview_configure_pipes(100, 100)
                notes.append("retry pipe timeouts 100/100ms")

            for label, out_payload in (
                ("bulk IN", None),
                ("OUT 01", b"\x01"),
                ("OUT 02", b"\x02"),
            ):
                if out_payload is not None:
                    for ep in self._write_endpoints:
                        try:
                            ep.write(out_payload, write_ms)
                        except Exception:  # noqa: BLE001
                            continue
                    time.sleep(0.03)
                data = self._read_bulk_up_to(0x80, read_ms + 100)
                if data:
                    notes.append(f"{label} ({write_ms}/{read_ms}ms): {data[:24].hex()}")
                    return CaptureResult(data, "readinInfoString", notes=notes)

            for req_type, req, val, idx in (
                (0xC0, 0x01, 0x0300, 0),
                (0xC0, 0x02, 0x0300, 0),
                (0xC0, 0x03, 0x0300, 0),
                (0x80, 0x06, 0x0300, 0),
                (0xC0, 0x01, 0, 0x0300),
            ):
                try:
                    data = bytes(
                        self._device.ctrl_transfer(req_type, req, val, idx, 0x80, read_ms + 50)
                    )
                except Exception:  # noqa: BLE001
                    continue
                if data:
                    notes.append(
                        f"ctrl {req_type:02X}/{req:02X} val={val:04X} "
                        f"({write_ms}/{read_ms}ms): {data[:24].hex()}"
                    )
                    return CaptureResult(data, "readinInfoString", notes=notes)

        return CaptureResult(payload=b"", method="readinInfoString", notes=notes)

    def _read_bulk_up_to(self, max_bytes: int = 2048, timeout_ms: int = 500) -> bytes:
        chunks: list[bytes] = []
        for ep in self._read_endpoints:
            remaining = max_bytes
            while remaining > 0:
                try:
                    chunk = ep.read(min(remaining, ep.wMaxPacketSize * 32), timeout_ms)
                    if not chunk:
                        break
                    data = bytes(chunk)
                    chunks.append(data)
                    remaining -= len(data)
                except Exception:  # noqa: BLE001
                    break
        return b"".join(chunks)

    def _bodyview_button_read(self, hold_s: float = 0.0) -> CaptureResult:
        """From disasm _bxbuttonPressed: pipe setup, OUT 0xA0 0x01, read up to 0x800."""
        if self._device is None:
            self.connect()
        if not self._pipes_configured:
            self._bodyview_configure_pipes(20, 50)
        if not self._bodyview_connected:
            self._bodyview_read_info_string()

        payload = b"\xa0\x01"
        write_ms = self._write_timeout_ms
        read_ms = max(self._read_timeout_ms, 500)
        best = b""
        best_q = 0.0
        deadline = time.time() + (hold_s if hold_s > 0 else 0.6)

        while time.time() < deadline:
            for ep in self._write_endpoints:
                try:
                    ep.write(payload, write_ms)
                except Exception:  # noqa: BLE001
                    continue
            time.sleep(0.05)
            data = self._read_bulk_up_to(0x800, read_ms)
            if not data:
                continue
            q = payload_quality(data)
            if q > best_q or (q == best_q and len(data) > len(best)):
                best = data
                best_q = q
            if best_q >= 0.35 and len(best) >= 32:
                break

        notes = [
            f"OUT {payload.hex()} → {len(best)} bytes "
            f"(hold={hold_s:.0f}s quality={best_q:.2f})"
        ]
        if best and is_placeholder_payload(best):
            notes.append("warning: best packet still looks like padding — hold SEND on gelled skin")

        return CaptureResult(
            payload=best,
            method="bxbuttonPressed",
            notes=notes,
        )

    def write_gain(self, gain: int) -> None:
        """Send gain byte to wand (BodyView writebxGainandRead step 1)."""
        if self._device is None:
            self.connect()
        if not self._pipes_configured:
            self._bodyview_configure_pipes(20, 50)
        gain_out = bytes([gain & 0xFF])
        for ep in self._write_endpoints:
            try:
                ep.write(gain_out, self._write_timeout_ms)
            except Exception:  # noqa: BLE001
                continue

    def write_gain_and_read(self, gain: int, read_ms: int = 500) -> CaptureResult:
        """BodyView writebxGainandRead: OUT gain byte, then OUT a001 while SEND held."""
        if self._device is None:
            self.connect()
        if not self._pipes_configured:
            self._bodyview_configure_pipes(20, 50)

        gain_out = bytes([gain & 0xFF])
        trigger = b"\xa0\x01"
        write_ms = self._write_timeout_ms
        read_one_ms = max(self._read_timeout_ms, 200)
        deadline = time.time() + read_ms / 1000.0
        best = b""
        best_q = 0.0

        self.write_gain(gain)
        time.sleep(0.03)

        while time.time() < deadline:
            for ep in self._write_endpoints:
                try:
                    ep.write(trigger, write_ms)
                except Exception:  # noqa: BLE001
                    continue
            time.sleep(0.05)
            data = self._read_bulk_up_to(0x800, read_one_ms)
            if not data:
                continue
            q = payload_quality(data)
            if q > best_q or (q == best_q and len(data) > len(best)):
                best = data
                best_q = q
            if best_q >= 0.35 and len(best) >= 32:
                break

        notes = [
            f"gain={gain} OUT {gain_out.hex()} + {trigger.hex()} "
            f"→ {len(best)} bytes (q={best_q:.2f})"
        ]
        if best and is_placeholder_payload(best):
            notes.append("warning: padding — hold SEND on gelled skin")

        return CaptureResult(
            payload=best,
            method="writebxGainandRead",
            notes=notes,
        )

    def try_bodyview_gain_scan(self) -> list[dict[str, Any]]:
        """Try BodyView gain values; user holds SEND on skin during scan."""
        if self._device is None:
            self.connect()

        # Common gain steps — BodyView uses defaultgain (uchar) + deviceGainOffset.
        gains = list(range(0, 16)) + [32, 48, 64, 96, 128, 160, 192, 255]
        hits: list[dict[str, Any]] = []

        for gain in gains:
            result = self.write_gain_and_read(gain, read_ms=500)
            if len(result.payload) >= 8:
                hits.append(
                    {
                        "gain": gain,
                        "bytes": len(result.payload),
                        "hex": result.payload[:48].hex(),
                        "endpoint": result.endpoint,
                    }
                )
            if hits and hits[-1]["bytes"] >= 32:
                break
        return hits

    def disconnect(self) -> None:
        if self._device is not None:
            try:
                import usb.util

                usb.util.release_interface(self._device, 0)
            except Exception:  # noqa: BLE001
                pass
        self._device = None
        self._read_endpoints = []
        self._write_endpoints = []
        self._session_open = False

    def ensure_session(self) -> None:
        """Keep USB open between measurements (Scanoprobe-style session)."""
        if not self._session_open or self._device is None:
            self.connect()

    def _trigger_writes(self) -> None:
        for ep in self._write_endpoints:
            for payload in (b"\x01", b"\x00", b"\x02", b"MEAS", b"\xff"):
                try:
                    ep.write(payload, 200)
                except Exception:  # noqa: BLE001
                    continue

    def _try_control_writes(self) -> None:
        """Best-effort host init — BodyView likely sent something like this first."""
        if self._device is None:
            return
        payloads = (
            b"",
            b"\x01",
            b"\x02",
            b"\x00",
            b"MEAS",
            b"SCAN",
            b"START",
            bytes([0xFF]),
            bytes(range(16)),
        )
        for request in range(0, 32):
            for value in (0, 1, 2, 0xFF):
                for payload in payloads:
                    try:
                        self._device.ctrl_transfer(0x40, request, value, 0, payload, 200)
                    except Exception:  # noqa: BLE001
                        continue

    def dump_usb(self) -> dict[str, Any]:
        """Full USB descriptor dump for protocol research."""
        if self._device is None:
            self.connect()
        assert self._device is not None
        dev = self._device
        out: dict[str, Any] = {
            "manufacturer": self._usb_descriptor_str(dev, "manufacturer"),
            "product": self._usb_descriptor_str(dev, "product"),
            "serial": self._usb_descriptor_str(dev, "serial_number"),
            "configurations": [],
        }
        for cfg in dev:
            cfg_info: dict[str, Any] = {
                "value": cfg.bConfigurationValue,
                "interfaces": [],
            }
            for intf in cfg:
                intf_info: dict[str, Any] = {
                    "number": intf.bInterfaceNumber,
                    "class": intf.bInterfaceClass,
                    "subclass": intf.bInterfaceSubClass,
                    "protocol": intf.bInterfaceProtocol,
                    "endpoints": [],
                }
                for ep in intf:
                    intf_info["endpoints"].append(
                        {
                            "address": f"0x{ep.bEndpointAddress:02X}",
                            "direction": "IN" if ep.bEndpointAddress & 0x80 else "OUT",
                            "type": ep.bmAttributes & 0x03,
                            "max_packet": ep.wMaxPacketSize,
                        }
                    )
                cfg_info["interfaces"].append(intf_info)
            out["configurations"].append(cfg_info)
        return out

    def hunt_wand(self, listen_ms: int = 350) -> list[dict[str, Any]]:
        """
        Discover what OUT command makes the wand send on bulk IN.
        User: gel, skin, hold SEND for the whole run (~45s).
        """
        if self._device is None:
            self.connect()

        hits: list[dict[str, Any]] = []
        payloads: list[bytes] = [bytes([n]) for n in range(256)]
        payloads.extend(
            [
                b"\x01\x00",
                b"\x00\x01",
                b"\x02\x00",
                b"\x03\x00",
                b"MEAS",
                b"SCAN",
                b"START",
                b"READ",
                b"SEND",
                bytes(range(8)),
                bytes(range(16)),
            ]
        )

        for idx, payload in enumerate(payloads):
            for ep in self._write_endpoints:
                try:
                    ep.write(payload, 150)
                except Exception:  # noqa: BLE001
                    continue
            time.sleep(0.04)
            for r in self._read_endpoint_for(listen_ms):
                if len(r.payload) >= 8:
                    hits.append(
                        {
                            "out_hex": payload.hex(),
                            "in_bytes": len(r.payload),
                            "in_hex": r.payload[:48].hex(),
                            "endpoint": r.endpoint,
                        }
                    )
            if hits and len(hits[-1]["in_bytes"]) >= 32:
                break

        return hits

    def passive_listen(self, duration_s: float = 60.0) -> CaptureResult:
        """
        Minimal arm, then only listen on bulk IN — no OUT spam.
        Press SEND on gelled skin anytime during the window.
        """
        if self._device is None:
            self.connect()

        _, usb_util = _import_usb()
        for ep in self._read_endpoints:
            try:
                usb_util.clear_halt(self._device, ep.bEndpointAddress)
            except Exception:  # noqa: BLE001
                pass

        if self._write_endpoints:
            try:
                self._write_endpoints[0].write(b"\x01", 200)
            except Exception:  # noqa: BLE001
                pass

        best = CaptureResult(payload=b"", method="none")
        notes = ["passive listen — press SEND anytime…"]
        deadline = time.time() + duration_s
        chunks: list[bytes] = []

        while time.time() < deadline:
            for hit in self._read_endpoint_for(600, accumulate=True):
                notes.append(f"IN {hit.endpoint}: +{len(hit.payload)}")
                chunks.append(hit.payload)
                combined = b"".join(chunks)
                if len(combined) > len(best.payload):
                    best = CaptureResult(
                        payload=combined,
                        method="passive IN",
                        endpoint=hit.endpoint,
                    )
            for hit in self._try_control_reads():
                if len(hit.payload) > len(best.payload):
                    best = hit
                    notes.append(f"ctrl {hit.endpoint}: {hit.payload.hex()}")

        best.notes = notes
        if not best.payload:
            raise BodyMetrixError(
                f"No data in {duration_s:.0f}s passive listen. "
                f"Tried hub path — if you have a USB-C → USB-A adapter, try Mac direct."
            )
        return best

    def brute_init(self) -> list[dict[str, Any]]:
        """Try common init patterns; return any non-empty reads."""
        if self._device is None:
            self.connect()
        hits: list[dict[str, Any]] = []

        sequences = [
            (0x40, 0x01, 0, 0, b"\x01"),
            (0x40, 0x01, 0, 0, b"\x00"),
            (0x40, 0x02, 0, 0, b""),
            (0x40, 0x03, 0, 0, b"\x01"),
            (0x40, 0x0A, 0, 0, b"MEAS"),
            (0x40, 0x0B, 0, 0, b"SCAN"),
            (0x21, 0x09, 0x0200, 0, b"\x01"),
            (0x21, 0x09, 0x0300, 0, b"\x01"),
        ]
        for req_type, req, value, index, data in sequences:
            try:
                self._device.ctrl_transfer(req_type, req, value, index, data, 500)
            except Exception:  # noqa: BLE001
                pass
            for r in self._read_endpoint_for(300):
                hits.append(
                    {
                        "init": f"ctrl {req_type:02X}/{req:02X} val={value} idx={index}",
                        "length": len(r.payload),
                        "hex": r.payload[:48].hex(),
                    }
                )
            for r in self._try_control_reads():
                hits.append(
                    {
                        "init": f"ctrl {req_type:02X}/{req:02X} val={value}",
                        "length": len(r.payload),
                        "hex": r.payload[:48].hex(),
                    }
                )
        return hits

    def _wake_device(self) -> None:
        if self._device is None:
            return
        # Do not USB-reset — can clear probe state BodyView may have established.
        self._try_control_writes()
        self._trigger_writes()

    def _read_endpoint_for(self, ms: int, accumulate: bool = False) -> list[CaptureResult]:
        results: list[CaptureResult] = []
        for ep in self._read_endpoints:
            chunks: list[bytes] = []
            deadline = time.time() + ms / 1000.0
            while time.time() < deadline:
                try:
                    data = ep.read(ep.wMaxPacketSize, max(200, int((deadline - time.time()) * 1000)))
                    if data:
                        chunks.append(bytes(data))
                        if not accumulate:
                            break
                except Exception:  # noqa: BLE001
                    if chunks:
                        break
                    time.sleep(0.02)
            if chunks:
                payload = b"".join(chunks)
                results.append(
                    CaptureResult(
                        payload=payload,
                        method="bulk/interrupt IN",
                        endpoint=f"0x{ep.bEndpointAddress:02X}",
                    )
                )
        return results

    def _collect_stream(self, duration_s: float) -> CaptureResult:
        """Gather every USB chunk while SEND is held — one echo burst."""
        best = CaptureResult(payload=b"", method="none")
        notes: list[str] = []
        deadline = time.time() + duration_s
        all_chunks: list[bytes] = []

        while time.time() < deadline:
            for hit in self._read_endpoint_for(400, accumulate=True):
                notes.append(f"stream {hit.endpoint}: +{len(hit.payload)} bytes")
                all_chunks.append(hit.payload)
                combined = b"".join(all_chunks)
                if len(combined) > len(best.payload):
                    best = CaptureResult(
                        payload=combined,
                        method="SEND stream",
                        endpoint=hit.endpoint,
                    )
            for hit in self._try_control_reads():
                notes.append(f"ctrl {hit.endpoint}: {len(hit.payload)} bytes")
                if len(hit.payload) > len(best.payload):
                    best = hit
            if best.payload and time.time() + 0.4 < deadline:
                # Brief tail read after first burst (multi-packet A-scan).
                time.sleep(0.15)
                for hit in self._read_endpoint_for(300, accumulate=True):
                    all_chunks.append(hit.payload)
                    combined = b"".join(all_chunks)
                    if len(combined) > len(best.payload):
                        best = CaptureResult(
                            payload=combined,
                            method="SEND stream",
                            endpoint=hit.endpoint,
                        )
                break

        best.notes = notes
        return best

    def _try_control_reads(self) -> list[CaptureResult]:
        if self._device is None:
            return []
        results: list[CaptureResult] = []
        for request in range(0, 16):
            for request_type in (0xC0, 0x80):  # vendor IN, standard IN
                try:
                    data = self._device.ctrl_transfer(
                        request_type, request, 0, 0, 64, 200
                    )
                    if data:
                        results.append(
                            CaptureResult(
                                payload=bytes(data),
                                method="control IN",
                                endpoint=f"req=0x{request:02X} type=0x{request_type:02X}",
                            )
                        )
                except Exception:  # noqa: BLE001
                    continue
        return results

    def wait_for_send(self, duration_s: float = 30.0) -> CaptureResult:
        """
        BodyView arms USB on app open; SEND then returns data immediately.
        We open the session on connect, then read bulk IN while SEND is held.
        """
        self.ensure_session()

        best = CaptureResult(payload=b"", method="none")
        notes: list[str] = ["session armed — press SEND on skin…"]
        if getattr(self, "_session_notes", None):
            notes.extend(self._session_notes[:6])

        # BodyView measure path: hold SEND while polling (bx uses same 0xA0 0x01 OUT).
        hold_s = max(8.0, min(duration_s, 25.0))
        notes.append(f"holding SEND window {hold_s:.0f}s — gel, skin, press SEND…")
        hit = self._bodyview_button_read(hold_s=hold_s)
        if len(hit.payload) >= 8 and not is_placeholder_payload(hit.payload):
            hit.notes = notes + hit.notes
            return hit
        if len(hit.payload) >= 8:
            notes.append("warning: got USB padding (0x63) — unplug wand, replug, retry SEND")

        deadline = time.time() + duration_s

        while time.time() < deadline:
            # Keep OUT alive like BodyView during measurement.
            self._trigger_writes()
            for hit in self._read_endpoint_for(400, accumulate=True):
                notes.append(f"IN {hit.endpoint}: {len(hit.payload)} bytes")
                if len(hit.payload) > len(best.payload):
                    best = CaptureResult(
                        payload=hit.payload,
                        method="SEND bulk",
                        endpoint=hit.endpoint,
                    )
            for hit in self._try_control_reads():
                if len(hit.payload) > len(best.payload):
                    best = hit
                    notes.append(f"ctrl {hit.endpoint}: {hit.payload.hex()}")
            # Full A-scan is hundreds+ bytes; 2-byte status (0100) is not a measurement.
            if len(best.payload) >= 32:
                stream = self._collect_stream(min(2.0, deadline - time.time()))
                if len(stream.payload) > len(best.payload):
                    best = stream
                best.notes = notes + stream.notes
                return best

        if self.measurement_mode == MEASUREMENT_MODE_BODYVIEW:
            return self._listen_bodyview(duration_s, notes)

        best.notes = notes
        raise BodyMetrixError(
            f"No echo in {duration_s:.0f}s (got {len(best.payload)} bytes max). "
            "Press SEND on gelled skin. Try: python3 scripts/probe_usb.py hunt"
        )

    def _listen_bodyview(self, duration_s: float, notes: list[str]) -> CaptureResult:
        """Legacy path: try BodyView-style USB wake if passive SEND fails."""
        best = CaptureResult(payload=b"", method="none")
        self._wake_device()
        deadline = time.time() + duration_s
        while time.time() < deadline:
            self._try_control_writes()
            self._trigger_writes()
            for hit in self._read_endpoint_for(250):
                notes.append(f"bodyview {hit.endpoint}: {len(hit.payload)} bytes")
                if len(hit.payload) > len(best.payload):
                    best = hit
            if best.payload:
                break
        best.notes = notes
        if not best.payload:
            raise BodyMetrixError(
                f"No data in {duration_s:.0f}s. Try measurement_mode scanoprobe in config.json."
            )
        return best

    def listen(self, duration_s: float = 30.0, poll_ms: int = 250) -> CaptureResult:
        """Wait for SEND (scanoprobe) or legacy BodyView poll."""
        if self.measurement_mode == MEASUREMENT_MODE_SCANOPROBE:
            return self.wait_for_send(duration_s=duration_s)
        if self._device is None:
            self.connect()
        return self._listen_bodyview(duration_s, [])

    def capture_raw(self, timeout_ms: int = 8000) -> bytes:
        result = self.listen(duration_s=timeout_ms / 1000.0, poll_ms=300)
        return result.payload

    def parse_measurement_packet(self, payload: bytes) -> MeasurementResult:
        """Decode echo → mm (Scanoprobe: our peak math, not BodyView)."""
        if len(payload) < 2:
            raise BodyMetrixError(f"Payload too short ({len(payload)} bytes).")
        try:
            parsed: ScanoprobeResult = echo_to_thickness_mm(
                payload,
                sound_speed_m_s=self.sound_speed_m_s,
                sample_rates_hz=self.sample_rates_hz,
                prefer_ascan=self.measurement_mode == MEASUREMENT_MODE_SCANOPROBE,
            )
        except ValueError as exc:
            raise BodyMetrixError(str(exc)) from exc
        return MeasurementResult(
            mm=parsed.thickness_mm,
            source="scanoprobe" if parsed.sample_rate_hz else "embedded",
            method=parsed.method,
            confidence=parsed.confidence,
            bytes_received=len(payload),
        )

    def measure_mm(self, timeout_ms: int = 30000) -> float:
        return self.measure(timeout_ms=timeout_ms).mm

    def measure(self, timeout_ms: int = 30000) -> MeasurementResult:
        result = self.wait_for_send(duration_s=timeout_ms / 1000.0)
        return self.parse_measurement_packet(result.payload)

    def scan_state(self) -> dict:
        return self._scan.to_dict()

    def scan_begin(self, site: int) -> dict:
        self._scan = ScanScaleState(
            active=True,
            site=site,
            gain_index=DEFAULT_GAIN_INDEX,
            message="Scanoprobe LEDs — hold SEND, tune gain, HOLD to lock.",
        )
        self.ensure_session()
        return self._scan.to_dict()

    def scan_end(self) -> dict:
        self._scan = ScanScaleState()
        return self._scan.to_dict()

    def scan_adjust_gain(self, delta: int) -> dict:
        if not self._scan.active:
            raise BodyMetrixError("Scan not active.")
        if self._scan.locked:
            raise BodyMetrixError("Release HOLD before changing gain.")
        idx = self._scan.gain_index + int(delta)
        self._scan.gain_index = max(0, min(idx, len(GAIN_STEPS) - 1))
        self._scan.message = f"Gain {self._scan.gain}"
        return self._scan.to_dict()

    def scan_set_gain_index(self, index: int) -> dict:
        if not self._scan.active:
            raise BodyMetrixError("Scan not active.")
        if self._scan.locked:
            raise BodyMetrixError("Release HOLD before changing gain.")
        self._scan.gain_index = max(0, min(int(index), len(GAIN_STEPS) - 1))
        self._scan.message = f"Gain {self._scan.gain}"
        return self._scan.to_dict()

    def scan_toggle_hold(self) -> dict:
        if not self._scan.active:
            raise BodyMetrixError("Scan not active.")
        if self._scan.locked:
            self._scan.locked = False
            self._scan.locked_mm = None
            self._scan.message = "HOLD released — adjust gain or re-lock."
        else:
            if self._scan.live_mm is None:
                raise BodyMetrixError("No reading yet. Hold SEND on gelled skin.")
            self._scan.locked = True
            self._scan.locked_mm = self._scan.live_mm
            self._scan.message = f"LOCKED {self._scan.locked_mm:g} mm — put down wand, then save."
        return self._scan.to_dict()

    def scan_tick(self) -> dict:
        """One gain+read while SEND is held; skipped when scale is locked."""
        if not self._scan.active:
            raise BodyMetrixError("Scan not active.")
        if self._scan.locked:
            return self._scan.to_dict()

        self.ensure_session()
        if not self._pipes_configured:
            self.bodyview_init()

        gain = self._scan.gain
        # Scanoprobe path: write gain then read echo (user holds SEND on wand).
        capture = self.write_gain_and_read(gain, read_ms=450)
        if len(capture.payload) < 8:
            # Fall back to button path at current gain.
            capture = self._bodyview_button_read(hold_s=0.35)

        mm = scale_mm_from_payload(
            capture.payload,
            gain_byte=gain,
            gain_index=self._scan.gain_index,
        )
        if mm is not None:
            self._scan.live_mm = mm
            self._scan.message = f"{mm:g} mm @ gain {gain}"
        elif is_placeholder_payload(capture.payload):
            self._scan.message = "No signal — gel, skin, hold SEND (or unplug/replug)."
        else:
            self._scan.message = f"No mm @ gain {gain} — try gain +/-"

        return self._scan.to_dict()

    def save_capture(self, result: CaptureResult, out_dir: Path, stem: str) -> tuple[Path, Path]:
        out_dir.mkdir(parents=True, exist_ok=True)
        bin_path = out_dir / f"{stem}.bin"
        meta_path = out_dir / f"{stem}.json"
        bin_path.write_bytes(result.payload)
        meta = {
            "method": result.method,
            "endpoint": result.endpoint,
            "length": len(result.payload),
            "hex_preview": result.payload[:128].hex(),
            "notes": result.notes,
        }
        try:
            parsed = self.parse_measurement_packet(result.payload)
            meta["parsed_mm"] = parsed.mm
            meta["parse_method"] = parsed.method
            meta["confidence"] = parsed.confidence
        except BodyMetrixError as exc:
            meta["parse_error"] = str(exc)
        meta_path.write_text(json.dumps(meta, indent=2) + "\n")
        return bin_path, meta_path

    def describe(self) -> dict[str, Any]:
        if self._device is None:
            self.connect()
        assert self._device is not None
        dev = self._device
        return {
            "manufacturer": self._usb_descriptor_str(dev, "manufacturer"),
            "product": self._usb_descriptor_str(dev, "product"),
            "serial": self._usb_descriptor_str(dev, "serial_number"),
            "endpoints": self._endpoint_summary(),
        }

    def scan(self) -> list[dict[str, Any]]:
        """One-shot probe of all endpoints without waiting for button."""
        if self._device is None:
            self.connect()
        self._trigger_writes()
        hits: list[dict[str, Any]] = []
        for r in self._read_endpoint_for(500):
            hits.append(
                {
                    "method": r.method,
                    "endpoint": r.endpoint,
                    "length": len(r.payload),
                    "hex": r.payload[:32].hex(),
                }
            )
        for r in self._try_control_reads():
            hits.append(
                {
                    "method": r.method,
                    "endpoint": r.endpoint,
                    "length": len(r.payload),
                    "hex": r.payload[:32].hex(),
                }
            )
        return hits

    def _endpoint_summary(self) -> list[dict[str, Any]]:
        if self._device is None:
            return []
        cfg = self._device.get_active_configuration()
        summary = []
        for intf in cfg:
            for ep in intf:
                summary.append(
                    {
                        "address": f"0x{ep.bEndpointAddress:02X}",
                        "direction": "IN" if ep.bEndpointAddress & 0x80 else "OUT",
                        "type": ep.bmAttributes & 0x03,
                        "max_packet": ep.wMaxPacketSize,
                    }
                )
        return summary

    @staticmethod
    def _safe_str(value: Any) -> str:
        try:
            return str(value) if value is not None else ""
        except Exception:  # noqa: BLE001
            return ""

    @staticmethod
    def _usb_descriptor_str(dev: Any, attr: str) -> str:
        """Read USB string descriptor without crashing on langid / stuck device."""
        try:
            value = getattr(dev, attr)
            return str(value) if value is not None else ""
        except Exception:  # noqa: BLE001 — langid, detached, permission
            return ""


def load_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        example = path.parent / "config.example.json"
        if example.exists():
            return json.loads(example.read_text())
        return {}
    return json.loads(path.read_text())


def probe_from_config(cfg: dict[str, Any]) -> BodyMetrixProbe:
    def _parse_id(key: str, default: int) -> int:
        raw = cfg.get(key, default)
        if isinstance(raw, str):
            return int(raw, 16) if raw.lower().startswith("0x") else int(raw)
        return int(raw)

    rates = cfg.get("sample_rates_hz")
    sample_rates = tuple(float(r) for r in rates) if rates else DEFAULT_SAMPLE_RATES_HZ

    return BodyMetrixProbe(
        vendor_id=_parse_id("usb_vendor_id", VENDOR_ID),
        product_id=_parse_id("usb_product_id", PRODUCT_ID),
        sound_speed_m_s=float(cfg.get("sound_speed_m_s", 1540.0)),
        sample_rate_hz=float(cfg.get("sample_rate_hz", DEFAULT_SAMPLE_RATE_HZ)),
        measurement_mode=str(cfg.get("measurement_mode", MEASUREMENT_MODE_SCANOPROBE)),
        sample_rates_hz=sample_rates,
    )
