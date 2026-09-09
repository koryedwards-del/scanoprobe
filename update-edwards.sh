#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

curl -fsSL -o static/app.js "https://tmpfiles.org/dl/1788904848.60fb64b20b9f7ac0/wiwO41OGnJiF/app.js"
curl -fsSL -o static/formula.js "https://tmpfiles.org/dl/1788904849.2306725294fef7fc/w7wz4MO6nwRA/formula.js"
curl -fsSL -o static/style.css "https://tmpfiles.org/dl/1788904849.5af5821d9eaffdb0/w7wW4AOsnCFl/style.css"
curl -fsSL -o bodymetrix/formula.py "https://tmpfiles.org/dl/1788904849.7f1d7789f880382d/wKwv46Ozn4DX/formula.py"
curl -fsSL -o bodymetrix/app.py "https://tmpfiles.org/dl/1788904849.b261854b67129490/w7wx4DOgnjCd/app.py"

cat > templates/index.html <<'HTML'
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
  <meta name="theme-color" content="#0f1419">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <title>Burn &amp; Build LBA</title>
  <link rel="stylesheet" href="/static/style.css">
  <link rel="manifest" href="/static/manifest.webmanifest">
</head>
<body data-backend="flask">
  <main class="container">
    <header>
      <h1>Burn &amp; Build LBA</h1>
      <p class="subtitle">Thigh + waist ultrasound → your fat % formula</p>
      <div class="header-actions">
        <div id="device-status" class="status-pill">Loading…</div>
        <button type="button" class="btn secondary" id="connect-probe">Connect probe</button>
      </div>
      <p id="compat-note" class="compat-note"></p>
    </header>

    <section id="result" class="card result-card hidden">
      <span class="result-label">Body fat</span>
      <span class="result-value" id="fat-percent">—</span>
    </section>

    <section class="card">
      <h2>1. Client</h2>
      <label class="field">
        <span>Sex</span>
        <select id="sex-input">
          <option value="female">Female</option>
          <option value="male">Male</option>
        </select>
      </label>
      <p class="hint">Edwards 2-site formula — thigh mm, waist mm, and sex.</p>
    </section>

    <section class="card">
      <h2>2. Measurements</h2>
      <div class="sites">
        <article class="site">
          <div class="site-header">
            <label class="field compact">
              <span>Site 1</span>
              <input id="site1-name" type="text" placeholder="Thigh" value="Thigh" autocomplete="off">
            </label>
            <span class="reading" id="mm1-display">—</span>
          </div>
          <div class="measure-row">
            <input id="mm1-input" type="number" step="0.1" min="0.1" max="80" placeholder="mm" inputmode="decimal">
            <button type="button" class="btn primary" data-action="save-mm" data-site="1">Set</button>
            <button type="button" class="btn secondary" data-action="probe" data-site="1">From probe</button>
          </div>
        </article>

        <article class="site">
          <div class="site-header">
            <label class="field compact">
              <span>Site 2</span>
              <input id="site2-name" type="text" placeholder="Waist" value="Waist" autocomplete="off">
            </label>
            <span class="reading" id="mm2-display">—</span>
          </div>
          <div class="measure-row">
            <input id="mm2-input" type="number" step="0.1" min="0.1" max="80" placeholder="mm" inputmode="decimal">
            <button type="button" class="btn primary" data-action="save-mm" data-site="2">Set</button>
            <button type="button" class="btn secondary" data-action="probe" data-site="2">From probe</button>
          </div>
        </article>
      </div>
      <button type="button" class="btn primary wide" id="calculate-btn">Calculate fat %</button>
      <button type="button" class="btn ghost" id="reset-btn">Clear readings</button>
    </section>
  </main>

  <div id="toast" class="toast hidden"></div>
  <script type="module" src="/static/app.js?v=4"></script>
</body>
</html>
HTML

if [[ ! -f config.json ]]; then
  curl -fsSL -o config.json "https://tmpfiles.org/dl/1788904850.b0d857ca673c5a20/www74eOXnz2l/config.example.json"
else
  python3 -c "
import json
from pathlib import Path
p = Path('config.json')
cfg = json.loads(p.read_text())
cfg['formula_type'] = 'edwards'
cfg['default_sex'] = cfg.get('default_sex', 'female')
cfg['fat_percent_formula'] = 'edwards'
p.write_text(json.dumps(cfg, indent=2) + '\n')
"
fi

echo "Updated. Restart ./go.sh then Cmd+Shift+R in Chrome."
