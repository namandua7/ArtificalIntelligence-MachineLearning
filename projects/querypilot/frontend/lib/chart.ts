import type { ChartSpec } from "@/lib/api";

/** Pick a sensible chart when the agent didn't (or the user switches type). */
export function inferChart(columns: string[], rows: unknown[][]): ChartSpec {
  if (rows.length < 2 || columns.length < 2) return { type: "none" };
  const numeric = columns.filter((_, i) => rows.every((r) => r[i] === null || typeof r[i] === "number"));
  const label = columns.find((c) => !numeric.includes(c)) ?? columns[0];
  const y = numeric.filter((c) => c !== label && !/(^|_)id$/i.test(c)).slice(0, 3);
  if (!y.length) return { type: "none" };
  const xi = columns.indexOf(label);
  const isTime = rows.every((r) => typeof r[xi] === "string" && /^\d{4}-\d{2}/.test(r[xi] as string));
  return { type: isTime ? "line" : "bar", x: label, y };
}
