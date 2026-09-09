#!/usr/bin/env python3
"""Run the MM Measure app (subcutaneous depth only)."""

from bodymetrix.measure_app import create_measure_app


def main() -> None:
    app = create_measure_app()
    print("Scanoprobe → http://127.0.0.1:8766")
    print("Gain 0 · 0–50 mm · HOLD to lock")
    app.run(host="127.0.0.1", port=8766, debug=False)


if __name__ == "__main__":
    main()
