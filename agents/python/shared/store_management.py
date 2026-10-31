"""Whole-store operational reads shared by manager APIs and agent tools.

The legacy products.seller_id column never restricts this single-store application.
Authorization is enforced by the HTTP dependency or the tool entry point.
"""

from __future__ import annotations

import asyncpg

from shared.sales_analysis import serialize


async def list_products(conn: asyncpg.Connection, category: str | None, limit: int, offset: int = 0) -> dict:
    rows = await conn.fetch(
        """SELECT id, name, description, category, brand, price, original_price,
                  image_url, rating, review_count, is_active
           FROM products WHERE ($1::text IS NULL OR category = $1)
           ORDER BY created_at DESC, id LIMIT $2 OFFSET $3""",
        category,
        limit,
        offset,
    )
    total = await conn.fetchval("SELECT COUNT(*) FROM products WHERE ($1::text IS NULL OR category = $1)", category)
    return {"products": serialize(rows), "total": total}


async def list_orders(conn: asyncpg.Connection, status: str | None, limit: int, offset: int = 0) -> dict:
    rows = await conn.fetch(
        """SELECT o.id, o.status, o.total, o.created_at AS date,
                  buyer.name AS buyer_name, buyer.email AS buyer_email,
                  COALESCE(items.item_count, 0) AS item_count
           FROM orders o JOIN users buyer ON o.user_id = buyer.id
           LEFT JOIN LATERAL (
               SELECT COUNT(*) AS item_count FROM order_items WHERE order_id = o.id
           ) items ON TRUE
           WHERE ($1::text IS NULL OR o.status = $1)
           ORDER BY o.created_at DESC, o.id LIMIT $2 OFFSET $3""",
        status,
        limit,
        offset,
    )
    total = await conn.fetchval("SELECT COUNT(*) FROM orders WHERE ($1::text IS NULL OR status = $1)", status)
    return {"orders": serialize(rows), "total": total}


async def statistics(conn: asyncpg.Connection) -> dict:
    row = await conn.fetchrow(
        """SELECT (SELECT COUNT(*) FROM products) AS product_count,
                  (SELECT COUNT(*) FROM orders) AS order_count,
                  (SELECT COALESCE(SUM(oi.subtotal), 0) FROM order_items oi
                   JOIN orders o ON oi.order_id = o.id WHERE o.status <> 'cancelled') AS item_sales_amount,
                  (SELECT COALESCE(AVG(rating), 0) FROM products) AS avg_rating"""
    )
    result = serialize([row])[0]
    result["avg_rating"] = round(result["avg_rating"], 2)
    result["sales_definition"] = (
        "Non-cancelled item subtotals, including returned orders; not net revenue after discounts/refunds."
    )
    return result


async def inventory(conn: asyncpg.Connection, low_stock_only: bool) -> list[dict]:
    rows = await conn.fetch(
        """SELECT p.id AS product_id, p.name AS product_name, w.name AS warehouse, w.region,
                  wi.quantity, (wi.quantity <= wi.reorder_threshold) AS low_stock
           FROM warehouse_inventory wi JOIN products p ON wi.product_id = p.id
           JOIN warehouses w ON wi.warehouse_id = w.id
           WHERE (NOT $1::boolean OR wi.quantity <= wi.reorder_threshold)
           ORDER BY p.name, w.region, w.id""",
        low_stock_only,
    )
    return serialize(rows)
