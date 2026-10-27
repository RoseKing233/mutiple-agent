-- Inventory management: warehouse lifecycle and human-reviewed stock suggestions.
-- Warehouses and products are deactivated, never deleted: movements and orders reference them.
ALTER TABLE warehouses ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE warehouses ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- Rule-computed suggestions. The LLM only writes `rationale`; numbers come from code.
-- Accepting a restock records a receipt through change_inventory (event_key below);
-- accepting an overstock suggestion records the decision only and never changes stock.
CREATE TABLE IF NOT EXISTS inventory_suggestions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id UUID NOT NULL,
    owner_id UUID NOT NULL REFERENCES users(id),
    product_id UUID NOT NULL REFERENCES products(id),
    warehouse_id UUID REFERENCES warehouses(id),
    suggestion_type TEXT NOT NULL CHECK (suggestion_type IN ('restock', 'overstock')),
    priority TEXT NOT NULL CHECK (priority IN ('high', 'medium', 'low')),
    suggested_quantity INTEGER NOT NULL CHECK (suggested_quantity >= 0),
    as_of DATE NOT NULL,
    horizon INTEGER NOT NULL,
    evidence JSONB NOT NULL,
    rationale TEXT NOT NULL DEFAULT '',
    rationale_source TEXT NOT NULL DEFAULT 'rule' CHECK (rationale_source IN ('ai', 'rule')),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'accepted', 'rejected', 'superseded')),
    decided_by UUID REFERENCES users(id),
    decided_at TIMESTAMPTZ,
    decision_note TEXT NOT NULL DEFAULT '',
    executed_quantity INTEGER,
    executed_warehouse_id UUID REFERENCES warehouses(id),
    movement_event_key TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS inventory_suggestions_status ON inventory_suggestions(status, created_at DESC);
CREATE INDEX IF NOT EXISTS inventory_suggestions_product ON inventory_suggestions(product_id, created_at DESC);

-- Chat write operations are two-step: a tool proposes (no data change), and a later
-- confirm call executes only if the user's newest message in the same conversation
-- arrived after the proposal and explicitly agrees. The server checks consent, not the LLM.
CREATE TABLE IF NOT EXISTS inventory_action_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id UUID NOT NULL REFERENCES users(id),
    conversation_id UUID NOT NULL,
    action_type TEXT NOT NULL
        CHECK (action_type IN ('stock_adjustment', 'suggestion_decision', 'product_status')),
    payload JSONB NOT NULL,
    preview JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'executed', 'cancelled', 'failed')),
    result JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    expires_at TIMESTAMPTZ NOT NULL,
    resolved_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS inventory_action_requests_owner
    ON inventory_action_requests(owner_id, conversation_id, created_at DESC);
