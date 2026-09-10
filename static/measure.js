/** Scanoprobe — gain slider = wand amplitude; LEDs/LCD from echo at that gain. */

let pollTimer = null;
let lastSlider = 0;
let gainBusy = false;
let sliderDragging = false;

const SLIDER_MAX = 50;
const $ = (sel) => document.querySelector(sel);

function rightmostLitLed(ledOn) {
  if (!Array.isArray(ledOn) || ledOn.length < 50) return 0;
  for (let i = 49; i >= 0; i--) {
    if (ledOn[i]) return i + 1;
  }
  return 0;
}

function formatLcd(state) {
  const fromState = state.lcd;
  if (fromState != null && fromState > 0) return String(fromState);
  const pos = rightmostLitLed(state.led_on);
  return pos > 0 ? String(pos) : "—";
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

function renderLeds(state) {
  const bar = $("#led-bar");
  if (!bar) return;
  const ledOn = state.led_on;

  bar.querySelectorAll(".led").forEach((el, i) => {
    el.className = "led";
    const on = Array.isArray(ledOn) && ledOn.length >= 50 ? !!ledOn[i] : false;
    if (on) el.classList.add("on");
  });
}

function syncGainSlider(state) {
  const slider = $("#gain-slider");
  if (!slider || sliderDragging) return;
  slider.max = String(state.slider_max ?? SLIDER_MAX);
  const pos = state.slider ?? 0;
  slider.value = String(pos);
  lastSlider = pos;
}

function render(state) {
  const sliderPos = state.slider ?? 0;

  $("#mm").textContent = formatLcd(state);
  $("#gain-label").textContent = `GAIN ${sliderPos}`;

  syncGainSlider(state);
  renderLeds(state);
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
      render(await api("/api/scan/tick"));
    } catch {
      /* waiting for SEND */
    }
  }, 700);
}

async function setGainSlider(sliderVal, readWand = false) {
  const val = Math.max(0, Math.min(SLIDER_MAX, parseInt(sliderVal, 10)));
  const slider = $("#gain-slider");
  if (slider) slider.value = String(val);
  $("#gain-label").textContent = `GAIN ${val}`;

  if (readWand && gainBusy) return;
  if (readWand) gainBusy = true;

  const prev = lastSlider;
  try {
    const body = readWand ? { slider: val, read: true } : { slider: val };
    render(await api("/api/scan/gain", body));
  } catch {
    if (readWand) {
      if (slider) slider.value = String(prev);
      $("#gain-label").textContent = `GAIN ${prev}`;
    }
  } finally {
    if (readWand) gainBusy = false;
  }
}

async function clearReading() {
  stopPoll();
  sliderDragging = false;
  try {
    render(await api("/api/scan/clear"));
  } catch {
    /* ignore */
  }
  startPoll();
}

function bindGainSlider() {
  const slider = $("#gain-slider");
  if (!slider) return;

  let downVal = null;
  let lastTapAt = 0;

  const onStart = () => {
    sliderDragging = true;
    downVal = slider.value;
  };

  const onInput = () => {
    setGainSlider(slider.value, false);
  };

  const onEnd = async () => {
    if (!sliderDragging) return;
    const tapped = downVal === slider.value;
    sliderDragging = false;
    if (tapped) {
      const now = Date.now();
      if (now - lastTapAt < 450) {
        lastTapAt = 0;
        await clearReading();
        return;
      }
      lastTapAt = now;
    }
    await setGainSlider(slider.value, true);
  };

  slider.addEventListener("pointerdown", onStart);
  slider.addEventListener("input", onInput);
  slider.addEventListener("change", onEnd);
  slider.addEventListener("pointerup", onEnd);
  slider.addEventListener("pointercancel", () => {
    sliderDragging = false;
  });

  $("#clear-btn")?.addEventListener("click", () => clearReading());
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
  stopPoll();
  sliderDragging = false;
  lastSlider = 0;
  render(await api("/api/scan/begin"));
  startPoll();
}

async function init() {
  ensureLedBar();
  await refreshProbe();
  await beginSession();
  bindGainSlider();
}

init();
