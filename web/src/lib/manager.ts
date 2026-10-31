export function isStoreManager(role?: string): boolean {
  return role === "store_manager";
}

export function canAnalyze(role?: string): boolean {
  return isStoreManager(role);
}

export function defaultAnalysisDates(now = new Date()) {
  const end = new Date(now);
  const start = new Date(now);
  start.setUTCDate(start.getUTCDate() - 27);
  return { start_date: start.toISOString().slice(0, 10), end_date: end.toISOString().slice(0, 10) };
}

/** Only supported, nonempty filters are forwarded; pagination resets separately. */
export function analysisQuery(params: URLSearchParams, productId?: string): string {
  const dates = defaultAnalysisDates();
  const result = new URLSearchParams();
  result.set("start_date", params.get("start_date") || dates.start_date);
  result.set("end_date", params.get("end_date") || dates.end_date);
  for (const key of ["category", "product_id", "search"]) {
    const value = params.get(key);
    if (value) result.set(key, value);
  }
  if (productId) {
    result.set("product_id", productId);
    result.delete("category");
    result.delete("search");
  }
  return result.toString();
}
