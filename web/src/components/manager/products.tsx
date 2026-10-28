"use client";

import Link from "next/link";
import { useCallback } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { analysisQuery } from "@/lib/manager";
import { formatPrice } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { AnalysisFilters } from "./filters";
import { AnalysisStats, HistoryCharts, ErrorMessage, Loading } from "./dashboard";
import { useManagerResource } from "./resource";

const cell = "px-4 py-3 text-left text-sm";

function Pagination({ offset, total, limit, href }: { offset: number; total: number; limit: number; href: (offset: number) => string }) {
  return <div className="flex items-center justify-between gap-3 pt-4 text-sm">
    <span className="text-muted-foreground">{total === 0 ? "0" : `${offset + 1}–${Math.min(offset + limit, total)}`} of {total}</span>
    <div className="flex gap-2">
      <Button variant="outline" size="sm" disabled={offset === 0} render={offset > 0 ? <Link href={href(Math.max(0, offset - limit))} /> : undefined}>Previous</Button>
      <Button variant="outline" size="sm" disabled={offset + limit >= total} render={offset + limit < total ? <Link href={href(offset + limit)} /> : undefined}>Next</Button>
    </div>
  </div>;
}

export function ManagerProducts() {
  const params = useSearchParams();
  const query = analysisQuery(new URLSearchParams(params.toString()));
  const rawOffset = Number(params.get("offset") || 0);
  const offset = Number.isSafeInteger(rawOffset) && rawOffset >= 0 ? rawOffset : 0;
  const request = `${query}&offset=${offset}&limit=20`;
  const catalogLoad = useCallback((signal: AbortSignal) => api.getManagerCatalog(signal), []);
  const productsLoad = useCallback((signal: AbortSignal) => api.getManagerProducts(request, signal), [request]);
  const catalog = useManagerResource("catalog", catalogLoad);
  const result = useManagerResource(request, productsLoad);
  return <div className="mx-auto max-w-7xl space-y-6 p-4 sm:p-6 lg:p-8">
    <header className="flex flex-wrap items-center justify-between gap-4"><div><p className="text-xs uppercase tracking-widest text-primary">Store management</p><h1 className="mt-2 text-2xl font-semibold">Products</h1><p className="mt-2 text-sm text-muted-foreground">Compare sales for your selected period with current stock.</p></div><Link href={`/analysis?${query}`} className="text-sm font-medium text-primary">Open analysis →</Link></header>
    <AnalysisFilters key={query} query={query} catalog={catalog.data} mode="products" />
    {catalog.error && <ErrorMessage error={catalog.error} />}
    {result.loading && <Loading />}{result.error && <ErrorMessage error={result.error} />}
    {result.data && <div>
      <div className="overflow-x-auto rounded-xl border bg-card"><table className="w-full"><caption className="sr-only">Product sales and current inventory</caption>
        <thead className="border-b bg-muted/40"><tr>{["Product", "Category", "Price", "Current stock", "Sales units", "Item amount", "Orders", ""].map((label) => <th key={label} className={`${cell} whitespace-nowrap font-medium text-muted-foreground`}>{label}</th>)}</tr></thead>
        <tbody>{result.data.products.map((p) => <tr key={p.id} className="border-b last:border-0 hover:bg-muted/30">
          <td className={cell}><Link href={`/products/${p.id}?${query}`} className="font-medium text-primary hover:underline">{p.name}</Link><p className="mt-1 text-xs text-muted-foreground">{p.brand}{!p.is_active && " · Inactive"}</p></td>
          <td className={cell}>{p.category}</td><td className={`${cell} whitespace-nowrap`}>{formatPrice(p.price)}</td>
          <td className={cell}><span className="tabular-nums">{p.current_stock}</span>{p.low_stock && <span className="ml-2 text-xs text-warning">Low stock</span>}</td>
          <td className={cell}>{p.units}</td><td className={`${cell} whitespace-nowrap`}>{formatPrice(p.item_amount)}</td><td className={cell}>{p.order_count}</td>
          <td className={cell}><Link href={`/analysis?${analysisQuery(new URLSearchParams(query), p.id)}`} className="text-primary hover:underline">Analyze</Link></td>
        </tr>)}</tbody>
      </table>{result.data.products.length === 0 && <p className="p-8 text-center text-sm text-muted-foreground">No products match these filters.</p>}</div>
      <Pagination offset={offset} total={result.data.total} limit={20} href={(next) => `/products?${query}&offset=${next}`} />
      <p className="mt-4 text-xs leading-relaxed text-muted-foreground">Sales units exclude cancelled orders; returns are included. Item amounts are before order discounts and refunds. Current stock always shows the live balance.</p>
    </div>}
  </div>;
}

export function ManagerProductDetail() {
  const { id } = useParams<{ id: string }>();
  const params = useSearchParams();
  const query = analysisQuery(new URLSearchParams(params.toString()), id);
  const rawOffset = Number(params.get("offset") || 0);
  const offset = Number.isSafeInteger(rawOffset) && rawOffset >= 0 ? rawOffset : 0;
  const analysisLoad = useCallback((signal: AbortSignal) => api.getManagerAnalysis(query, signal), [query]);
  const ordersQuery = `${query}&offset=${offset}&limit=10`;
  const ordersLoad = useCallback((signal: AbortSignal) => api.getManagerOrders(id, ordersQuery, signal), [id, ordersQuery]);
  const analysis = useManagerResource(query, analysisLoad);
  const orders = useManagerResource(ordersQuery, ordersLoad);
  const product = analysis.data?.products[0];
  return <div className="mx-auto max-w-7xl space-y-6 p-4 sm:p-6 lg:p-8">
    <Link href={`/products?${query.replace(/&?product_id=[^&]*/g, "")}`} className="text-sm text-primary">← All products</Link>
    <header className="flex flex-wrap items-start justify-between gap-4"><div><h1 className="text-2xl font-semibold">{product?.name || "Product performance"}</h1>{product && <p className="mt-2 text-sm text-muted-foreground">{product.category} · {formatPrice(product.price)} · {product.is_active ? "Active" : "Inactive"}</p>}</div><Link href={`/analysis?${query}`} className="text-sm font-medium text-primary">Open analysis →</Link></header>
    <AnalysisFilters key={query} query={query} catalog={null} mode="detail" />
    {analysis.loading && <Loading />}{analysis.error && <ErrorMessage error={analysis.error} />}
    {analysis.data && <>
      {product?.description && <p className="max-w-3xl text-sm leading-relaxed text-muted-foreground">{product.description}</p>}
      <AnalysisStats data={analysis.data} /><HistoryCharts data={analysis.data} />
      <section className="rounded-xl border bg-card p-5"><h2 className="font-semibold">Current stock by warehouse</h2><div className="mt-4 grid gap-3 sm:grid-cols-3">{analysis.data.warehouses.map((w) => <div key={w.id} className="rounded-lg bg-muted/40 p-4"><p className="text-sm font-medium">{w.name}</p><p className="mt-2 text-xl font-semibold tabular-nums">{w.quantity}</p><p className="mt-1 text-xs text-muted-foreground">{w.quantity <= w.reorder_threshold ? "Low stock" : "Available"} · threshold {w.reorder_threshold}</p></div>)}</div></section>
    </>}
    <section className="rounded-xl border bg-card p-5"><h2 className="font-semibold">Related sales orders</h2><p className="mt-1 text-xs text-muted-foreground">Read-only · selected period · amount for this product only · all order statuses</p>
      {orders.loading && <Loading />}{orders.error && <ErrorMessage error={orders.error} />}
      {orders.data && <><div className="mt-4 overflow-x-auto"><table className="w-full"><thead><tr>{["Order", "Ordered at (UTC)", "Quantity", "Item amount", "Status"].map((label) => <th key={label} className={`${cell} font-medium text-muted-foreground`}>{label}</th>)}</tr></thead><tbody>{orders.data.orders.map((o) => <tr key={o.id} className="border-t"><td className={`${cell} font-mono`}>#{o.id.slice(0, 8)}</td><td className={`${cell} whitespace-nowrap`}>{o.created_at.slice(0, 19).replace("T", " ")}</td><td className={cell}>{o.quantity}</td><td className={cell}>{formatPrice(o.item_amount)}</td><td className={cell}>{o.status.replaceAll("_", " ")}</td></tr>)}</tbody></table>{orders.data.total === 0 && <p className="p-6 text-sm text-muted-foreground">No orders in this period.</p>}</div><Pagination offset={offset} total={orders.data.total} limit={10} href={(next) => `/products/${id}?${query}&offset=${next}`} /></>}
    </section>
  </div>;
}
