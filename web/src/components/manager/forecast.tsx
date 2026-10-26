"use client";

import { useCallback, useRef, useState } from "react";
import { CartesianGrid, Line, LineChart, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "@/lib/api";
import type { ForecastParameters, ForecastPoint, ForecastRun, PerformanceReport } from "@/lib/manager-types";
import { Button } from "@/components/ui/button";
import { ChartContainer, CHART_COLORS } from "@/components/ui/chart";
import { useManagerResource } from "./resource";

const field = "rounded-md border bg-background px-3 py-2 text-sm";
const fmt = (value: number | null | undefined) => value == null ? "Unknown" : value.toLocaleString(undefined, { maximumFractionDigits: 1 });
const words = (value: string) => value.replaceAll("_", " ");

export function forecastScope(query: string): ForecastParameters {
  const params = new URLSearchParams(query);
  const yesterday = new Date();
  yesterday.setUTCDate(yesterday.getUTCDate() - 1);
  const latest = yesterday.toISOString().slice(0, 10);
  const requested = params.get("end_date") || latest;
  return { as_of: requested < latest ? requested : latest, horizon: 14,
    product_id: params.get("product_id") || null, category: params.get("category") || null };
}

function Notice({ children, error = false }: { children: React.ReactNode; error?: boolean }) {
  return <p role={error ? "alert" : "status"} className={`rounded-lg border p-3 text-sm ${error ? "text-destructive" : "text-muted-foreground"}`}>{children}</p>;
}

export function PerformanceTable({ products }: Pick<PerformanceReport, "products">) {
  return <div className="max-h-96 overflow-auto rounded-lg border">
    <table className="w-full text-left text-sm" aria-label="Product performance classification">
      <thead className="sticky top-0 bg-muted"><tr>{["Product", "Trend", "Recent / prior units", "Change", "Stock / cover days", "Flags & evidence"].map((v) => <th className="whitespace-nowrap p-3 font-medium" key={v}>{v}</th>)}</tr></thead>
      <tbody>{products.map((p) => <tr key={p.product_id} className="border-t align-top">
        <td className="min-w-40 p-3">{p.name}</td><td className="p-3">{words(p.trend)}</td>
        <td className="p-3">{fmt(p.recent_units)} / {fmt(p.previous_units)}<span className="block text-xs text-muted-foreground">{p.comparison_days} days each</span></td>
        <td className="p-3">{p.growth_percent == null ? "—" : `${fmt(p.growth_percent)}%`}</td>
        <td className="p-3">{fmt(p.stock_at_cutoff)} / {fmt(p.days_of_cover)}</td>
        <td className="min-w-60 p-3 text-xs leading-relaxed">
          {p.slow_moving && <span className="mr-2 font-semibold text-primary">Slow-moving</span>}
          {p.overstock && <span className="mr-2 font-semibold text-primary">Overstock</span>}
          {p.no_recent_sales && <span className="mr-2">No recent sales</span>}
          {p.slow_moving === false && p.overstock === false && !p.no_recent_sales && "No slow-moving or overstock flag"}
          {p.warnings.map((warning) => <span className="block text-muted-foreground" key={warning}>{warning}</span>)}
        </td>
      </tr>)}</tbody>
    </table>
    {!products.length && <p className="p-4 text-sm text-muted-foreground">No products match this scope.</p>}
  </div>;
}

export function PerformancePanel({ query }: { query: string }) {
  const scope = forecastScope(query);
  const params = new URLSearchParams({ as_of: scope.as_of });
  if (scope.category) params.set("category", scope.category);
  if (scope.product_id) params.set("product_id", scope.product_id);
  const key = params.toString();
  const load = useCallback((signal: AbortSignal) => api.getManagerPerformance(key, signal), [key]);
  const result = useManagerResource(key, load);
  return <section className="min-w-0 space-y-4 rounded-xl border bg-card p-5" aria-label="Product performance">
    <h2 className="font-semibold">Product performance</h2>
    <p className="text-xs leading-relaxed text-muted-foreground">Through {scope.as_of} UTC. Compares 28 days with the preceding 28 days; growth/decline requires ±15% and at least 5 units. Slow-moving: ≤3 units or 14 days without sales. Overstock: ≥5 units and over 60 days of cover. Stockouts and unknown history can withhold flags.</p>
    {result.loading && <Notice>Loading product performance…</Notice>}
    {result.error && <Notice error>{result.error}</Notice>}
    {result.data && <PerformanceTable products={result.data.products} />}
  </section>;
}

function ForecastChart({ series, stock = false, partial = false }: { series: ForecastPoint[]; stock?: boolean; partial?: boolean }) {
  const key = stock ? "stock" : partial ? "available_product_units" : "units";
  return <section className="min-w-0 rounded-lg border p-4" aria-label={stock ? "Projected stock chart" : "Forecast sales chart"}>
    <h3 className="mb-4 text-sm font-medium">{stock ? "Projected closing stock" : partial ? "Forecast sales · available products only" : "Forecast daily sales"}</h3>
    {series.some((r) => r[key] != null) ? <ChartContainer height={250}>
      <LineChart accessibilityLayer data={series} margin={{ left: -20, right: 10, top: 8 }}>
        <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="date" minTickGap={25} tickFormatter={(v: string) => v.slice(5)} tick={{ fontSize: 11 }} />
        <YAxis tick={{ fontSize: 11 }} />
        <Tooltip formatter={(value) => fmt(Number(value))} contentStyle={{ background: "var(--popover)", color: "var(--popover-foreground)", border: "1px solid var(--border)", borderRadius: 8 }} />
        <Line type="linear" dataKey={key} name={stock ? "Stock" : "Expected units"} stroke={CHART_COLORS[stock ? 1 : 0]} dot={false} isAnimationActive={false} connectNulls={false} />
        {!stock && <Line dataKey="lower_units" name="Lower empirical scenario" stroke={CHART_COLORS[2]} dot={false} strokeDasharray="4 4" isAnimationActive={false} />}
        {!stock && <Line dataKey="upper_units" name="Upper empirical scenario" stroke={CHART_COLORS[2]} dot={false} strokeDasharray="4 4" isAnimationActive={false} />}
      </LineChart>
    </ChartContainer> : <p className="flex h-60 items-center justify-center text-sm text-muted-foreground">Insufficient data for this curve.</p>}
  </section>;
}

export function ForecastResult({ report }: { report: ForecastRun }) {
  const [productId, setProductId] = useState("");
  const product = report.products.find((p) => p.product_id === productId);
  const series = product ? product.forecast.series || [] : report.series;
  const f = product?.forecast;
  return <div className="space-y-4" aria-label="Saved forecast result">
    <div className="rounded-lg bg-muted/50 p-4 text-sm leading-relaxed">
      <p className="font-medium">Saved report · {report.parameters.as_of} · {report.parameters.horizon} days</p>
      <p className="text-muted-foreground">{report.stock_baseline}. No future replenishment or returns assumed.</p>
      <p className="text-xs text-muted-foreground">{report.engine_version} · Generated {new Date(report.generated_at).toLocaleString()}</p>
      <p className="text-xs text-muted-foreground">{report.parameters.category || "All categories"} · {report.summary.product_count} products · {report.summary.forecastable_products} forecastable</p>
      {!report.summary.complete && <p className="mt-2 text-destructive">Partial coverage: unavailable products are not treated as zero. The store-wide total and stock curve are withheld.</p>}
    </div>
    <label className="flex flex-wrap items-center gap-3 text-sm">Forecast product
      <select aria-label="Forecast product" className={`${field} max-w-full`} value={productId} onChange={(e) => setProductId(e.target.value)}>
        <option value="">Selected scope (aggregate)</option>{report.products.map((p) => <option key={p.product_id} value={p.product_id}>{p.name}</option>)}
      </select>
    </label>
    <div className="grid gap-4 xl:grid-cols-2"><ForecastChart series={series} partial={!product && !report.summary.complete} /><ForecastChart series={series} stock /></div>
    {f && <div className="space-y-2 text-sm">
      {f.available ? <><p>Model: <strong>{f.model}</strong> · {f.training_days} training days · Reliability: {f.reliability}</p>
        <p>Stockout: {words(f.stockout_status || "unknown")} {f.stockout_date && `(${f.stockout_date})`} · Potential unmet units: {fmt(f.unmet_units)}</p>
        <p className="text-xs text-muted-foreground">{f.uncertainty}</p>
        {(f.earlier_stockout_scenario || f.later_stockout_scenario) && <p className="text-xs text-muted-foreground">Higher-demand depletion scenario: {f.earlier_stockout_scenario || "not within horizon"}; lower-demand scenario: {f.later_stockout_scenario || "not within horizon"}.</p>}
      </> : <Notice>{f.reason}</Notice>}
      {f.warnings.map((warning) => <p key={warning} className="text-xs text-muted-foreground">{warning}</p>)}
      {f.backtest && <details className="rounded-lg border p-3"><summary className="cursor-pointer">Model comparison & backtest errors</summary>
        <p className="my-2 text-xs text-muted-foreground">{f.backtest.note}. Lower MAE is better; cumulative error is measured over the whole horizon.</p>
        <div className="overflow-auto"><table className="w-full text-left text-xs"><thead><tr>{["Candidate", "Daily MAE", "Horizon total MAE", "Folds"].map((v) => <th className="p-2" key={v}>{v}</th>)}</tr></thead>
          <tbody>{f.backtest.scores.map((score) => <tr key={score.model}><td className="p-2">{score.model}</td><td>{fmt(score.mae)}</td><td>{fmt(score.horizon_total_mae)}</td><td>{score.folds}</td></tr>)}</tbody></table></div>
      </details>}
    </div>}
    <div className="max-h-80 overflow-auto rounded-lg border"><table className="w-full text-left text-sm" aria-label="Forecast stockout risks">
      <thead className="sticky top-0 bg-muted"><tr>{["Product", "Model / availability", "Forecast units", "Stockout risk"].map((v) => <th className="whitespace-nowrap p-3" key={v}>{v}</th>)}</tr></thead>
      <tbody>{report.products.map((p) => <tr key={p.product_id} className="border-t"><td className="min-w-40 p-3"><button className="text-left text-primary underline underline-offset-4" onClick={() => setProductId(p.product_id)}>{p.name}</button></td><td className="p-3 text-xs">{p.forecast.model || p.forecast.reason}</td>
        <td className="p-3">{p.forecast.available ? fmt(p.forecast.series?.reduce((sum, row) => sum + (row.units || 0), 0)) : "Unavailable"}</td>
        <td className="p-3 text-xs">{words(p.forecast.stockout_status || "unavailable")} {p.forecast.stockout_date || ""}</td></tr>)}</tbody>
    </table></div>
    <details className="rounded-lg border p-3 text-sm"><summary className="cursor-pointer">Saved performance, assumptions & reproducibility</summary>
      <div className="mt-3"><PerformanceTable products={report.products.map((p) => ({ product_id: p.product_id, name: p.name, category: p.category, ...p.performance }))} /></div>
      <ul className="my-3 list-inside list-disc space-y-1 text-xs text-muted-foreground">{report.assumptions.map((s) => <li key={s}>{s}</li>)}</ul>
      <p className="break-all text-xs text-muted-foreground">Report ID: {report.id}<br />Data fingerprint: {report.data_fingerprint}<br />Rules: {JSON.stringify(report.parameters.rules)}</p>
    </details>
  </div>;
}

export function ForecastPanel({ query, initialRunId = "" }: { query: string; initialRunId?: string }) {
  const scope = forecastScope(query);
  const [horizon, setHorizon] = useState<7 | 14 | 28>(14);
  const [report, setReport] = useState<ForecastRun | null>(null);
  const [selectedRun, setSelectedRun] = useState(initialRunId);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  const [offset, setOffset] = useState(0);
  const request = useRef<{ signature: string; id: string } | null>(null);
  const savedLoad = useCallback((signal: AbortSignal) => api.getAnalysisRuns(offset, signal), [offset]);
  const saved = useManagerResource(`${offset}:${revision}`, savedLoad);
  const runLoad = useCallback((signal: AbortSignal) => selectedRun ? api.getAnalysisRun(selectedRun, signal) : Promise.resolve(null), [selectedRun]);
  const loaded = useManagerResource(selectedRun, runLoad);
  const displayed = report || loaded.data;
  async function generate() {
    if (pending) return;
    setPending(true); setError("");
    const parameters = { ...scope, horizon };
    const signature = JSON.stringify(parameters);
    if (request.current?.signature !== signature) request.current = { signature, id: crypto.randomUUID() };
    try {
      const result = await api.createAnalysisRun(parameters, request.current.id);
      setReport(result); setSelectedRun(""); setRevision((v) => v + 1); request.current = null;
    } catch (e) { setError(e instanceof Error ? e.message : "Unable to generate forecast"); }
    finally { setPending(false); }
  }
  return <section id="forecast" className="min-w-0 space-y-5 rounded-xl border bg-card p-5" aria-label="Sales and inventory forecasting">
    <h2 className="font-semibold">Sales &amp; inventory forecast</h2>
    <p className="text-sm text-muted-foreground">Cutoff: {scope.as_of} UTC. Forecasting uses up to 180 complete days; the chart start date does not shorten training. Generating a forecast also saves its performance analysis and assumptions. Actual inventory is unchanged.</p>
    <div className="flex flex-wrap items-center gap-3"><label className="flex items-center gap-2 text-sm">Forecast horizon
      <select aria-label="Forecast horizon" className={field} value={horizon} disabled={pending} onChange={(e) => setHorizon(Number(e.target.value) as 7 | 14 | 28)}>{[7, 14, 28].map((n) => <option key={n} value={n}>{n} days</option>)}</select>
    </label><Button disabled={pending} onClick={generate}>{pending ? "Calculating and saving…" : "Generate & save forecast"}</Button></div>
    {error && <Notice error>{error}</Notice>}
    {loaded.error && <Notice error>{loaded.error}</Notice>}
    {selectedRun && loaded.loading && <Notice>Loading saved forecast…</Notice>}
    {displayed && <ForecastResult key={displayed.id} report={displayed} />}
    <div className="space-y-3 border-t pt-5"><h3 className="font-medium">Your saved analyses</h3>
      <p className="text-xs text-muted-foreground">Each snapshot retains its own dates and scope. Opening it does not recompute it from current data.</p>
      {saved.error && <Notice error>{saved.error}</Notice>}
      {saved.loading && <Notice>Loading saved analyses…</Notice>}
      {saved.data && <><div className="max-h-64 overflow-auto">{saved.data.runs.length ? saved.data.runs.map((run) => <div className="flex flex-wrap items-center justify-between gap-2 border-b py-3 text-sm" key={run.id}>
        <span>{run.as_of} · {run.horizon} days · {run.parameters.category || "All categories"} · {run.summary.product_count} products<span className="block text-xs text-muted-foreground">{new Date(run.created_at).toLocaleString()}</span></span>
        <Button variant="outline" size="sm" disabled={pending} onClick={() => { setReport(null); setSelectedRun(run.id); }}>Open saved report</Button>
      </div>) : <p className="text-sm text-muted-foreground">No saved reports yet.</p>}</div>
      <div className="flex items-center gap-3"><Button variant="outline" size="sm" disabled={!offset} onClick={() => setOffset(Math.max(0, offset - 20))}>Previous reports</Button><span className="text-xs text-muted-foreground">{saved.data.total} saved reports</span><Button variant="outline" size="sm" disabled={offset + 20 >= saved.data.total} onClick={() => setOffset(offset + 20)}>Next reports</Button></div></>}
    </div>
  </section>;
}
