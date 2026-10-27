export const finite = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value);
export const number = (value: unknown, digits = 0) =>
  finite(value) ? value.toFixed(digits) : "—";
export const percent = (value: unknown) =>
  finite(value) ? `${Math.round(value)}%` : "—";
export const clamp = (value: unknown) =>
  finite(value) ? Math.max(0, Math.min(100, value)) : 0;
export const knowledgeLabel = (state: string, evidence: number) =>
  state === "unseen"
    ? evidence > 0
      ? "证据不足"
      : "尚未学习"
    : state === "weak"
      ? "需要巩固"
      : "已掌握";
export function delta(value: unknown, unit = "个百分点") {
  return finite(value)
    ? `${value > 0 ? "+" : ""}${number(value, 1)} ${unit}`
    : "暂无可比较记录";
}

export function masteryChange30d(
  value: number,
  lastEvidence: string | null,
  now = Date.now(),
) {
  const at = lastEvidence ? Date.parse(lastEvidence) : NaN;
  return finite(value) &&
    Number.isFinite(at) &&
    at <= now &&
    now - at <= 30 * 86400000
    ? `${value > 0 ? "+" : ""}${(value * 100).toFixed(1)}`
    : "—";
}
