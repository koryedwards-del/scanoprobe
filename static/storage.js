/** localStorage config when running as static site (no Flask). */

const KEY = "burn_build_lba_config";

const DEFAULTS = {
  site1_label: "Thigh",
  site2_label: "Waist",
  fat_percent_formula: "",
};

export function loadLocalConfig() {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return { ...DEFAULTS };
    return { ...DEFAULTS, ...JSON.parse(raw) };
  } catch {
    return { ...DEFAULTS };
  }
}

export function saveLocalConfig(config) {
  localStorage.setItem(KEY, JSON.stringify(config));
}

export function hasBackend() {
  return document.body?.dataset?.backend === "flask";
}
