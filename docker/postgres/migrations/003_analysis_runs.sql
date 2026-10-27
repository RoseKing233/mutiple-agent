-- Immutable, reproducible manager reports. Forecasts never mutate inventory.
CREATE TABLE IF NOT EXISTS sales_analysis_runs (
    id UUID PRIMARY KEY,
    owner_id UUID NOT NULL REFERENCES users(id),
    request_id UUID NOT NULL,
    engine_version TEXT NOT NULL,
    as_of DATE NOT NULL,
    horizon INTEGER NOT NULL CHECK (horizon IN (7,14,28)),
    parameters JSONB NOT NULL,
    result JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(owner_id, request_id)
);
CREATE INDEX IF NOT EXISTS sales_analysis_runs_owner_created
    ON sales_analysis_runs(owner_id, created_at DESC, id);
CREATE INDEX IF NOT EXISTS order_status_history_asof
    ON order_status_history(order_id, timestamp);
