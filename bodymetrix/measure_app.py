"""MM Measure — standalone subcutaneous mm reader (no formula, no presets)."""

from __future__ import annotations

from typing import Any

from flask import Flask, jsonify, render_template, request, send_from_directory

from bodymetrix.device import BodyMetrixProbe, load_config, probe_from_config
from bodymetrix.scan_controller import ScanController

ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"


def create_measure_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=str(ROOT / "templates"),
        static_folder=str(ROOT / "static"),
    )
    probe = probe_from_config(load_config(CONFIG_PATH))
    scan = ScanController(probe)

    @app.get("/")
    def index() -> str:
        return render_template("measure.html")

    @app.get("/mockup")
    def led_mockup() -> Any:
        return send_from_directory(app.static_folder, "led-mockup.html")

    @app.get("/api/status")
    def api_status() -> Any:
        status = probe.status()
        return jsonify({"device": status.__dict__})

    @app.get("/api/scan/state")
    def api_scan_state() -> Any:
        return jsonify({"ok": True, **scan.state()})

    @app.post("/api/scan/begin")
    def api_scan_begin() -> Any:
        try:
            state = scan.begin(site=0)
            return jsonify({"ok": True, **state})
        except Exception as exc:  # noqa: BLE001
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.post("/api/scan/end")
    def api_scan_end() -> Any:
        return jsonify({"ok": True, **scan.end()})

    @app.post("/api/scan/tick")
    def api_scan_tick() -> Any:
        try:
            state = scan.tick()
            return jsonify({"ok": True, **state})
        except Exception as exc:  # noqa: BLE001
            return jsonify({"ok": False, **scan.state(), "error": str(exc)}), 400

    @app.post("/api/scan/gain")
    def api_scan_gain() -> Any:
        payload = request.get_json(force=True) or {}
        read_wand = bool(payload.get("read", False))
        fast = bool(payload.get("fast", False))
        try:
            if "slider" in payload:
                state = scan.set_slider(
                    int(payload["slider"]), read_wand=read_wand, fast=fast
                )
            elif "index" in payload:
                state = scan.set_gain_index(int(payload["index"]), read_wand=read_wand)
            else:
                state = scan.adjust_gain(
                    int(payload.get("delta", 0)), read_wand=read_wand
                )
            return jsonify({"ok": True, **state})
        except Exception as exc:  # noqa: BLE001
            return jsonify({"ok": False, "error": str(exc)}), 400

    @app.post("/api/scan/clear")
    def api_scan_clear() -> Any:
        try:
            state = scan.clear_reading()
            return jsonify({"ok": True, **state})
        except Exception as exc:  # noqa: BLE001
            return jsonify({"ok": False, **scan.state(), "error": str(exc)}), 400

    @app.post("/api/scan/hold")
    def api_scan_hold() -> Any:
        try:
            state = scan.toggle_hold()
            return jsonify({"ok": True, **state})
        except Exception as exc:  # noqa: BLE001
            return jsonify({"ok": False, **scan.state(), "error": str(exc)}), 400

    @app.post("/api/scan/save")
    def api_scan_save() -> Any:
        state = scan.state()
        if not state.get("active"):
            return jsonify({"ok": False, "error": "Not measuring."}), 400
        if not state.get("locked"):
            return jsonify({"ok": False, "error": "Press HOLD to lock first."}), 400
        mm = state.get("locked_mm") or state.get("mm")
        if mm is None:
            return jsonify({"ok": False, "error": "No mm value."}), 400
        scan.end()
        return jsonify(
            {
                "ok": True,
                "mm": round(float(mm), 1),
                "gain": state.get("gain"),
                "source": "scan-scale",
            }
        )

    return app
