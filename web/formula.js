/** Safe client-side fat % formula: mm1, mm2, Math only */

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
