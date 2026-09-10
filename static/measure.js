/** Scanoprobe — instant local gain on drag; wand read on release only. */

let pollTimer = null;
let lastSlider = 0;
let gainBusy = false;
let sliderDragging = false;
let cachedEnvelope = null;
let fastGainTimer = null;
let fastGainSeq = 0;

const SLIDER_MAX = 50;
const LED_COUNT = 50;
const MM_PER_BIN = 0.1;
const $ = (sel) => document.querySelector(sel);

function rightmostLitLed(ledOn) {
  if (!Array.isArray(ledOn) || ledOn.length < LED_COUNT) return 0;
  for (let i = LED_COUNT - 1; i >= 0; i--) {
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

function depthZeroBin(env) {
  if (env.length < 64) return 0;
  const head = env.slice(0, 32).sort((a, b) => a - b);
  const baseline = head[Math.floor(head.length / 2)] ?? 0;
  let peak = 0;
  for (let i = 0; i < env.length; i++) peak = Math.max(peak, env[i]);
  const trigger = baseline + 0.08 * (peak - baseline);
  let run = 0;
  const end = Math.min(env.length - 4, 400);
  for (let i = 5; i < end; i++) {
    if (env[i] > trigger) {
      run += 1;
      if (run >= 3) return Math.max(0, i - 2);
    } else {
      run = 0;
    }
  }
  return 0;
}

function envelopeAtLed(env, led, depthZero = 0) {
  const binIdx = depthZero + Math.round(led / MM_PER_BIN);
  const lo = Math.max(0, binIdx - 2);
  const hi = Math.min(env.length, binIdx + 3);
  if (lo >= hi) return 0;
  let peak = 0;
  for (let i = lo; i < hi; i++) peak = Math.max(peak, env[i]);
  return peak;
}

function ledsForEcho(env, slider) {
  const off = Array(LED_COUNT).fill(false);
  if (slider <= 0 || env.length < 32) return off;

  let peak = 0;
  for (let i = 0; i < env.length; i++) peak = Math.max(peak, env[i]);
  if (peak < 2) return off;

  const dial = Math.min(1, slider / SLIDER_MAX);
  const depthZero = depthZeroBin(env);
  const tail = env.slice(depthZero, Math.min(env.length, depthZero + 600));
  if (tail.length < 16) return off;

  const head = tail.slice(0, 16).sort((a, b) => a - b);
  const baseline = head[Math.floor(head.length / 2)] ?? 0;
  const tailPeak = Math.max(...tail);
  const span = Math.max(1, tailPeak - baseline);
  const floor = baseline + 0.05 * span;
  const threshold = tailPeak - span * dial * 0.98;

  for (let led = 1; led <= LED_COUNT; led++) {
    if (envelopeAtLed(env, led, depthZero) > Math.max(floor, threshold)) {
      off[led - 1] = true;
    }
  }
  return off;
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
  if (!bar || bar.childElementCount >= LED_COUNT) return;
  bar.innerHTML = "";
  for (let i = 0; i < LED_COUNT; i++) {
    const el = document.createElement("div");
    el.className = "led";
    bar.appendChild(el);
  }
}

function renderLeds(ledOn) {
  const bar = $("#led-bar");
  if (!bar) return;
  bar.querySelectorAll(".led").forEach((el, i) => {
    el.className = "led";
    const on = Array.isArray(ledOn) && ledOn.length >= LED_COUNT ? !!ledOn[i] : false;
    if (on) el.classList.add("on");
  });
}

function syncGainSlider(state, locked) {
  const slider = $("#gain-slider");
  if (!slider || sliderDragging) return;
  slider.max = String(state.slider_max ?? SLIDER_MAX);
  const pos = state.slider ?? 0;
  slider.value = String(pos);
  lastSlider = pos;
}

function applyLocalGain(val) {
  $("#gain-label").textContent = `GAIN ${val}`;
  if (!cachedEnvelope) {
    $("#mm").textContent = val > 0 ? "—" : "—";
    return;
  }
  const ledOn = ledsForEcho(cachedEnvelope, val);
  renderLeds(ledOn);
  const lcd = rightmostLitLed(ledOn);
  $("#mm").textContent = lcd > 0 ? String(lcd) : "—";
}

function render(state) {
  const isNewSend = !!state.new_send;
  if (isNewSend) {
    cachedEnvelope = null;
    fastGainSeq++;
    clearTimeout(fastGainTimer);
    sliderDragging = false;
    lastSlider = 0;
    const slider = $("#gain-slider");
    if (slider) slider.value = "0";
    $("#gain-label").textContent = "GAIN 0";
    $("#mm").textContent = "—";
    renderLeds(Array(LED_COUNT).fill(false));
  }

  const sliderPos = state.slider ?? 0;
  if (!isNewSend || sliderPos > 0) {
    $("#gain-label").textContent = `GAIN ${sliderPos}`;
  }

  if (sliderDragging && cachedEnvelope) {
    applyLocalGain(parseInt($("#gain-slider")?.value ?? sliderPos, 10));
  } else {
    if (!isNewSend) {
      $("#mm").textContent = formatLcd(state);
    }
    renderLeds(state.led_on);
    syncGainSlider(state);
  }

  if (Array.isArray(state.envelope) && state.envelope.length >= 32) {
    cachedEnvelope = state.envelope;
  }

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
    if (sliderDragging) return;
    try {
      render(await api("/api/scan/tick"));
    } catch {
      /* waiting for SEND */
    }
  }, 350);
}

function queueFastGain(val) {
  applyLocalGain(val);
  const seq = ++fastGainSeq;
  clearTimeout(fastGainTimer);
  fastGainTimer = setTimeout(() => {
    api("/api/scan/gain", { slider: val, fast: true })
      .then((state) => {
        if (seq === fastGainSeq && sliderDragging) render(state);
      })
      .catch(() => {});
  }, 12);
}

async function setGainSlider(sliderVal, readWand = false) {
  const val = Math.max(0, Math.min(SLIDER_MAX, parseInt(sliderVal, 10)));
  const slider = $("#gain-slider");
  if (slider) slider.value = String(val);

  if (!readWand) {
    queueFastGain(val);
    return;
  }

  if (gainBusy) return;
  gainBusy = true;
  const prev = lastSlider;
  applyLocalGain(val);
  try {
    render(await api("/api/scan/gain", { slider: val, read: true }));
  } catch {
    if (slider) slider.value = String(prev);
    applyLocalGain(prev);
  } finally {
    gainBusy = false;
  }
}

function bindGainSlider() {
  const slider = $("#gain-slider");
  if (!slider) return;

  const onStart = () => {
    sliderDragging = true;
    stopPoll();
  };

  const onInput = () => {
    queueFastGain(parseInt(slider.value, 10));
  };

  const onEnd = async () => {
    if (!sliderDragging) return;
    sliderDragging = false;
    clearTimeout(fastGainTimer);
    await setGainSlider(slider.value, true);
    startPoll();
  };

  slider.addEventListener("pointerdown", onStart);
  slider.addEventListener("input", onInput);
  slider.addEventListener("change", onEnd);
  slider.addEventListener("pointerup", onEnd);
  slider.addEventListener("pointercancel", () => {
    sliderDragging = false;
    startPoll();
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
  stopPoll();
  sliderDragging = false;
  cachedEnvelope = null;
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
