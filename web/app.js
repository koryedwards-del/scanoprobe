import { evaluateFatPercent } from "./formula.js";
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
  if (config.fat_percent_formula && config.fat_percent_formula !== "REPLACE_WITH_YOUR_FORMULA") {
    $("#formula-input").value = config.fat_percent_formula;
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

function updateProbeStatus() {
  const el = $("#device-status");
  const compat = $("#compat-note");
  const hint = webUsbPlatformHint();

  if (state.webUsb.connected) {
    el.textContent = "Probe connected via browser USB";
    el.className = "status-pill ok";
  } else if (hint) {
    el.textContent = "Manual entry — USB not available in this browser";
    el.className = "status-pill warn";
    if (compat) compat.textContent = hint;
  } else if (webUsbSupported()) {
    el.textContent = "Click Connect probe (Chrome / Edge)";
    el.className = "status-pill warn";
    if (compat) compat.textContent = "Works: Chrome/Edge desktop · Android+OTG. Not iPhone/iPad Safari.";
  } else {
    el.textContent = "Manual entry only on this device";
    el.className = "status-pill warn";
  }
}

async function loadConfig() {
  if (hasBackend()) {
    try {
      applyConfig(await api("/api/config"));
      const status = await api("/api/status");
      if (status.device?.connected) {
        $("#device-status").textContent = status.device.message;
        $("#device-status").className = "status-pill ok";
      }
    } catch {
      applyConfig(loadLocalConfig());
    }
  } else {
    applyConfig(loadLocalConfig());
  }
  updateProbeStatus();
}

async function saveConfig() {
  const config = {
    site1_label: siteLabel(1),
    site2_label: siteLabel(2),
    fat_percent_formula: $("#formula-input").value.trim(),
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
  try {
    await state.webUsb.connect();
    toast("Probe connected.");
    updateProbeStatus();
    $("#connect-probe").textContent = "Probe connected";
  } catch (err) {
    toast(err.message, true);
    updateProbeStatus();
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
  toast(`Reading ${siteLabel(site)}… press probe button on skin.`);
  try {
    let mm;
    if (state.webUsb.connected || webUsbSupported()) {
      if (!state.webUsb.connected) await state.webUsb.connect();
      mm = await state.webUsb.measureMm();
    } else if (hasBackend()) {
      const data = await api("/api/measure", {
        method: "POST",
        body: JSON.stringify({ site, mode: "device" }),
      });
      mm = data.mm;
    } else {
      throw new Error(webUsbPlatformHint() || "USB not available.");
    }
    setReading(site, mm);
    toast(`${siteLabel(site)}: ${mm} mm (probe)`);
    if (state.mm1 != null && state.mm2 != null) await calculate(false);
  } catch (err) {
    toast(err.message, true);
  }
}

async function calculate(showToast = true) {
  if (state.mm1 == null || state.mm2 == null) {
    if (showToast) toast("Enter both measurements first.", true);
    return;
  }
  const formula = $("#formula-input").value.trim();
  try {
    let fatPercent;
    if (hasBackend()) {
      try {
        const data = await api("/api/calculate", {
          method: "POST",
          body: JSON.stringify({ mm1: state.mm1, mm2: state.mm2, formula }),
        });
        fatPercent = data.fat_percent;
      } catch {
        fatPercent = evaluateFatPercent(formula, state.mm1, state.mm2);
      }
    } else {
      fatPercent = evaluateFatPercent(formula, state.mm1, state.mm2);
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

$("#save-formula").addEventListener("click", saveConfig);
$("#calculate-btn").addEventListener("click", () => calculate(true));
$("#reset-btn").addEventListener("click", reset);
$("#connect-probe")?.addEventListener("click", connectProbe);

["#mm1-input", "#mm2-input"].forEach((sel) => {
  $(sel).addEventListener("keydown", (e) => {
    if (e.key === "Enter") saveMm(sel === "#mm1-input" ? 1 : 2);
  });
});

loadConfig();
