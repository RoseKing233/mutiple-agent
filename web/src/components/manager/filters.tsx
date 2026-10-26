"use client";

import { useState, type FormEvent } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { ManagerCatalog } from "@/lib/manager-types";

const selectClass = "h-9 w-full rounded-md border border-input bg-background px-3 text-sm";

export function AnalysisFilters({ query, catalog, mode = "analysis" }: {
  query: string; catalog: ManagerCatalog | null; mode?: "analysis" | "products" | "detail";
}) {
  const router = useRouter();
  const pathname = usePathname();
  const params = new URLSearchParams(query);
  const [category, setCategory] = useState(params.get("category") || "");
  const [product, setProduct] = useState(params.get("product_id") || "");
  const [error, setError] = useState<string | null>(null);
  function apply(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    if (String(values.get("start_date")) > String(values.get("end_date"))) {
      setError("Start date must not be after end date");
      return;
    }
    setError(null);
    const result = new URLSearchParams();
    for (const key of ["start_date", "end_date", "category", "product_id", "search"]) {
      const value = values.get(key)?.toString().trim();
      if (value) result.set(key, value);
    }
    router.replace(`${pathname}?${result}`);
  }
  return <form onSubmit={apply} className="flex flex-wrap items-end gap-3 rounded-xl border bg-card p-4" aria-label="Analysis filters">
    <label className="min-w-36 flex-1 text-xs font-medium">Start date (UTC)
      <input aria-label="Start date" name="start_date" type="date" required defaultValue={params.get("start_date") || ""} className={`${selectClass} mt-1`} />
    </label>
    <label className="min-w-36 flex-1 text-xs font-medium">End date (UTC)
      <input aria-label="End date" name="end_date" type="date" required defaultValue={params.get("end_date") || ""} className={`${selectClass} mt-1`} />
    </label>
    {mode !== "detail" && <label className="min-w-36 flex-1 text-xs font-medium">Category
      <select aria-label="Category" name="category" value={category} onChange={(e) => { setCategory(e.target.value); setProduct(""); }} className={`${selectClass} mt-1`}>
        <option value="">All categories</option>
        {catalog?.categories.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
    </label>}
    {mode === "analysis" && <label className="min-w-48 flex-1 text-xs font-medium">Product
      <select aria-label="Product" name="product_id" value={product} onChange={(e) => setProduct(e.target.value)} className={`${selectClass} mt-1`}>
        <option value="">All products</option>
        {catalog?.products.filter((p) => !category || p.category === category).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
      </select>
    </label>}
    {mode === "products" && <label className="min-w-44 flex-1 text-xs font-medium">Product name or brand
      <Input name="search" aria-label="Search products" defaultValue={params.get("search") || ""} placeholder="Search products" className="mt-1" />
    </label>}
    <Button type="submit">Apply filters</Button>
    {error && <p role="alert" className="w-full text-sm text-destructive">{error}</p>}
  </form>;
}
