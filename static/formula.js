/** Safe client-side fat % formula: mm1, mm2, Math only */

export function evaluateEdwardsBodyfat(thigh, waist, sex) {
  if (thigh <= 0 || waist <= 0) {
    throw new Error("Thigh and waist mm must be greater than zero.");
  }
  const s = String(sex || "").toLowerCase();
  let pf;
  if (s === "female" || s === "f") {
    const d = 1.12 - 0.0365 * Math.log10(thigh) - 0.0389 * Math.log10(waist);
    const rpf = 100 * (4.57 / d - 4.142);
    pf = rpf;
    if (rpf > 1.099) pf = rpf - 4;
    if (rpf > 15.099) pf = rpf - 3.5;
    if (rpf > 20.099) pf = rpf - 2.5;
    if (rpf > 25.099) pf = rpf - 2;
    if (rpf > 29.099) pf = rpf - 1;
    if (rpf > 33.099) pf = rpf - 0.5;
    if (rpf > 36.099) pf = rpf + 2;
  } else if (s === "male" || s === "m") {
    const d = 1.107 - 0.003845 * thigh - 0.001493 * waist;
    pf = 100 * (4.57 / d - 4.142);
  } else {
    throw new Error("Sex must be female or male.");
  }
  if (!Number.isFinite(pf)) throw new Error("Formula produced a non-finite result.");
  return Math.round(pf * 100) / 100;
}

export function evaluateFatPercent(expression, mm1, mm2) {
  const expr = String(expression || "").trim();
  if (!expr || expr === "REPLACE_WITH_YOUR_FORMULA") {
    throw new Error("Save your fat % formula first.");
  }
  if (mm1 <= 0 || mm2 <= 0) {
    throw new Error("Both mm readings must be greater than zero.");
  }
  if (!/^[\d\s.+\-*/%(),a-zA-Z]+$/.test(expr)) {
    throw new Error("Formula contains invalid characters.");
  }
  if (/\b(?!mm1\b|mm2\b|Math\b)\w+\b/.test(expr.replace(/mm1|mm2|Math/g, ""))) {
    throw new Error("Formula may only use mm1, mm2, and Math.");
  }
  let value;
  try {
    value = new Function("mm1", "mm2", "Math", `return (${expr});`)(mm1, mm2, Math);
  } catch (e) {
    throw new Error(`Invalid formula: ${e.message}`);
  }
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error("Formula must evaluate to a number.");
  }
  return Math.round(value * 100) / 100;
}
