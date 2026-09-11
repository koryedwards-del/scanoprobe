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

const SKIN_LEDS = 3;

function rightmostLitLed(ledOn) {
  if (!Array.isArray(ledOn) || ledOn.length < LED_COUNT) return 0;
  for (let i = LED_COUNT - 1; i >= 0; i--) {
    if (ledOn[i]) return i + 1;
  }
  return 0;
}

function borderLed(ledOn) {
  if (!Array.isArray(ledOn) || ledOn.length < LED_COUNT) return 0;
  const right = rightmostLitLed(ledOn);
  if (right <= SKIN_LEDS) return 0;
  for (let i = SKIN_LEDS; i < right - 1; i++) {
    if (!ledOn[i]) return right;
  }
  return 0;
}

function formatLcd(state) {
  if (state.locked && state.mm != null) return String(Math.round(state.mm));
  const fromState = state.lcd;
  if (fromState != null && fromState > 0) return String(fromState);
  const pos = borderLed(state.led_on);
  return pos > 0 ? String(pos) : "—";
}

function findSkinPeakBin(env) {
  const head = env.slice(0, Math.max(16, Math.floor(env.length / 32)));
  const sorted = head.slice().sort((a, b) => a - b);
  const baseline = sorted[Math.floor(sorted.length / 2)] ?? 0;
  let peak = 0;
  for (let i = 0; i < env.length; i++) peak = Math.max(peak, env[i]);
  const threshold = baseline + 0.08 * (peak - baseline);
  const end = Math.min(env.length - 2, Math.round(3.0 / MM_PER_BIN) + 50);
  for (let i = 5; i < end; i++) {
    if (env[i] < threshold) continue;
    if (env[i] >= env[i - 1] && env[i] >= env[i + 1]) return i;
  }
  return null;
}

function depthAnchor(skinBin) {
  return Math.max(0, skinBin - Math.round(2.0 / MM_PER_BIN));
}

function envelopeAtMm(env, mm, anchor) {
  const binIdx = anchor + Math.round(mm / MM_PER_BIN);
  const lo = Math.max(0, binIdx - 3);
  const hi = Math.min(env.length, binIdx + 4);
  if (lo >= hi) return 0;
  let amp = 0;
  for (let i = lo; i < hi; i++) amp = Math.max(amp, env[i]);
  return amp;
}

function gainCut(env, anchor, skinAmp, dial) {
  const tail = env.slice(anchor, Math.min(env.length, anchor + 550));
  const use = tail.length >= 8 ? tail : env;
  const head = use.slice(0, Math.max(8, Math.floor(use.length / 8))).sort((a, b) => a - b);
  const baseline = head[Math.floor(head.length / 2)] ?? 0;
  const floor = Math.min(skinAmp, baseline + 0.05 * Math.max(1, skinAmp - baseline));
  return floor + (1 - dial) * Math.max(0, skinAmp - floor) * 0.98;
}

function echoParams(env) {
  let peak = 0;
  for (let i = 0; i < env.length; i++) peak = Math.max(peak, env[i]);
  const skinBin = findSkinPeakBin(env);
  let anchor = 0;
  let skinAmp = Math.max(...env.slice(0, Math.max(32, Math.floor(env.length / 16))));
  if (skinBin != null) {
    anchor = depthAnchor(skinBin);
    const lo = Math.max(0, skinBin - 3);
    const hi = Math.min(env.length, skinBin + 4);
    skinAmp = Math.max(...env.slice(lo, hi));
  }
  return { anchor, skinAmp, peak, skinBin };
}

function ledsForEcho(env, slider) {
  const off = Array(LED_COUNT).fill(false);
  if (slider <= 0 || env.length < 32) return off;

  const { anchor, skinAmp, peak } = echoParams(env);
  if (peak < 2) return off;
  if (slider >= SLIDER_MAX) return Array(LED_COUNT).fill(true);

  const dial = slider / SLIDER_MAX;
  const cut = gainCut(env, anchor, skinAmp, dial);

  for (let mm = 1; mm <= LED_COUNT; mm++) {
    if (envelopeAtMm(env, mm, anchor) > cut) off[mm - 1] = true;
  }
  return off;
}

function ampsByDepth(env, anchor) {
  const amps = [];
  for (let mm = 0; mm <= LED_COUNT; mm++) {
    amps.push(envelopeAtMm(env, mm, anchor));
  }
  return amps;
}

function drawWaveform(env, slider, locked = false) {
  const canvas = $("#wave-canvas");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const w = Math.max(1, Math.floor(rect.width));
  const h = Math.max(1, Math.floor(rect.height));
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  ctx.fillStyle = "#0a0a0a";
  ctx.fillRect(0, 0, w, h);

  const pad = { l: 6, r: 6, t: 8, b: 16 };
  const gw = w - pad.l - pad.r;
  const gh = h - pad.t - pad.b;

  if (!env || env.length < 32) {
    ctx.fillStyle = "#555";
    ctx.font = "11px sans-serif";
    ctx.textAlign = "center";
    ctx.fillText("Hold SEND — live waveform", w / 2, h / 2);
    return;
  }

  const { anchor, skinAmp, peak } = echoParams(env);
  const amps = ampsByDepth(env, anchor);
  let maxAmp = Math.max(peak, ...amps, 2);
  const dial = slider / SLIDER_MAX;
  const cut = slider > 0 ? gainCut(env, anchor, skinAmp, dial) : maxAmp;
  maxAmp = Math.max(maxAmp, cut, 2);

  const trace = locked ? "#e8a020" : "#5cb85c";
  const fill = locked ? "rgba(232, 160, 32, 0.22)" : "rgba(45, 138, 45, 0.3)";
  const cutColor = locked ? "#e8a020" : "#e82828";

  ctx.strokeStyle = "#1e1e1e";
  ctx.lineWidth = 1;
  for (let mm = 0; mm <= LED_COUNT; mm += 10) {
    const x = pad.l + (mm / LED_COUNT) * gw;
    ctx.beginPath();
    ctx.moveTo(x, pad.t);
    ctx.lineTo(x, pad.t + gh);
    ctx.stroke();
  }

  ctx.fillStyle = "rgba(100, 100, 100, 0.12)";
  ctx.fillRect(pad.l, pad.t, (SKIN_LEDS / LED_COUNT) * gw, gh);

  if (slider > 0) {
    const cutY = pad.t + gh - (cut / maxAmp) * gh;
    ctx.strokeStyle = cutColor;
    ctx.lineWidth = 1;
    ctx.setLineDash([5, 4]);
    ctx.beginPath();
    ctx.moveTo(pad.l, cutY);
    ctx.lineTo(pad.l + gw, cutY);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  const yAt = (amp) => pad.t + gh - (amp / maxAmp) * gh;
  const xAt = (mm) => pad.l + (mm / LED_COUNT) * gw;

  ctx.beginPath();
  ctx.moveTo(xAt(0), yAt(amps[0]));
  for (let mm = 1; mm <= LED_COUNT; mm++) {
    ctx.lineTo(xAt(mm), yAt(amps[mm]));
  }
  ctx.lineTo(xAt(LED_COUNT), pad.t + gh);
  ctx.lineTo(xAt(0), pad.t + gh);
  ctx.closePath();
  ctx.fillStyle = fill;
  ctx.fill();

  ctx.beginPath();
  ctx.moveTo(xAt(0), yAt(amps[0]));
  for (let mm = 1; mm <= LED_COUNT; mm++) {
    ctx.lineTo(xAt(mm), yAt(amps[mm]));
  }
  ctx.strokeStyle = trace;
  ctx.lineWidth = 1.5;
  ctx.stroke();

  ctx.fillStyle = "#666";
  ctx.font = "9px sans-serif";
  ctx.textAlign = "center";
  for (let mm = 0; mm <= LED_COUNT; mm += 10) {
    ctx.fillText(String(mm), xAt(mm), h - 3);
  }
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

function syncGainSlider(state) {
  const slider = $("#gain-slider");
  if (!slider || sliderDragging) return;
  slider.max = String(state.slider_max ?? SLIDER_MAX);
  const pos = state.slider ?? 0;
  slider.value = String(pos);
  slider.disabled = !!state.locked;
  lastSlider = pos;
}

function syncHold(state) {
  const device = $("#device");
  const btn = $("#hold-btn");
  const locked = !!state.locked;
  if (device) device.classList.toggle("locked", locked);
  if (!btn) return;
  btn.classList.toggle("active", locked);
  btn.setAttribute("aria-pressed", locked ? "true" : "false");
  const hasMm = state.mm != null || borderLed(state.led_on) > 0;
  btn.disabled = !locked && !hasMm;
}

function applyLocalGain(val, locked = false) {
  $("#gain-label").textContent = `GAIN ${val}`;
  drawWaveform(cachedEnvelope, val, locked);
  if (!cachedEnvelope) {
    $("#mm").textContent = "—";
    return;
  }
  const ledOn = ledsForEcho(cachedEnvelope, val);
  renderLeds(ledOn);
  const lcd = borderLed(ledOn);
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
    drawWaveform(null, 0, false);
  }

  const sliderPos = state.slider ?? 0;
  if (!isNewSend || sliderPos > 0) {
    $("#gain-label").textContent = `GAIN ${sliderPos}`;
  }

  if (state.locked) {
    stopPoll();
  } else if (!pollTimer && !sliderDragging) {
    startPoll();
  }

  const activeSlider = sliderDragging
    ? parseInt($("#gain-slider")?.value ?? sliderPos, 10)
    : sliderPos;

  if (sliderDragging && cachedEnvelope && !state.locked) {
    applyLocalGain(activeSlider, false);
  } else {
    if (!isNewSend) {
      $("#mm").textContent = formatLcd(state);
    }
    renderLeds(state.led_on);
    syncGainSlider(state);
    drawWaveform(cachedEnvelope, activeSlider, !!state.locked);
  }

  syncHold(state);
  syncHint(state);

  if (Array.isArray(state.envelope) && state.envelope.length >= 32) {
    cachedEnvelope = state.envelope;
  }

  lastSlider = sliderPos;
}

function syncHint(state) {
  const el = $("#probe-status");
  if (!el || state.locked) return;
  if (state.message) {
    el.textContent = state.message;
    el.className = "probe-line ok";
  }
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
  }, 400);
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

async function toggleHold() {
  const btn = $("#hold-btn");
  if (btn?.disabled) return;
  try {
    render(await api("/api/scan/hold"));
  } catch (err) {
    /* no reading yet */
  }
}

function bindHold() {
  const btn = $("#hold-btn");
  if (!btn) return;
  btn.addEventListener("click", () => toggleHold());
}

async function beginSession() {
  stopPoll();
  sliderDragging = false;
  cachedEnvelope = null;
  lastSlider = 0;
  render(await api("/api/scan/begin"));
  startPoll();
}

function bindWaveformResize() {
  const canvas = $("#wave-canvas");
  if (!canvas) return;
  const redraw = () => {
    const slider = parseInt($("#gain-slider")?.value ?? lastSlider, 10);
    const locked = $("#device")?.classList.contains("locked");
    drawWaveform(cachedEnvelope, slider, locked);
  };
  window.addEventListener("resize", redraw);
  if (typeof ResizeObserver !== "undefined") {
    new ResizeObserver(redraw).observe(canvas.parentElement);
  }
}

async function init() {
  ensureLedBar();
  bindWaveformResize();
  drawWaveform(null, 0, false);
  await refreshProbe();
  await beginSession();
  bindGainSlider();
  bindHold();
}

init();
