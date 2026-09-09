# Personal use on your devices

This is **your** tool — no public site, no accounts, no cloud.

## Recommended setup

**Your main machine** (laptop/desktop):

```bash
./go.sh
```

Bookmark `http://127.0.0.1:8765` in Chrome or Edge.

## Other devices you own

**Android tablet** (with USB OTG): copy the `web/` folder to the device or open it from a local file server; use Chrome. Probe may work with OTG.

**iPhone / iPad**: use manual mm entry only — type readings from your probe display or from the laptop session.

You do **not** need to deploy to Netlify, buy a domain, or publish anything.

## `web/` folder (optional)

If you want the UI without running Python:

```bash
cd web
python3 -m http.server 8765
```

Open `http://127.0.0.1:8765` on the same computer. Formula saves in browser localStorage.

## Data stays local

- `config.json` — on your computer only (not in git)
- `captures/` — USB debug files you create
- No telemetry, no login
