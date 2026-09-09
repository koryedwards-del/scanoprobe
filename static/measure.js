/** Scanoprobe — subcutaneous mm (gain 0, full LED bar, bracket tune, HOLD). */

let pollTimer = null;
let lastGainIndex = 0;
let gainRepeatTimer = null;

const $ = (sel) => document.querySelector(sel);

function formatMm(mm) {
  if (mm == null || !Number.isFinite(mm)) return "—";
  return (Math.round(mm * 10) / 10).toFixed(1);
}

async function api(path, body) {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : "{}",
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Request failed");
  return data;
}

function ensureLedBar() {
  const bar = $("#led-bar");
  if (!bar || bar.childElementCount >= 50) return;
  bar.innerHTML = "";
  for (let i = 0; i < 50; i++) {
    const el = document.createElement("div");
    el.className = "led";
    bar.appendChild(el);
  }
}

function renderLeds(mm, gainChanged) {
  const bar = $("#led-bar");
  if (!bar) return;
  const level = mm != null ? Math.max(0, Math.min(50, Math.round(mm))) : 0;
  const b1 = level - 1;
  const b2 = level;
  const b3 = level + 1;

  bar.querySelectorAll(".led").forEach((el, i) => {
    const n = i + 1;
    el.className = "led";
    if (level > 0 && n <= level) el.classList.add("on");
    if (level >= 2 && (n === b1 || n === b2 || n === b3)) {
      if (n === b2) el.classList.add("bracket-core");
      else el.classList.add("bracket-edge");
      if (gainChanged && (n === b1 || n === b3)) el.classList.add("bounce");
    }
  });
}

function render(state, gainChanged = false) {
  const mm = state.mm ?? state.live_mm ?? state.locked_mm;
  const locked = !!state.locked;
  const gainIdx = state.gain_index ?? 0;

  $("#mm").textContent = formatMm(mm);
  $("#gain-label").textContent = `GAIN ${gainIdx}`;
  $("#device").classList.toggle("locked", locked);

  const holdBtn = $("#hold");
  holdBtn.classList.toggle("locked", locked);
  holdBtn.disabled = false;
  $("#gain-down").disabled = locked;
  $("#gain-up").disabled = locked;

  const liveWrap = $("#live-wrap");
  if (liveWrap && !locked) {
    liveWrap.innerHTML = 'LIVE <span class="live-dot" id="live-dot"></span>';
  }

  renderLeds(mm, gainChanged && !locked);
  if (state.gain_index != null) lastGainIndex = state.gain_index;
}

function stopPoll() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

function startPoll() {
  stopPoll();
  pollTimer = setInterval(async () => {
    try {
      render(await api("/api/scan/tick"), false);
    } catch {
      /* waiting for SEND */
    }
  }, 450);
}

async function nudgeGain(delta) {
  const prev = lastGainIndex;
  const state = await api("/api/scan/gain", { delta });
  const gainChanged = state.gain_index !== prev;
  render(state, gainChanged);
  if (!state.locked) await api("/api/scan/tick").then((s) => render(s, gainChanged));
}

function stopGainRepeat() {
  if (gainRepeatTimer) {
    clearInterval(gainRepeatTimer);
    gainRepeatTimer = null;
  }
}

function startGainRepeat(delta) {
  stopGainRepeat();
  nudgeGain(delta).catch(() => {});
  gainRepeatTimer = setInterval(() => nudgeGain(delta).catch(() => {}), 100);
}

function bindGainButton(btn, delta) {
  if (!btn) return;
  const onStart = (e) => {
    e.preventDefault();
    if (btn.disabled) return;
    startGainRepeat(delta);
  };
  const onEnd = () => stopGainRepeat();
  btn.addEventListener("mousedown", onStart);
  btn.addEventListener("mouseup", onEnd);
  btn.addEventListener("mouseleave", onEnd);
  btn.addEventListener("touchstart", onStart, { passive: false });
  btn.addEventListener("touchend", onEnd);
  btn.addEventListener("touchcancel", onEnd);
}

async function refreshProbe() {
  const el = $("#probe-status");
  try {
    const res = await fetch("/api/status");
    const data = await res.json();
    const d = data.device || {};
    el.textContent = d.connected ? "Probe ready" : d.message || "Plug in probe";
    el.className = d.connected ? "probe-line ok" : "probe-line warn";
  } catch {
    el.textContent = "Plug in probe";
    el.className = "probe-line warn";
  }
}

async function beginSession() {
  $("#new-btn")?.classList.add("hidden");
  const state = await api("/api/scan/begin");
  render(state);
  startPoll();
}

async function init() {
  ensureLedBar();
  await refreshProbe();
  await beginSession();

  bindGainButton($("#gain-down"), -1);
  bindGainButton($("#gain-up"), 1);

  document.addEventListener("keydown", (e) => {
    if (!$("#new-btn")?.classList.contains("hidden")) return;
    if (e.key === "-" || e.key === "_") {
      e.preventDefault();
      nudgeGain(-1);
    } else if (e.key === "=" || e.key === "+") {
      e.preventDefault();
      nudgeGain(1);
    }
  });

  $("#hold")?.addEventListener("click", async () => {
    try {
      const state = await api("/api/scan/hold");
      render(state);
      if (state.locked) {
        stopPoll();
        $("#new-btn")?.classList.remove("hidden");
      } else {
        $("#new-btn")?.classList.add("hidden");
        startPoll();
      }
    } catch (err) {
      alert(err.message);
    }
  });

  $("#new-btn")?.addEventListener("click", () => beginSession());
}

init();
