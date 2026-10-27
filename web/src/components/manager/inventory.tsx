"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, RefreshCw, Sparkles } from "lucide-react";
import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ErrorMessage } from "./dashboard";

/* Minimal manager page for inventory suggestions and CRUD. Styling is intentionally plain;
   the Friday frontend pass will restyle it. Every write goes through /api/manager. */

interface Suggestion {
  id: string;
  product_name: string;
  suggestion_type: "restock" | "overstock";
  priority: "high" | "medium" | "low";
  suggested_quantity: number;
  warehouse_id: string | null;
  warehouse_name: string | null;
  rationale: string;
  rationale_source: "ai" | "rule";
  evidence: Record<string, unknown>;
}
interface InventoryItem {
  product_id: string;
  product_name: string;
  category: string;
  product_active: boolean;
  warehouse_id: string;
  warehouse_name: string;
  warehouse_active: boolean;
  quantity: number;
  reorder_threshold: number;
  low_stock: boolean;
}
interface Movement {
  id: number;
  movement_type: string;
  quantity_delta: number;
  balance_after: number;
  occurred_at: string;
  notes: string;
}
interface Warehouse {
  id: string;
  name: string;
  location: string;
  region: string;
  is_active: boolean;
  total_quantity: number;
}
interface ProductRow {
  id: string;
  name: string;
  category: string;
  is_active: boolean;
  current_stock: number;
}

const newId = () => crypto.randomUUID();

function useLoad<T>(load: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reload = useCallback(() => {
    load().then((d) => { setData(d); setError(null); }, (e: Error) => setError(e.message));
  }, [load]);
  useEffect(reload, [reload]);
  return { data, error, reload };
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="flex flex-col gap-1 text-xs text-muted-foreground">{label}{children}</label>;
}

const selectClass = "h-8 rounded-lg border border-input bg-background px-2 text-sm";

export function InventoryPage() {
  const [tab, setTab] = useState<"suggestions" | "stock" | "setup">("suggestions");
  const tabs = [["suggestions", "Suggestions"], ["stock", "Stock"], ["setup", "Warehouses & products"]] as const;
  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-4 p-4 sm:p-6">
      <div>
        <h1 className="text-xl font-semibold">Inventory</h1>
        <p className="text-sm text-muted-foreground">
          Quantities come from code and the sales forecast; AI only writes the explanation. Nothing changes stock until you act.
        </p>
      </div>
      <div className="flex gap-1 border-b" role="tablist">
        {tabs.map(([key, label]) => (
          <button key={key} role="tab" aria-selected={tab === key} onClick={() => setTab(key)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm ${tab === key ? "border-primary font-medium" : "border-transparent text-muted-foreground"}`}>
            {label}
          </button>
        ))}
      </div>
      {tab === "suggestions" && <SuggestionsTab />}
      {tab === "stock" && <StockTab />}
      {tab === "setup" && <SetupTab />}
    </div>
  );
}

// ── Suggestions ─────────────────────────────────────────────────────────────

function SuggestionsTab() {
  const load = useCallback(() => api.inventory<{ suggestions: Suggestion[] }>("/inventory-suggestions?limit=100"), []);
  const { data, error, reload } = useLoad(load);
  const warehouses = useLoad(useCallback(() => api.inventory<{ warehouses: Warehouse[] }>("/warehouses"), []));
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  async function generate() {
    setBusy(true);
    setMessage(null);
    try {
      const r = await api.inventory<{ summary: Record<string, number>; ai_rationale: string }>(
        "/inventory-suggestions/generate", "POST", { use_ai: true });
      setMessage(`Generated ${r.summary.restock} restock and ${r.summary.overstock} overstock suggestions (AI explanation: ${r.ai_rationale}).`);
      reload();
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Button onClick={generate} disabled={busy}>
          {busy ? <Loader2 className="animate-spin" /> : <Sparkles />}Generate suggestions
        </Button>
        <Button variant="outline" onClick={reload}><RefreshCw />Refresh</Button>
        {message && <span className="text-sm text-muted-foreground">{message}</span>}
      </div>
      {error && <ErrorMessage error={error} />}
      {data && data.suggestions.length === 0 && <p className="text-sm text-muted-foreground">No pending suggestions.</p>}
      {data?.suggestions.map((s) => (
        <SuggestionCard key={s.id} s={s} warehouses={warehouses.data?.warehouses ?? []} onDone={reload} />
      ))}
    </div>
  );
}

function SuggestionCard({ s, warehouses, onDone }: { s: Suggestion; warehouses: Warehouse[]; onDone: () => void }) {
  const [quantity, setQuantity] = useState(s.suggested_quantity);
  const [warehouseId, setWarehouseId] = useState(s.warehouse_id ?? warehouses.find((w) => w.is_active)?.id ?? "");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const restock = s.suggestion_type === "restock";

  async function decide(decision: "accept" | "reject") {
    setBusy(true);
    setError(null);
    try {
      await api.inventory(`/inventory-suggestions/${s.id}/decision`, "POST", {
        decision, note,
        ...(decision === "accept" && restock ? { quantity, warehouse_id: warehouseId || null } : {}),
      });
      onDone();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const e = s.evidence;
  return (
    <div className="rounded-lg border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{s.product_name}</span>
        <Badge variant={restock ? "default" : "secondary"}>{restock ? "Restock" : "Overstock"}</Badge>
        <Badge variant={s.priority === "high" ? "destructive" : "outline"}>{s.priority}</Badge>
        <span className="text-sm text-muted-foreground">
          {restock ? `Order ${s.suggested_quantity} → ${s.warehouse_name ?? "choose warehouse"}` : `${s.suggested_quantity} excess units`}
        </span>
      </div>
      <p className="mt-2 text-sm">{s.rationale}</p>
      <p className="mt-1 text-xs text-muted-foreground">
        {s.rationale_source === "ai" ? "Explanation by AI (numbers verified against evidence)" : "Rule-based explanation"} ·
        live stock {String(e.live_stock)} · forecast {e.forecast_units == null ? "n/a" : String(e.forecast_units)} units /{" "}
        {String(e.horizon_days)} days{e.projected_stockout_date ? ` · runs out ${String(e.projected_stockout_date)}` : ""}
      </p>
      <div className="mt-3 flex flex-wrap items-end gap-2">
        {restock && (
          <>
            <Field label="Quantity">
              <Input type="number" min={1} className="w-24" value={quantity} onChange={(ev) => setQuantity(Number(ev.target.value))} />
            </Field>
            <Field label="Warehouse">
              <select className={selectClass} value={warehouseId} onChange={(ev) => setWarehouseId(ev.target.value)}>
                {warehouses.filter((w) => w.is_active).map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
              </select>
            </Field>
          </>
        )}
        <Field label="Note (optional)">
          <Input className="w-56" value={note} onChange={(ev) => setNote(ev.target.value)} />
        </Field>
        <Button disabled={busy || (restock && quantity < 1)} onClick={() => decide("accept")}>
          {restock ? "Accept & receive stock" : "Accept"}
        </Button>
        <Button variant="outline" disabled={busy} onClick={() => decide("reject")}>Reject</Button>
      </div>
      {error && <p className="mt-2 text-sm text-destructive">{error}</p>}
    </div>
  );
}

// ── Stock ───────────────────────────────────────────────────────────────────

function StockTab() {
  const [search, setSearch] = useState("");
  const [lowOnly, setLowOnly] = useState(false);
  const load = useCallback(() => {
    const q = new URLSearchParams({ limit: "200", low_stock_only: String(lowOnly) });
    if (search) q.set("search", search);
    return api.inventory<{ items: InventoryItem[]; total: number }>(`/inventory?${q}`);
  }, [search, lowOnly]);
  const { data, error, reload } = useLoad(load);
  const [open, setOpen] = useState<string | null>(null);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <Input placeholder="Search product or brand" className="w-64" value={search} onChange={(e) => setSearch(e.target.value)} />
        <label className="flex items-center gap-1 text-sm">
          <input type="checkbox" checked={lowOnly} onChange={(e) => setLowOnly(e.target.checked)} />Low stock only
        </label>
        <AddInventoryRow onDone={reload} />
      </div>
      {error && <ErrorMessage error={error} />}
      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full text-sm">
          <thead className="bg-muted/50 text-left text-xs text-muted-foreground">
            <tr><th className="p-2">Product</th><th className="p-2">Warehouse</th><th className="p-2 text-right">Qty</th>
              <th className="p-2 text-right">Threshold</th><th className="p-2">Status</th><th className="p-2" /></tr>
          </thead>
          <tbody>
            {data?.items.map((i) => {
              const key = `${i.product_id}/${i.warehouse_id}`;
              return (
                <StockRow key={key} item={i} open={open === key} onToggle={() => setOpen(open === key ? null : key)} onDone={reload} />
              );
            })}
          </tbody>
        </table>
      </div>
      {data && <p className="text-xs text-muted-foreground">{data.total} inventory rows</p>}
    </div>
  );
}

function StockRow({ item, open, onToggle, onDone }: { item: InventoryItem; open: boolean; onToggle: () => void; onDone: () => void }) {
  const path = `/inventory/${item.product_id}/${item.warehouse_id}`;
  const [kind, setKind] = useState("manual_receipt");
  const [quantity, setQuantity] = useState(1);
  const [reason, setReason] = useState("");
  const [threshold, setThreshold] = useState(item.reorder_threshold);
  const [error, setError] = useState<string | null>(null);
  const [movements, setMovements] = useState<Movement[] | null>(null);

  useEffect(() => {
    if (open) api.inventory<{ movements: Movement[] }>(`${path}/movements?limit=10`).then((r) => setMovements(r.movements), () => setMovements([]));
  }, [open, path]);

  async function run(action: () => Promise<unknown>) {
    setError(null);
    try { await action(); onDone(); } catch (e) { setError((e as Error).message); }
  }

  return (
    <>
      <tr className="border-t">
        <td className="p-2">{item.product_name}{!item.product_active && <Badge variant="outline" className="ml-1">delisted</Badge>}</td>
        <td className="p-2">{item.warehouse_name}{!item.warehouse_active && <Badge variant="outline" className="ml-1">inactive</Badge>}</td>
        <td className="p-2 text-right tabular-nums">{item.quantity}</td>
        <td className="p-2 text-right tabular-nums">{item.reorder_threshold}</td>
        <td className="p-2">{item.quantity === 0 ? <Badge variant="destructive">out</Badge> : item.low_stock ? <Badge variant="secondary">low</Badge> : "ok"}</td>
        <td className="p-2 text-right"><Button size="sm" variant="ghost" onClick={onToggle}>{open ? "Close" : "Manage"}</Button></td>
      </tr>
      {open && (
        <tr className="border-t bg-muted/20">
          <td colSpan={6} className="p-3">
            <div className="flex flex-wrap items-end gap-2">
              <Field label="Action">
                <select className={selectClass} value={kind} onChange={(e) => setKind(e.target.value)}>
                  <option value="manual_receipt">Receive (+)</option>
                  <option value="manual_issue">Issue (−)</option>
                  <option value="stock_count_adjustment">Stock count (set total)</option>
                </select>
              </Field>
              <Field label={kind === "stock_count_adjustment" ? "Counted total" : "Quantity"}>
                <Input type="number" min={0} className="w-24" value={quantity} onChange={(e) => setQuantity(Number(e.target.value))} />
              </Field>
              <Field label="Reason (required)">
                <Input className="w-56" value={reason} onChange={(e) => setReason(e.target.value)} />
              </Field>
              <Button disabled={reason.trim().length < 3}
                onClick={() => run(() => api.inventory(`${path}/adjustments`, "POST", { kind, quantity, reason, request_id: newId() }))}>
                Apply
              </Button>
              <Field label="Reorder threshold">
                <Input type="number" min={0} className="w-24" value={threshold} onChange={(e) => setThreshold(Number(e.target.value))} />
              </Field>
              <Button variant="outline" onClick={() => run(() => api.inventory(path, "PATCH", { reorder_threshold: threshold }))}>Save threshold</Button>
              <Button variant="destructive" disabled={item.quantity !== 0} title="Only empty rows can be deleted"
                onClick={() => run(() => api.inventory(path, "DELETE"))}>Delete row</Button>
            </div>
            {error && <p className="mt-2 text-sm text-destructive">{error}</p>}
            <div className="mt-3 text-xs">
              <p className="mb-1 font-medium">Recent movements</p>
              {movements?.map((m) => (
                <div key={m.id} className="flex gap-3 text-muted-foreground">
                  <span className="w-40">{new Date(m.occurred_at).toLocaleString()}</span>
                  <span className="w-40">{m.movement_type}</span>
                  <span className="w-12 text-right tabular-nums">{m.quantity_delta > 0 ? `+${m.quantity_delta}` : m.quantity_delta}</span>
                  <span className="w-12 text-right tabular-nums">{m.balance_after}</span>
                  <span className="truncate">{m.notes}</span>
                </div>
              ))}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

function AddInventoryRow({ onDone }: { onDone: () => void }) {
  const products = useLoad(useCallback(() => api.inventory<{ products: { id: string; name: string }[] }>("/catalog"), []));
  const warehouses = useLoad(useCallback(() => api.inventory<{ warehouses: Warehouse[] }>("/warehouses"), []));
  const [productId, setProductId] = useState("");
  const [warehouseId, setWarehouseId] = useState("");
  const [initial, setInitial] = useState(0);
  const [error, setError] = useState<string | null>(null);
  async function add() {
    setError(null);
    try {
      await api.inventory("/inventory", "POST", { product_id: productId, warehouse_id: warehouseId, initial_quantity: initial, request_id: newId() });
      onDone();
    } catch (e) { setError((e as Error).message); }
  }
  return (
    <div className="ml-auto flex flex-wrap items-end gap-2">
      <select className={selectClass} value={productId} onChange={(e) => setProductId(e.target.value)} aria-label="Product">
        <option value="">Product…</option>
        {products.data?.products.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
      </select>
      <select className={selectClass} value={warehouseId} onChange={(e) => setWarehouseId(e.target.value)} aria-label="Warehouse">
        <option value="">Warehouse…</option>
        {warehouses.data?.warehouses.filter((w) => w.is_active).map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
      </select>
      <Input type="number" min={0} className="w-20" value={initial} onChange={(e) => setInitial(Number(e.target.value))} aria-label="Initial quantity" />
      <Button variant="outline" disabled={!productId || !warehouseId} onClick={add}>Add stock row</Button>
      {error && <span className="text-sm text-destructive">{error}</span>}
    </div>
  );
}

// ── Warehouses & products ───────────────────────────────────────────────────

function SetupTab() {
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <WarehousesPanel />
      <ProductsPanel />
    </div>
  );
}

function WarehousesPanel() {
  const { data, error, reload } = useLoad(useCallback(() => api.inventory<{ warehouses: Warehouse[] }>("/warehouses"), []));
  const [form, setForm] = useState({ name: "", location: "", region: "" });
  const [actionError, setActionError] = useState<string | null>(null);
  async function run(action: () => Promise<unknown>) {
    setActionError(null);
    try { await action(); reload(); } catch (e) { setActionError((e as Error).message); }
  }
  return (
    <section className="flex flex-col gap-2">
      <h2 className="font-medium">Warehouses</h2>
      {error && <ErrorMessage error={error} />}
      {data?.warehouses.map((w) => (
        <div key={w.id} className="flex items-center gap-2 rounded-lg border p-2 text-sm">
          <span className="font-medium">{w.name}</span>
          <span className="text-muted-foreground">{w.location} · {w.region} · {w.total_quantity} units</span>
          {!w.is_active && <Badge variant="outline">inactive</Badge>}
          <Button size="sm" variant="ghost" className="ml-auto"
            onClick={() => run(() => api.inventory(`/warehouses/${w.id}`, "PATCH", { is_active: !w.is_active }))}>
            {w.is_active ? "Deactivate" : "Reactivate"}
          </Button>
        </div>
      ))}
      <div className="flex flex-wrap items-end gap-2">
        <Input placeholder="Name" className="w-28" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        <Input placeholder="Location" className="w-36" value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })} />
        <Input placeholder="Region" className="w-24" value={form.region} onChange={(e) => setForm({ ...form, region: e.target.value })} />
        <Button variant="outline" disabled={!form.name || !form.location || !form.region}
          onClick={() => run(async () => { await api.inventory("/warehouses", "POST", form); setForm({ name: "", location: "", region: "" }); })}>
          Add warehouse
        </Button>
      </div>
      {actionError && <p className="text-sm text-destructive">{actionError}</p>}
    </section>
  );
}

function ProductsPanel() {
  const [search, setSearch] = useState("");
  const load = useCallback(() => {
    const q = new URLSearchParams({ limit: "20" });
    if (search) q.set("search", search);
    return api.getManagerProducts(q.toString()) as Promise<{ products: ProductRow[] }>;
  }, [search]);
  const { data, error, reload } = useLoad(load);
  const [actionError, setActionError] = useState<string | null>(null);
  async function toggle(p: ProductRow) {
    setActionError(null);
    try { await api.inventory(`/products/${p.id}/status`, "PATCH", { is_active: !p.is_active }); reload(); }
    catch (e) { setActionError((e as Error).message); }
  }
  return (
    <section className="flex flex-col gap-2">
      <h2 className="font-medium">Products</h2>
      <NewProductForm onCreated={reload} />
      <Input placeholder="Search products" value={search} onChange={(e) => setSearch(e.target.value)} />
      {error && <ErrorMessage error={error} />}
      {data?.products.map((p) => (
        <div key={p.id} className="flex items-center gap-2 rounded-lg border p-2 text-sm">
          <span className="font-medium">{p.name}</span>
          <span className="text-muted-foreground">{p.category} · {p.current_stock} in stock</span>
          <Badge variant={p.is_active ? "secondary" : "outline"} className="ml-auto">{p.is_active ? "listed" : "delisted"}</Badge>
          <Button size="sm" variant="ghost" onClick={() => toggle(p)}>{p.is_active ? "Delist" : "List"}</Button>
        </div>
      ))}
      {actionError && <p className="text-sm text-destructive">{actionError}</p>}
    </section>
  );
}

function NewProductForm({ onCreated }: { onCreated: () => void }) {
  const warehouses = useLoad(useCallback(() => api.inventory<{ warehouses: Warehouse[] }>("/warehouses"), []));
  const empty = { name: "", description: "", category: "", brand: "", price: "", image_url: "", warehouse_id: "", initial_quantity: 0 };
  const [form, setForm] = useState(empty);
  const [listNow, setListNow] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const set = (key: keyof typeof empty) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) =>
    setForm({ ...form, [key]: key === "initial_quantity" ? Number(e.target.value) : e.target.value });

  async function save() {
    setError(null);
    try {
      await api.inventory("/products", "POST", {
        name: form.name, description: form.description, category: form.category, brand: form.brand || null,
        price: Number(form.price), image_url: form.image_url || null, is_active: listNow,
        stock: form.warehouse_id ? [{ warehouse_id: form.warehouse_id, initial_quantity: form.initial_quantity }] : [],
      });
      setForm(empty);
      onCreated();
    } catch (e) { setError((e as Error).message); }
  }

  return (
    <details className="rounded-lg border p-2">
      <summary className="cursor-pointer text-sm font-medium">New product</summary>
      {/* AI marketing helpers (title/copy/image generation) attach here in phase 2. */}
      <div className="mt-2 grid gap-2 sm:grid-cols-2">
        <Input placeholder="Name" value={form.name} onChange={set("name")} />
        <Input placeholder="Category" value={form.category} onChange={set("category")} />
        <Input placeholder="Brand" value={form.brand} onChange={set("brand")} />
        <Input placeholder="Price" type="number" min={0} step="0.01" value={form.price} onChange={set("price")} />
        <textarea placeholder="Description" className="min-h-20 rounded-lg border border-input bg-background p-2 text-sm sm:col-span-2"
          value={form.description} onChange={set("description")} />
        <Input placeholder="Image URL (optional)" className="sm:col-span-2" value={form.image_url} onChange={set("image_url")} />
        <select className={selectClass} value={form.warehouse_id} onChange={set("warehouse_id")} aria-label="Initial warehouse">
          <option value="">No initial stock</option>
          {warehouses.data?.warehouses.filter((w) => w.is_active).map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}
        </select>
        <Input type="number" min={0} placeholder="Initial quantity" value={form.initial_quantity} onChange={set("initial_quantity")}
          disabled={!form.warehouse_id} />
        <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={listNow} onChange={(e) => setListNow(e.target.checked)} />List immediately</label>
        <Button disabled={!form.name || !form.description || !form.category || !(Number(form.price) > 0)} onClick={save}>Save product</Button>
      </div>
      {error && <p className="mt-2 text-sm text-destructive">{error}</p>}
    </details>
  );
}
