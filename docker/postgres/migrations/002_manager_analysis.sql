COMMENT ON COLUMN users.role IS 'customer, power_user, seller, store_manager, admin; assigned by trusted setup only';
CREATE INDEX IF NOT EXISTS products_analysis_category ON products(category, name, id);
-- Backfill nothing: manager provisioning is explicit Python code so bcrypt hashes
-- are generated locally, and existing customer accounts cannot be silently promoted.
