-- Additive migration. Existing orders are NOT replayed against today's inventory.
CREATE TABLE IF NOT EXISTS sales_dataset_runs (
    id UUID PRIMARY KEY,
    generator_version TEXT NOT NULL,
    random_seed INTEGER NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    business_timezone TEXT NOT NULL DEFAULT 'UTC',
    config JSONB NOT NULL,
    summary JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (end_date >= start_date)
);

CREATE TABLE IF NOT EXISTS inventory_movements (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_key TEXT NOT NULL UNIQUE,
    product_id UUID NOT NULL REFERENCES products(id),
    warehouse_id UUID NOT NULL REFERENCES warehouses(id),
    movement_type TEXT NOT NULL,
    quantity_delta INTEGER NOT NULL,
    balance_after INTEGER NOT NULL CHECK (balance_after >= 0),
    order_id UUID REFERENCES orders(id) ON DELETE SET NULL,
    order_item_id UUID REFERENCES order_items(id) ON DELETE SET NULL,
    return_id UUID REFERENCES returns(id) ON DELETE SET NULL,
    dataset_run_id UUID REFERENCES sales_dataset_runs(id) ON DELETE SET NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notes TEXT NOT NULL DEFAULT '',
    CHECK (movement_type <> ''),
    CHECK ((movement_type <> 'sale' OR quantity_delta < 0)
       AND (movement_type NOT IN ('opening', 'historical_receipt', 'return_received', 'cancel_release')
            OR quantity_delta >= 0))
);
CREATE UNIQUE INDEX IF NOT EXISTS inventory_one_opening
    ON inventory_movements(product_id, warehouse_id) WHERE movement_type = 'opening';
CREATE INDEX IF NOT EXISTS inventory_movements_history
    ON inventory_movements(product_id, warehouse_id, occurred_at, id);
CREATE INDEX IF NOT EXISTS inventory_movements_order ON inventory_movements(order_id);
CREATE INDEX IF NOT EXISTS sales_orders_created ON orders(created_at, id);
CREATE INDEX IF NOT EXISTS sales_items_product_order ON order_items(product_id, order_id);

-- Lock the live stock table while establishing the first trustworthy history point.
LOCK TABLE warehouse_inventory IN SHARE ROW EXCLUSIVE MODE;
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                   WHERE conname = 'inventory_quantity_nonnegative'
                     AND conrelid = 'warehouse_inventory'::regclass) THEN
        ALTER TABLE warehouse_inventory ADD CONSTRAINT inventory_quantity_nonnegative CHECK (quantity >= 0);
    END IF;
END $$;
INSERT INTO inventory_movements
    (event_key, product_id, warehouse_id, movement_type, quantity_delta, balance_after, occurred_at, notes)
SELECT 'opening:' || wi.warehouse_id || ':' || wi.product_id,
       wi.product_id, wi.warehouse_id, 'opening', wi.quantity, wi.quantity, NOW(),
       'Migration baseline: inventory before this timestamp is unknown; old orders were not replayed.'
FROM warehouse_inventory wi
WHERE NOT EXISTS (
    SELECT 1 FROM inventory_movements m
    WHERE m.product_id = wi.product_id AND m.warehouse_id = wi.warehouse_id
)
ON CONFLICT (event_key) DO NOTHING;

-- No discount allocation: amounts here are item subtotals, not net cash revenue.
-- Status columns reflect the CURRENT order status and may revise historical totals.
CREATE OR REPLACE VIEW sales_daily AS
SELECT (o.created_at AT TIME ZONE 'UTC')::date AS sales_date,
       oi.product_id,
       COUNT(DISTINCT o.id) AS order_count,
       SUM(oi.quantity) AS ordered_units,
       COALESCE(SUM(oi.quantity) FILTER (WHERE o.status = 'cancelled'), 0) AS cancelled_units,
       COALESCE(SUM(oi.quantity) FILTER (WHERE o.status = 'returned'), 0) AS returned_order_units,
       COALESCE(SUM(oi.quantity) FILTER (WHERE o.status <> 'cancelled'), 0) AS non_cancelled_units,
       SUM(oi.subtotal) AS ordered_item_amount,
       COALESCE(SUM(oi.subtotal) FILTER (WHERE o.status <> 'cancelled'), 0) AS non_cancelled_item_amount
FROM orders o JOIN order_items oi ON oi.order_id = o.id
GROUP BY (o.created_at AT TIME ZONE 'UTC')::date, oi.product_id;

-- Event days only. Carry the latest known balance forward for quiet days; do not fill
-- days before the opening event with zeros. id breaks ties within one transaction.
CREATE OR REPLACE VIEW inventory_daily_changes AS
SELECT (occurred_at AT TIME ZONE 'UTC')::date AS inventory_date,
       product_id, warehouse_id,
       SUM(quantity_delta) AS net_change,
       COALESCE(-SUM(quantity_delta) FILTER (WHERE movement_type = 'sale'), 0) AS outbound_units,
       COALESCE(SUM(quantity_delta) FILTER (WHERE movement_type = 'return_received'), 0) AS returned_units,
       (ARRAY_AGG(balance_after ORDER BY occurred_at DESC, id DESC))[1] AS closing_quantity
FROM inventory_movements
GROUP BY (occurred_at AT TIME ZONE 'UTC')::date, product_id, warehouse_id;
