import { evaluateEdwardsBodyfat, evaluateFatPercent } from "./formula.js";
import { BodyMetrixWebUSB, webUsbPlatformHint, webUsbSupported } from "./webusb.js";
import { hasBackend, loadLocalConfig, saveLocalConfig } from "./storage.js";

const state = { mm1: null, mm2: null, config: {}, webUsb: new BodyMetrixWebUSB() };

const $ = (sel) => document.querySelector(sel);

function toast(message, isError = false) {
  const el = $("#toast");
  el.textContent = message;
  el.classList.toggle("err", isError);
  el.classList.remove("hidden");
  clearTimeout(el._timer);
  el._timer = setTimeout(() => el.classList.add("hidden"), 3500);
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || "Request failed");
  return data;
}

function siteLabel(site) {
  const el = site === 1 ? $("#site1-name") : $("#site2-name");
  return el.value.trim() || `Site ${site}`;
}

function applyConfig(config) {
  state.config = config;
  $("#site1-name").value = config.site1_label || "Thigh";
  $("#site2-name").value = config.site2_label || "Waist";
  if (config.default_sex) {
    $("#sex-input").value = config.default_sex;
  }
}

function setReading(site, mm) {
  const rounded = Math.round(mm * 10) / 10;
  if (site === 1) {
    state.mm1 = rounded;
    $("#mm1-display").textContent = `${rounded} mm`;
    $("#mm1-input").value = rounded;
  } else {
    state.mm2 = rounded;
    $("#mm2-display").textContent = `${rounded} mm`;
    $("#mm2-input").value = rounded;
  }
}

function updateProbeStatus(message, className = "status-pill warn") {
  const el = $("#device-status");
  const compat = $("#compat-note");
  el.textContent = message;
  el.className = className;
  if (compat && hasBackend()) {
    compat.textContent = "Probe reads through the Mac app (not browser USB).";
  }
}

async function refreshServerProbeStatus() {
  if (!hasBackend()) {
    updateProbeStatusFromWebUsb();
    return;
  }
  try {
    const status = await api("/api/status");
    const device = status.device || {};
    if (device.connected) {
      updateProbeStatus(device.message || "Probe ready — press SEND on wand", "status-pill ok");
      $("#connect-probe").textContent = "Probe detected";
    } else {
      updateProbeStatus(device.message || "Plug in probe via USB", "status-pill warn");
      $("#connect-probe").textContent = "Check probe";
    }
  } catch {
    updateProbeStatus("App running — plug in probe", "status-pill warn");
  }
}

function updateProbeStatusFromWebUsb() {
  const compat = $("#compat-note");
  const hint = webUsbPlatformHint();

  if (state.webUsb.connected) {
    updateProbeStatus("Probe connected via browser USB", "status-pill ok");
    return;
  }
  if (hint) {
    updateProbeStatus("Manual entry — USB not available in this browser", "status-pill warn");
    if (compat) compat.textContent = hint;
    return;
  }
  if (webUsbSupported()) {
    updateProbeStatus("Static site — browser USB only", "status-pill warn");
    if (compat) compat.textContent = "For the probe, run ./go.sh on your Mac instead.";
    return;
  }
  updateProbeStatus("Manual entry only on this device", "status-pill warn");
}

async function loadConfig() {
  if (hasBackend()) {
    $("#connect-probe")?.classList.add("hidden");
    try {
      applyConfig(await api("/api/config"));
    } catch {
      applyConfig(loadLocalConfig());
    }
    await refreshServerProbeStatus();
  } else {
    applyConfig(loadLocalConfig());
    updateProbeStatusFromWebUsb();
  }
}

async function saveConfig() {
  const config = {
    site1_label: siteLabel(1),
    site2_label: siteLabel(2),
    formula_type: "edwards",
    default_sex: $("#sex-input").value,
    fat_percent_formula: "edwards",
  };
  if (hasBackend()) {
    try {
      await api("/api/config", { method: "POST", body: JSON.stringify({ ...state.config, ...config }) });
    } catch {
      saveLocalConfig(config);
    }
  } else {
    saveLocalConfig(config);
  }
  state.config = { ...state.config, ...config };
  toast("Saved.");
}

async function connectProbe() {
  if (hasBackend()) {
    await refreshServerProbeStatus();
    toast($("#device-status").textContent);
    return;
  }
  try {
    await state.webUsb.connect();
    toast("Probe connected.");
    updateProbeStatusFromWebUsb();
    $("#connect-probe").textContent = "Probe connected";
  } catch (err) {
    toast(err.message, true);
    updateProbeStatusFromWebUsb();
  }
}

async function saveMm(site) {
  const input = site === 1 ? $("#mm1-input") : $("#mm2-input");
  const mm = Number(input.value);
  if (!Number.isFinite(mm) || mm <= 0) {
    toast(`Enter a valid mm value for ${siteLabel(site)}.`, true);
    return;
  }
  setReading(site, mm);
  await saveConfig();
  toast(`${siteLabel(site)}: ${mm} mm`);
  if (state.mm1 != null && state.mm2 != null) await calculate(false);
}

async function fromProbe(site) {
  toast(`Reading ${siteLabel(site)}… gel, place on skin, press SEND on wand.`);
  try {
    let mm;
    if (hasBackend()) {
      const data = await api("/api/measure", {
        method: "POST",
        body: JSON.stringify({ site, mode: "device" }),
      });
      mm = data.mm;
    } else if (state.webUsb.connected || webUsbSupported()) {
      if (!state.webUsb.connected) await state.webUsb.connect();
      mm = await state.webUsb.measureMm();
    } else {
      throw new Error(webUsbPlatformHint() || "USB not available.");
    }
    setReading(site, mm);
    toast(`${siteLabel(site)}: ${mm} mm (probe)`);
    if (state.mm1 != null && state.mm2 != null) await calculate(false);
  } catch (err) {
    toast(err.message, true);
    if (hasBackend()) await refreshServerProbeStatus();
  }
}

function hasValidFormula() {
  return state.config.formula_type === "edwards" || $("#formula-input")?.value?.trim();
}

function currentSex() {
  return $("#sex-input").value;
}

async function calculate(showToast = true) {
  if (state.mm1 == null || state.mm2 == null) {
    if (showToast) toast("Enter both measurements first.", true);
    return;
  }
  const sex = currentSex();
  try {
    let fatPercent;
    if (hasBackend()) {
      const data = await api("/api/calculate", {
        method: "POST",
        body: JSON.stringify({
          mm1: state.mm1,
          mm2: state.mm2,
          sex,
          formula_type: "edwards",
        }),
      });
      fatPercent = data.fat_percent;
    } else {
      fatPercent = evaluateEdwardsBodyfat(state.mm1, state.mm2, sex);
    }
    $("#fat-percent").textContent = `${fatPercent}%`;
    $("#result").classList.remove("hidden");
    if (showToast) toast("Fat % calculated.");
  } catch (err) {
    toast(err.message, true);
  }
}

function reset() {
  state.mm1 = null;
  state.mm2 = null;
  $("#mm1-display").textContent = "—";
  $("#mm2-display").textContent = "—";
  $("#mm1-input").value = "";
  $("#mm2-input").value = "";
  $("#result").classList.add("hidden");
  toast("Cleared.");
}

document.querySelectorAll("[data-action=save-mm]").forEach((btn) => {
  btn.addEventListener("click", () => saveMm(Number(btn.dataset.site)));
});

document.querySelectorAll("[data-action=probe]").forEach((btn) => {
  btn.addEventListener("click", () => fromProbe(Number(btn.dataset.site)));
});

$("#calculate-btn").addEventListener("click", () => calculate(true));
$("#reset-btn").addEventListener("click", reset);
$("#connect-probe")?.addEventListener("click", connectProbe);
$("#sex-input").addEventListener("change", saveConfig);

["#mm1-input", "#mm2-input"].forEach((sel) => {
  $(sel).addEventListener("keydown", (e) => {
    if (e.key === "Enter") saveMm(sel === "#mm1-input" ? 1 : 2);
  });
});

loadConfig();
