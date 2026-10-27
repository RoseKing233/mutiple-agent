"use client";

import Link from "next/link";
import { useCallback } from "react";
import { useSearchParams } from "next/navigation";
import { BarChart3, Boxes, DollarSign, ShoppingBag, ArrowRight, Loader2 } from "lucide-react";
import { CartesianGrid, Line, LineChart, Tooltip, XAxis, YAxis } from "recharts";
import { api } from "@/lib/api";
import { canAnalyze, analysisQuery } from "@/lib/manager";
import { useAuth } from "@/lib/auth-context";
import { formatPrice } from "@/lib/format";
import type { ManagerAnalysis } from "@/lib/manager-types";
import { ChartContainer, CHART_COLORS } from "@/components/ui/chart";
import { StatCard } from "@/components/ui/stat-card";
import { AnalysisFilters } from "./filters";
import { useManagerResource } from "./resource";
import { ForecastPanel, PerformancePanel } from "./forecast";

export function ManagerGate({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuth();
  if (isLoading) return <Loading />;
  if (!canAnalyze(user?.role)) return <div className="p-8"><h1 className="text-xl font-semibold">Access denied</h1><p className="mt-2 text-muted-foreground">Store manager access is required.</p></div>;
  return children;
}

export function Loading() {
  return <div className="flex items-center gap-2 p-8 text-muted-foreground" role="status"><Loader2 className="size-4 animate-spin" />Loading analysis…</div>;
}

export function ErrorMessage({ error }: { error: string }) {
  return <div role="alert" className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">{error}</div>;
}

export function AnalysisStats({ data }: { data: ManagerAnalysis }) {
  const s = data.summary;
  return <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
    <StatCard label="Sales units" value={s.units.toLocaleString()} icon={BarChart3} hint="Non-cancelled; returns shown separately" />
    <StatCard label="Item sales amount" value={formatPrice(s.item_amount)} icon={DollarSign} hint="Before order discounts and refunds" />
    <StatCard label="Sales orders" value={s.order_count.toLocaleString()} icon={ShoppingBag} hint="Distinct non-cancelled orders" />
    <StatCard label="Current stock" value={s.current_stock.toLocaleString()} icon={Boxes} hint="Live balance across selected products" />
  </div>;
}

export function HistoryCharts({ data }: { data: ManagerAnalysis }) {
  return <div className="grid gap-5 xl:grid-cols-2">
    {([{ key: "units", title: "Daily sales", description: "Non-cancelled units by order date", color: 0 },
      { key: "closing_stock", title: "Inventory history", description: "End-of-day stock · gaps mean unknown", color: 1 }] as const).map((chart) =>
      <section key={chart.key} className="min-w-0 rounded-xl border bg-card p-5" aria-label={chart.title}>
        <h2 className="font-semibold">{chart.title}</h2><p className="mb-5 mt-1 text-xs text-muted-foreground">{chart.description}</p>
        {data.series.some((r) => r[chart.key] !== null) ? <ChartContainer height={260}>
          <LineChart accessibilityLayer data={data.series} margin={{ top: 8, right: 12, left: -18, bottom: 0 }}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="date" minTickGap={36} tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} tickFormatter={(v: string) => v.slice(5)} tickLine={false} axisLine={false} />
            <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: "var(--muted-foreground)" }} tickLine={false} axisLine={false} />
            <Tooltip contentStyle={{ background: "var(--popover)", border: "1px solid var(--border)", color: "var(--popover-foreground)", borderRadius: 8 }} />
            <Line dataKey={chart.key} name={chart.title} type="linear" stroke={CHART_COLORS[chart.color]} strokeWidth={2} dot={false} connectNulls={false} isAnimationActive={false} />
          </LineChart>
        </ChartContainer> : <p className="flex h-64 items-center justify-center text-sm text-muted-foreground">{chart.key === "units" ? "No recorded sales history in this period." : "Inventory history is not known for this period."}</p>}
      </section>)}
  </div>;
}

export function Dashboard() {
  const params = useSearchParams();
  const query = analysisQuery(new URLSearchParams(params.toString()));
  const catalogLoad = useCallback((signal: AbortSignal) => api.getManagerCatalog(signal), []);
  const analysisLoad = useCallback((signal: AbortSignal) => api.getManagerAnalysis(query, signal), [query]);
  const catalog = useManagerResource("catalog", catalogLoad);
  const result = useManagerResource(query, analysisLoad);
  const data = result.data;
  return <div className="mx-auto max-w-7xl space-y-6 p-4 sm:p-6 lg:p-8">
    <header className="flex flex-wrap items-center justify-between gap-4">
      <div><p className="text-xs font-medium uppercase tracking-widest text-primary">Store management</p><h1 className="mt-2 text-2xl font-semibold tracking-tight">Inventory &amp; Sales Analysis</h1><p className="mt-2 text-sm text-muted-foreground">Understand sales performance and stock movement across your store.</p></div>
      <Link href={`/products?${query}`} className="flex items-center gap-2 text-sm font-medium text-primary">View products<ArrowRight className="size-4" /></Link>
    </header>
    <AnalysisFilters key={query} query={query} catalog={catalog.data} />
    {catalog.error && <ErrorMessage error={catalog.error} />}
    {result.loading && <Loading />}
    {result.error && <ErrorMessage error={result.error} />}
    {data && <section id="history" className="space-y-6" aria-label="Historical analysis">
      <AnalysisStats data={data} />
      <div className="flex flex-wrap gap-x-6 gap-y-2 text-xs text-muted-foreground">
        <span>{data.summary.product_count} {data.summary.product_count === 1 ? "product" : "products"} selected</span><span>Cancelled: {data.summary.cancelled_units} units</span><span>Returned orders: {data.summary.returned_order_units} units</span><span>{data.summary.low_stock_products} products low in at least one warehouse</span>
      </div>
      {data.summary.product_count === 0 && <p className="rounded-lg border p-4 text-sm text-muted-foreground">No products match these filters.</p>}
      <HistoryCharts data={data} />
      <p className="text-xs leading-relaxed text-muted-foreground">Dates use UTC. {data.window.includes_partial_today && "Today is a partial day. "}Sales reflect current order status; returned orders remain included. Current stock is live and does not change with the historical date selection. Updated {new Date(data.generated_at).toLocaleString()}.</p>
    </section>}
    <PerformancePanel query={query} />
    <ForecastPanel key={`${query}:${params.get("run_id") || ""}`} query={query} initialRunId={params.get("run_id") || ""} />
  </div>;
}
