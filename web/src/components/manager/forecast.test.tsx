import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ForecastRun } from "@/lib/manager-types";
import { ForecastPanel, ForecastResult, forecastScope, PerformanceTable } from "./forecast";

const api = vi.hoisted(() => ({ getAnalysisRuns: vi.fn(), getAnalysisRun: vi.fn(), createAnalysisRun: vi.fn() }));
vi.mock("@/lib/api", () => ({ api }));
vi.mock("@/components/ui/chart", () => ({ ChartContainer: ({ children }: { children: React.ReactNode }) => <div>{children}</div>, CHART_COLORS: ["red", "blue", "green"] }));

const report: ForecastRun = {
  id: "saved-run", engine_version: "v1", generated_at: "2026-01-01T00:00:00Z", data_fingerprint: "sha256",
  parameters: { as_of: "2025-12-31", horizon: 7 }, stock_baseline: "End of 2025-12-31 UTC", assumptions: [],
  summary: { product_count: 1, forecastable_products: 0, complete: false, growing: 0, declining: 0, slow_moving: 0, overstock: 0 },
  series: [], products: [{ product_id: "sku", name: "New book", category: "Books", performance: {
    trend: "insufficient_history", slow_moving: null, overstock: null, recent_units: 2, previous_units: null, growth_percent: null,
    consecutive_zero_days: 1, stock_at_cutoff: null, days_of_cover: null, no_recent_sales: false, comparison_days: 28,
    recent_start: null, previous_start: null, warnings: ["Insufficient history"],
  }, forecast: { available: false, reason: "Need more days", training_days: 2, warnings: [] } }],
};

beforeEach(() => {
  vi.clearAllMocks();
  api.getAnalysisRuns.mockResolvedValue({ runs: [], total: 0, offset: 0, limit: 20 });
  api.getAnalysisRun.mockResolvedValue(report);
});

describe("manager forecasting", () => {
  it("clamps today's filter to the last complete UTC day and keeps the selected SKU", () => {
    const today = new Date().toISOString().slice(0, 10);
    const scope = forecastScope(`end_date=${today}&product_id=sku&category=Books`);
    expect(scope.as_of < today).toBe(true);
    expect(scope.product_id).toBe("sku");
    expect(forecastScope("end_date=2025-10-01").as_of).toBe("2025-10-01");
  });
  it("shows unknown evidence without labelling the product slow-moving", () => {
    render(<PerformanceTable products={report.products.map((p) => ({ ...p, ...p.performance }))} />);
    expect(screen.getByText("insufficient history")).toBeVisible();
    expect(screen.queryByText("Slow-moving", { exact: true })).not.toBeInTheDocument();
    expect(screen.getByText("Insufficient history")).toBeVisible();
  });
  it("distinguishes unavailable forecasts from zero and partial totals", () => {
    render(<ForecastResult report={report} />);
    expect(screen.getByText(/Partial coverage/)).toBeVisible();
    fireEvent.change(screen.getByLabelText("Forecast product"), { target: { value: "sku" } });
    expect(screen.getAllByText("Need more days").length).toBeGreaterThan(0);
  });
  it("saves server-computed reports and reuses the request ID after a network failure", async () => {
    api.createAnalysisRun.mockRejectedValueOnce(new Error("Network interrupted")).mockResolvedValueOnce(report);
    render(<ForecastPanel query="end_date=2025-12-31&category=Books" />);
    fireEvent.change(screen.getByLabelText("Forecast horizon"), { target: { value: "7" } });
    fireEvent.click(screen.getByRole("button", { name: "Generate & save forecast" }));
    await screen.findByText("Network interrupted");
    fireEvent.click(screen.getByRole("button", { name: "Generate & save forecast" }));
    await screen.findByText("Saved report · 2025-12-31 · 7 days");
    expect(api.createAnalysisRun.mock.calls[0][0]).toEqual({ as_of: "2025-12-31", horizon: 7, category: "Books", product_id: null });
    expect(api.createAnalysisRun.mock.calls[0][1]).toBe(api.createAnalysisRun.mock.calls[1][1]);
    await waitFor(() => expect(api.getAnalysisRuns).toHaveBeenCalledTimes(2));
  });
  it("loads a saved report using the Agent's run link", async () => {
    render(<ForecastPanel query="" initialRunId="saved-run" />);
    await screen.findByText("Saved report · 2025-12-31 · 7 days");
    expect(api.getAnalysisRun).toHaveBeenCalledWith("saved-run", expect.any(AbortSignal));
  });
});
