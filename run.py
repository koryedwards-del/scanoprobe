#!/usr/bin/env python3
"""Run the BodyMetrix mm reader web app."""

from bodymetrix.app import create_app


def main() -> None:
    app = create_app()
    print("Scanoprobe → http://127.0.0.1:8765")
    print("Plug in your probe, edit config.json with your formula, then open the page.")
    app.run(host="127.0.0.1", port=8765, debug=False)


if __name__ == "__main__":
    main()
