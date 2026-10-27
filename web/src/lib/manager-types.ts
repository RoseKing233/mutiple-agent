export interface ManagerProduct {
  id: string;
  name: string;
  category: string;
  brand: string | null;
  price: number;
  description: string;
  is_active: boolean;
  current_stock: number;
  units: number;
  item_amount: number;
  order_count: number;
  low_stock: boolean;
}

export interface ManagerCatalog {
  categories: string[];
  products: Array<Pick<ManagerProduct, "id" | "name" | "category">>;
}

export interface ManagerProductList {
  products: ManagerProduct[];
  total: number;
  offset: number;
  limit: number;
}

export interface ManagerAnalysis {
  window: { start_date: string; end_date: string; timezone: string; includes_partial_today: boolean };
  summary: {
    order_count: number;
    units: number;
    item_amount: number;
    cancelled_units: number;
    returned_order_units: number;
    current_stock: number;
    low_stock_products: number;
    product_count: number;
  };
  series: Array<{ date: string; units: number | null; closing_stock: number | null }>;
  products: Array<Pick<ManagerProduct, "id" | "name" | "category" | "price" | "description" | "is_active">>;
  warehouses: Array<{ id: string; name: string; region: string; product_id: string; quantity: number; reorder_threshold: number }>;
  coverage_start: string | null;
  generated_at: string;
  forecast: { available: boolean; assumption: string };
}

export interface ManagerOrders {
  orders: Array<{ id: string; created_at: string; status: string; quantity: number; item_amount: number }>;
  total: number;
  offset: number;
  limit: number;
}

export interface ProductPerformance {
  trend: string;
  slow_moving: boolean | null;
  overstock: boolean | null;
  recent_units: number;
  previous_units: number | null;
  growth_percent: number | null;
  consecutive_zero_days: number;
  stock_at_cutoff: number | null;
  days_of_cover: number | null;
  no_recent_sales: boolean;
  comparison_days: number;
  recent_start: string | null;
  previous_start: string | null;
  warnings: string[];
}

export interface PerformanceReport {
  as_of: string;
  rules: Record<string, number>;
  products: Array<ProductPerformance & { product_id: string; name: string; category: string }>;
}

export interface ForecastParameters {
  as_of: string;
  horizon: 7 | 14 | 28;
  product_id?: string | null;
  category?: string | null;
  rules?: Record<string, number>;
}

export interface ForecastPoint {
  date: string;
  units: number | null;
  stock: number | null;
  available_product_units?: number | null;
  lower_units?: number | null;
  upper_units?: number | null;
  shortfall?: number | null;
}

export interface ForecastRun {
  id: string;
  engine_version: string;
  generated_at: string;
  data_fingerprint: string;
  parameters: ForecastParameters;
  stock_baseline: string;
  assumptions: string[];
  summary: { product_count: number; forecastable_products: number; complete: boolean; growing: number; declining: number; slow_moving: number; overstock: number };
  series: ForecastPoint[];
  products: Array<{
    product_id: string;
    name: string;
    category: string;
    performance: ProductPerformance;
    forecast: {
      available: boolean;
      reason?: string;
      model?: string;
      training_days: number;
      reliability?: string;
      warnings: string[];
      uncertainty?: string;
      series?: ForecastPoint[];
      stockout_date?: string | null;
      stockout_status?: string;
      unmet_units?: number | null;
      earlier_stockout_scenario?: string | null;
      later_stockout_scenario?: string | null;
      backtest?: { scores: Array<{ model: string; mae: number; horizon_total_mae: number; folds: number }>; note: string };
    };
  }>;
}

export interface SavedAnalysisList {
  runs: Array<{ id: string; as_of: string; horizon: number; created_at: string; parameters: ForecastParameters; summary: ForecastRun["summary"] }>;
  total: number;
  offset: number;
  limit: number;
}
