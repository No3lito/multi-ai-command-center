/**
 * USD for budgets and costs. Whole cents use 2 decimals ($0.50, $10.00);
 * small amounts that are not whole cents use 4 decimals ($0.0123).
 */
export function formatUsd(value: number | null | undefined): string {
  const v = typeof value === "number" && Number.isFinite(value) ? value : 0;
  const abs = Math.abs(v);
  if (abs === 0) return "$0.00";
  const sign = v < 0 ? "-" : "";
  if (abs < 0.00005) return `${sign}<$0.0001`;
  const wholeCents = Math.abs(abs * 100 - Math.round(abs * 100)) < 1e-9;
  if (abs < 1 && !wholeCents) return `${sign}$${abs.toFixed(4)}`;
  return `${sign}$${abs.toFixed(2)}`;
}

export function formatCount(value: number | null | undefined): string {
  const v = typeof value === "number" && Number.isFinite(value) ? value : 0;
  return v.toLocaleString("en-US");
}
