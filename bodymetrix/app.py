"""Flask app: two-site mm readings + custom fat % formula."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request

from bodymetrix.device import BodyMetrixProbe, load_config, probe_from_config
from bodymetrix.formula import FormulaError, evaluate_edwards_bodyfat, evaluate_fat_percent

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=str(ROOT / "templates"),
        static_folder=str(ROOT / "static"),
    )
    probe = probe_from_config(load_config(CONFIG_PATH))

    def get_config() -> dict[str, Any]:
        return load_config(CONFIG_PATH)

    def refresh_probe() -> None:
        nonlocal probe
        probe = probe_from_config(get_config())

    @app.get("/")
    def index() -> str:
        return render_template("index.html")

    @app.get("/api/status")
    def api_status() -> Any:
        cfg = get_config()
        status = probe.status()
        return jsonify(
            {
                "device": status.__dict__,
                "config": {
                    "site1_label": cfg.get("site1_label", "Site 1"),
                    "site2_label": cfg.get("site2_label", "Site 2"),
                    "has_formula": cfg.get("formula_type") == "edwards"
                    or bool(
                        cfg.get("fat_percent_formula")
                        and cfg.get("fat_percent_formula") != "REPLACE_WITH_YOUR_FORMULA"
                    ),
                },
            }
        )

    @app.get("/api/config")
    def api_get_config() -> Any:
        return jsonify(get_config())

    @app.post("/api/config")
    def api_save_config() -> Any:
        data = request.get_json(force=True)
        CONFIG_PATH.write_text(json.dumps(data, indent=2) + "\n")
        refresh_probe()
        return jsonify({"ok": True})

    @app.post("/api/measure")
    def api_measure() -> Any:
        payload = request.get_json(force=True) or {}
        mode = payload.get("mode", "manual")
        site = payload.get("site", 1)

        try:
            if mode == "device":
                probe.ensure_session()
                reading = probe.measure(timeout_ms=int(payload.get("timeout_ms", 30000)))
                mm = reading.mm
                source = reading.source
                method = reading.method
                confidence = reading.confidence
            else:
                mm = float(payload.get("mm", 0))
                if mm <= 0:
                    raise ValueError("Enter a positive mm value.")
                source = "manual"
                method = ""
                confidence = 1.0
        except Exception as exc:  # noqa: BLE001
            return jsonify({"ok": False, "error": str(exc)}), 400

        return jsonify(
            {
                "ok": True,
                "site": site,
                "mm": round(mm, 1),
                "source": source,
                "method": method,
                "confidence": confidence,
            }
        )

    @app.post("/api/calculate")
    def api_calculate() -> Any:
        payload = request.get_json(force=True) or {}
        cfg = get_config()
        try:
            mm1 = float(payload["mm1"])
            mm2 = float(payload["mm2"])
            sex = str(payload.get("sex") or cfg.get("default_sex", "female"))
            formula_type = payload.get("formula_type") or cfg.get("formula_type", "edwards")
            if formula_type == "edwards":
                result = evaluate_edwards_bodyfat(mm1, mm2, sex)
            else:
                formula = payload.get("formula") or cfg.get("fat_percent_formula", "")
                result = evaluate_fat_percent(formula, mm1, mm2)
        except (KeyError, TypeError, ValueError, FormulaError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400

        return jsonify(
            {
                "ok": True,
                "fat_percent": round(result.fat_percent, 2),
                "formula": result.expression,
                "mm1": mm1,
                "mm2": mm2,
                "sex": sex,
            }
        )

    @app.post("/api/device/describe")
    def api_device_describe() -> Any:
        try:
            info = probe.describe()
            return jsonify({"ok": True, "info": info})
        except Exception as exc:  # noqa: BLE001
            return jsonify({"ok": False, "error": str(exc)}), 400

    return app
