"""Read-only sales/inventory calculations shared by HTTP and Agent tools.

UTC date windows are inclusive. Item amounts exclude allocation of order discounts.
Order status is current-state, not a historical as-of snapshot for model backtesting.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import asyncpg


@dataclass(frozen=True)
class AnalysisWindow:
    start: date
    end: date

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError("Start date must not be after end date")
        if (self.end - self.start).days >= 730:
            raise ValueError("Select no more than 730 days")
        if self.end > datetime.now(UTC).date():
            raise ValueError("Historical analysis cannot include future dates")

    @property
    def bounds(self) -> tuple[datetime, datetime]:
        return (
            datetime.combine(self.start, datetime.min.time(), UTC),
            datetime.combine(self.end + timedelta(days=1), datetime.min.time(), UTC),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "start_date": str(self.start),
            "end_date": str(self.end),
            "timezone": "UTC",
            "includes_partial_today": self.end == datetime.now(UTC).date(),
        }


def serialize(row: Any) -> Any:
    if isinstance(row, (dict, asyncpg.Record)):
        return {key: serialize(value) for key, value in dict(row).items()}
    if isinstance(row, list):
        return [serialize(value) for value in row]
    if isinstance(row, Decimal):
        return float(row)
    if isinstance(row, (uuid.UUID, date, datetime)):
        return str(row) if not isinstance(row, datetime) else row.isoformat()
    return row


async def scope_products(
    conn: asyncpg.Connection,
    category: str | None = None,
    product_id: uuid.UUID | None = None,
    search: str | None = None,
) -> list[asyncpg.Record]:
    return await conn.fetch(
        """SELECT p.id, p.name, p.category, p.brand, p.price, p.description, p.is_active, p.created_at,
                  LEAST((p.created_at AT TIME ZONE 'UTC')::date,
                        COALESCE(first_order.day,(p.created_at AT TIME ZONE 'UTC')::date)) AS known_launch
           FROM products p LEFT JOIN LATERAL (
               SELECT MIN(o.created_at AT TIME ZONE 'UTC')::date AS day
               FROM order_items oi JOIN orders o ON o.id=oi.order_id WHERE oi.product_id=p.id
           ) first_order ON TRUE
           WHERE ($1::text IS NULL OR p.category=$1)
             AND ($2::uuid IS NULL OR p.id=$2)
             AND ($3::text IS NULL OR p.name ILIKE '%' || $3 || '%' OR p.brand ILIKE '%' || $3 || '%')
           ORDER BY p.name,p.id""",
        category,
        product_id,
        search,
    )


async def metrics(
    conn: asyncpg.Connection,
    product_ids: list[uuid.UUID],
    window: AnalysisWindow,
) -> dict[str, Any]:
    row = await conn.fetchrow(
        """SELECT COUNT(DISTINCT o.id) FILTER(WHERE o.status<>'cancelled') AS order_count,
                  COALESCE(SUM(oi.quantity) FILTER(WHERE o.status<>'cancelled'),0) AS units,
                  COALESCE(SUM(oi.subtotal) FILTER(WHERE o.status<>'cancelled'),0) AS item_amount,
                  COALESCE(SUM(oi.quantity) FILTER(WHERE o.status='cancelled'),0) AS cancelled_units,
                  COALESCE(SUM(oi.quantity) FILTER(WHERE o.status='returned'),0) AS returned_order_units
           FROM orders o JOIN order_items oi ON oi.order_id=o.id
           WHERE oi.product_id=ANY($1::uuid[]) AND o.created_at >= $2 AND o.created_at < $3""",
        product_ids,
        *window.bounds,
    )
    stock = await conn.fetchrow(
        """SELECT COALESCE(SUM(quantity),0) AS current_stock,
           COUNT(DISTINCT product_id) FILTER(WHERE quantity<=reorder_threshold) AS low_stock_products
           FROM warehouse_inventory WHERE product_id=ANY($1::uuid[])""",
        product_ids,
    )
    return {**serialize(row), **serialize(stock), "product_count": len(product_ids)}


async def product_list(
    conn: asyncpg.Connection,
    window: AnalysisWindow,
    category: str | None = None,
    search: str | None = None,
    offset: int = 0,
    limit: int = 20,
    product_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    scope = await scope_products(conn, category=category, search=search, product_id=product_id)
    selected = scope[offset : offset + limit]
    ids = [row["id"] for row in selected]
    sales = await conn.fetch(
        """SELECT oi.product_id,
           COALESCE(SUM(oi.quantity) FILTER(WHERE o.status<>'cancelled'),0) AS units,
           COALESCE(SUM(oi.subtotal) FILTER(WHERE o.status<>'cancelled'),0) AS item_amount,
           COUNT(DISTINCT o.id) FILTER(WHERE o.status<>'cancelled') AS order_count
           FROM order_items oi JOIN orders o ON o.id=oi.order_id
           WHERE oi.product_id=ANY($1::uuid[]) AND o.created_at >= $2 AND o.created_at < $3
           GROUP BY oi.product_id""",
        ids,
        *window.bounds,
    )
    stocks = await conn.fetch(
        """SELECT product_id,SUM(quantity) AS current_stock,BOOL_OR(quantity<=reorder_threshold) AS low_stock
           FROM warehouse_inventory WHERE product_id=ANY($1::uuid[]) GROUP BY product_id""",
        ids,
    )
    sales_map, stock_map = {r["product_id"]: r for r in sales}, {r["product_id"]: r for r in stocks}
    products = [
        {
            **serialize(row),
            "units": 0,
            "item_amount": 0,
            "order_count": 0,
            "current_stock": 0,
            "low_stock": False,
            **serialize(sales_map.get(row["id"], {})),
            **serialize(stock_map.get(row["id"], {})),
        }
        for row in selected
    ]
    return {"products": products, "total": len(scope), "offset": offset, "limit": limit, "window": window.as_dict()}


async def product_orders(
    conn: asyncpg.Connection,
    product_id: uuid.UUID,
    window: AnalysisWindow,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    total = await conn.fetchval(
        """SELECT COUNT(DISTINCT o.id) FROM orders o JOIN order_items oi ON oi.order_id=o.id
           WHERE oi.product_id=$1 AND o.created_at >= $2 AND o.created_at < $3""",
        product_id,
        *window.bounds,
    )
    rows = await conn.fetch(
        """SELECT o.id,o.created_at,o.status,SUM(oi.quantity) AS quantity,SUM(oi.subtotal) AS item_amount
           FROM orders o JOIN order_items oi ON oi.order_id=o.id
           WHERE oi.product_id=$1 AND o.created_at >= $2 AND o.created_at < $3
           GROUP BY o.id ORDER BY o.created_at DESC,o.id LIMIT $4 OFFSET $5""",
        product_id,
        *window.bounds,
        limit,
        offset,
    )
    return {"orders": serialize(rows), "total": total, "offset": offset, "limit": limit}


async def historical_analysis(
    conn: asyncpg.Connection,
    window: AnalysisWindow,
    category: str | None = None,
    product_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    scope = await scope_products(conn, category, product_id)
    if product_id and not scope:
        raise LookupError("Product not found in the selected category")
    ids = [row["id"] for row in scope]
    summary = await metrics(conn, ids, window)
    daily = await conn.fetch(
        """SELECT (o.created_at AT TIME ZONE 'UTC')::date AS day,
           COUNT(DISTINCT o.id) FILTER(WHERE o.status<>'cancelled') AS order_count,
           COALESCE(SUM(oi.quantity) FILTER(WHERE o.status<>'cancelled'),0) AS units,
           COALESCE(SUM(oi.subtotal) FILTER(WHERE o.status<>'cancelled'),0) AS item_amount
           FROM order_items oi JOIN orders o ON o.id=oi.order_id
           WHERE oi.product_id=ANY($1::uuid[]) AND o.created_at >= $2 AND o.created_at < $3
           GROUP BY day ORDER BY day""",
        ids,
        *window.bounds,
    )
    coverage_start = await conn.fetchval(
        """SELECT COALESCE((SELECT MIN(start_date) FROM sales_dataset_runs),
                 (SELECT MIN((created_at AT TIME ZONE 'UTC')::date) FROM orders))""",
    )
    # A per-warehouse latest balance is carried forward before aggregating. Missing
    # baselines stay NULL; a newly launched product does not erase older products.
    inventory = await conn.fetch(
        """WITH days AS (SELECT d::date AS day FROM generate_series($2::date,$3::date,INTERVAL '1 day') d),
           pairs AS (SELECT wi.product_id,wi.warehouse_id,p.created_at FROM warehouse_inventory wi
                     JOIN products p ON p.id=wi.product_id WHERE p.id=ANY($1::uuid[]))
           SELECT days.day,
             CASE WHEN COUNT(*) FILTER(WHERE last_balance.balance_after IS NULL)>0 THEN NULL
                  ELSE SUM(last_balance.balance_after) END AS closing_stock
           FROM days JOIN pairs ON pairs.created_at < (days.day + 1)::timestamp AT TIME ZONE 'UTC'
           LEFT JOIN LATERAL (
               SELECT m.balance_after FROM inventory_movements m
               WHERE m.product_id=pairs.product_id AND m.warehouse_id=pairs.warehouse_id
                 AND m.occurred_at < (days.day + 1)::timestamp AT TIME ZONE 'UTC'
               ORDER BY m.occurred_at DESC,m.id DESC LIMIT 1
           ) last_balance ON TRUE GROUP BY days.day ORDER BY days.day""",
        ids,
        window.start,
        window.end,
    )
    daily_map = {r["day"]: r for r in daily}
    inventory_map = {r["day"]: r["closing_stock"] for r in inventory}
    launches = [row["known_launch"] for row in scope]
    series = []
    for offset in range((window.end - window.start).days + 1):
        day = window.start + timedelta(days=offset)
        known = bool(coverage_start and day >= coverage_start and launches and day >= min(launches))
        row = daily_map.get(day)
        series.append(
            {
                "date": str(day),
                "units": int(row["units"]) if row else 0 if known else None,
                "item_amount": float(row["item_amount"]) if row else 0 if known else None,
                "order_count": int(row["order_count"]) if row else 0 if known else None,
                "closing_stock": inventory_map.get(day),
            }
        )
    warehouses = await conn.fetch(
        """SELECT w.id,w.name,w.region,wi.product_id,wi.quantity,wi.reorder_threshold
           FROM warehouse_inventory wi JOIN warehouses w ON w.id=wi.warehouse_id
           WHERE wi.product_id=ANY($1::uuid[]) ORDER BY w.name,wi.product_id""",
        ids,
    )
    return {
        "window": window.as_dict(),
        "summary": summary,
        "series": series,
        "products": serialize(scope),
        "warehouses": serialize(warehouses),
        "coverage_start": str(coverage_start) if coverage_start else None,
        "generated_at": datetime.now(UTC).isoformat(),
        "definitions": {
            "units": "Non-cancelled order units; returned orders included and reported separately",
            "item_amount": "Item subtotals before order discounts/refunds; USD",
            "stock": "Current stock is live; historical stock is end-of-day UTC; null means unknown",
        },
        "forecast": {
            "available": True,
            "assumption": "No future receipts assumed",
            "endpoint": "/api/manager/analysis-runs",
            "note": "Separate calculation; individual products may have insufficient data",
        },
    }
