/** Scanoprobe — slider 0–50 directly lights that many LEDs; HOLD locks mm. */

let pollTimer = null;
let lastGainIndex = 0;
let lastSlider = 0;
let maxGainIndex = 127;
let gainRepeatTimer = null;
let gainBusy = false;
let sliderDragging = false;

const SLIDER_MAX = 50;
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

function renderLeds(state, gainChanged) {
  const bar = $("#led-bar");
  if (!bar) return;
  const mm = state.locked
    ? state.mm ?? state.locked_mm
    : state.live_mm ?? (state.bracket ? state.mm : null);
  const ledOn = state.led_on;
  const center = mm != null ? Math.round(mm) : 0;
  const b1 = center - 1;
  const b2 = center;
  const b3 = center + 1;

  bar.querySelectorAll(".led").forEach((el, i) => {
    const n = i + 1;
    el.className = "led";
    const on = Array.isArray(ledOn) && ledOn.length >= 50 ? !!ledOn[i] : false;
    if (on) el.classList.add("on");
    if (center >= 2 && (n === b1 || n === b2 || n === b3)) {
      if (n === b2) el.classList.add("bracket-core");
      else el.classList.add("bracket-edge");
      if (gainChanged && (n === b1 || n === b3)) el.classList.add("bounce");
    }
  });
}

function syncGainSlider(state, locked) {
  const slider = $("#gain-slider");
  if (!slider || sliderDragging) return;
  slider.max = String(state.slider_max ?? SLIDER_MAX);
  const pos = state.slider ?? 0;
  slider.value = String(pos);
  slider.disabled = locked;
  lastSlider = pos;
}

function render(state, gainChanged = false) {
  const mm = state.locked
    ? state.mm ?? state.locked_mm
    : state.live_mm ?? (state.bracket ? state.mm : null);
  const locked = !!state.locked;
  const sliderPos = state.slider ?? 0;

  if (state.gain_steps != null) {
    maxGainIndex = Math.max(0, state.gain_steps - 1);
  }

  $("#mm").textContent = formatMm(mm);
  $("#gain-label").textContent = `GAIN ${sliderPos}`;
  $("#device").classList.toggle("locked", locked);

  const holdBtn = $("#hold");
  holdBtn.classList.toggle("locked", locked);
  holdBtn.disabled = false;
  $("#gain-down").disabled = locked;
  $("#gain-up").disabled = locked;
  syncGainSlider(state, locked);

  const liveWrap = $("#live-wrap");
  if (liveWrap && !locked) {
    liveWrap.innerHTML = 'LIVE <span class="live-dot" id="live-dot"></span>';
  }

  renderLeds(state, gainChanged && !locked);

  const status = $("#status-message");
  if (status && state.message) {
    status.textContent = state.message;
  }

  if (state.gain_index != null) lastGainIndex = state.gain_index;
  lastSlider = sliderPos;
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
  }, 700);
}

async function setGainSlider(sliderVal, readWand = false) {
  if (gainBusy) return;
  gainBusy = true;
  const prev = lastSlider;
  const val = Math.max(0, Math.min(SLIDER_MAX, parseInt(sliderVal, 10)));
  const slider = $("#gain-slider");
  if (slider) slider.value = String(val);
  $("#gain-label").textContent = `GAIN ${val}`;
  try {
    const body = readWand ? { slider: val, read: true } : { slider: val };
    const state = await api("/api/scan/gain", body);
    render(state, state.slider !== prev);
  } catch (err) {
    const status = $("#status-message");
    if (status) status.textContent = err.message || "Gain failed";
    if (slider) slider.value = String(prev);
    $("#gain-label").textContent = `GAIN ${prev}`;
  } finally {
    gainBusy = false;
  }
}

async function nudgeGain(delta, readWand = false) {
  const slider = $("#gain-slider");
  const cur = slider ? parseInt(slider.value, 10) : lastSlider;
  await setGainSlider(cur + delta, readWand);
}

function stopGainRepeat() {
  if (gainRepeatTimer) {
    clearInterval(gainRepeatTimer);
    gainRepeatTimer = null;
  }
}

function startGainRepeat(delta) {
  stopPoll();
  stopGainRepeat();
  nudgeGain(delta, false).catch((err) => {
    const status = $("#status-message");
    if (status) status.textContent = err.message || "Gain failed";
  });
  gainRepeatTimer = setInterval(() => {
    nudgeGain(delta, false).catch((err) => {
      const status = $("#status-message");
      if (status) status.textContent = err.message || "Gain failed";
    });
  }, 180);
}

async function finishGainDial() {
  const slider = $("#gain-slider");
  const val = slider ? slider.value : lastSlider;
  try {
    await setGainSlider(val, true);
  } catch {
    try {
      render(await api("/api/scan/tick"), true);
    } catch {
      /* SEND not held */
    }
  }
}

function bindGainButton(btn, delta) {
  if (!btn) return;
  let holding = false;

  const onDown = (e) => {
    e.preventDefault();
    if (btn.disabled || holding) return;
    holding = true;
    startGainRepeat(delta);
  };
  const onUp = async () => {
    if (!holding) return;
    holding = false;
    stopGainRepeat();
    if ($("#new-btn")?.classList.contains("hidden")) {
      await finishGainDial();
      startPoll();
    }
  };

  btn.addEventListener("pointerdown", onDown);
  btn.addEventListener("pointerup", onUp);
  btn.addEventListener("pointerleave", onUp);
  btn.addEventListener("pointercancel", onUp);
}

function bindGainSlider() {
  const slider = $("#gain-slider");
  if (!slider) return;

  const onStart = () => {
    sliderDragging = true;
    stopPoll();
    stopGainRepeat();
  };

  const onInput = () => {
    if (slider.disabled) return;
    setGainSlider(slider.value, false);
  };

  const onEnd = async () => {
    if (!sliderDragging) return;
    sliderDragging = false;
    if (slider.disabled) return;
    await setGainSlider(slider.value, true);
    if (!$("#new-btn")?.classList.contains("hidden")) return;
    startPoll();
  };

  slider.addEventListener("pointerdown", onStart);
  slider.addEventListener("input", onInput);
  slider.addEventListener("change", onEnd);
  slider.addEventListener("pointerup", onEnd);
  slider.addEventListener("pointercancel", () => {
    sliderDragging = false;
  });
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
  stopPoll();
  stopGainRepeat();
  sliderDragging = false;
  lastGainIndex = 0;
  lastSlider = 0;
  const state = await api("/api/scan/begin");
  render(state);
  startPoll();
}

async function init() {
  ensureLedBar();
  await refreshProbe();
  await beginSession();

  bindGainSlider();
  bindGainButton($("#gain-down"), -1);
  bindGainButton($("#gain-up"), 1);

  document.addEventListener("keydown", (e) => {
    if (!$("#new-btn")?.classList.contains("hidden")) return;
    if (e.key === "-" || e.key === "_") {
      e.preventDefault();
      nudgeGain(-1, true);
    } else if (e.key === "=" || e.key === "+") {
      e.preventDefault();
      nudgeGain(1, true);
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
