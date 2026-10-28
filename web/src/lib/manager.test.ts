import { describe, expect, it } from "vitest";
import { analysisQuery, canAnalyze, defaultAnalysisDates, isStoreManager } from "./manager";

describe("manager filters and roles", () => {
  it("separates managers, admins and shoppers", () => {
    expect(isStoreManager("store_manager")).toBe(true);
    expect(isStoreManager("admin")).toBe(false);
    expect(canAnalyze("admin")).toBe(true);
    expect(canAnalyze("customer")).toBe(false);
    expect(canAnalyze("seller")).toBe(false);
  });
  it("uses 28 inclusive UTC dates across month boundaries", () => {
    expect(defaultAnalysisDates(new Date("2026-03-10T00:30:00Z"))).toEqual({ start_date: "2026-02-11", end_date: "2026-03-10" });
  });
  it("preserves analysis dates and drops stale category/search for a product link", () => {
    const input = new URLSearchParams("start_date=2026-01-01&end_date=2026-02-01&category=Books&search=hello&offset=80");
    const result = new URLSearchParams(analysisQuery(input, "product-id"));
    expect(result.get("start_date")).toBe("2026-01-01");
    expect(result.get("product_id")).toBe("product-id");
    expect(result.has("category")).toBe(false);
    expect(result.has("offset")).toBe(false);
    expect(result.has("search")).toBe(false);
  });
});
