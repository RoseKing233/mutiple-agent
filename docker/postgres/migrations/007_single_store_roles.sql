-- Single-store operation: managers replace sellers; retain all users and business data.
UPDATE users SET role = 'store_manager' WHERE role = 'seller';
UPDATE users SET role = 'customer' WHERE role = 'power_user';

COMMENT ON COLUMN users.role IS 'customer, store_manager, admin; managers operate the entire store';
COMMENT ON COLUMN products.seller_id IS 'Legacy ownership reference retained for compatibility; not an access boundary in the single-store application';

UPDATE agent_catalog
SET allowed_roles = ARRAY(
    SELECT DISTINCT CASE r WHEN 'seller' THEN 'store_manager' WHEN 'power_user' THEN 'customer' ELSE r END
    FROM unnest(COALESCE(allowed_roles, ARRAY[]::text[]) || ARRAY['store_manager']) AS r
    ORDER BY 1
);
ALTER TABLE agent_catalog ALTER COLUMN allowed_roles SET DEFAULT '{customer,store_manager,admin}';

INSERT INTO agent_permissions(user_id, agent_name, role, granted_by)
SELECT u.id, a.name, 'user', u.id
FROM users u CROSS JOIN agent_catalog a
WHERE u.role = 'store_manager'
ON CONFLICT DO NOTHING;
