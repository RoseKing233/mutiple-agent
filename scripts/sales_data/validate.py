"""Offline and live-database invariants. Returns summaries; raises on invalid data."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal

import asyncpg

from scripts.sales_data.generator import Simulation


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(f"Invalid simulation: {message}")


def validate_simulation(data: Simulation) -> dict[str, int]:
    end = datetime.combine(data.config.end_date + timedelta(days=1), time(), UTC)
    totals: dict = defaultdict(lambda: Decimal("0"))
    orders = {row["id"]: row for row in data.orders}
    items = {row["id"]: row for row in data.items}
    sales: dict = defaultdict(int)
    balances: dict = defaultdict(int)
    openings: set = set()
    keys: set = set()
    for item in data.items:
        require(item["quantity"] > 0 and item["subtotal"] == item["unit_price"] * item["quantity"], "item amount")
        totals[item["order_id"]] += item["subtotal"]
    for order in data.orders:
        require(totals[order["id"]] == order["total"] and order["created_at"] < end, "order total/date")
    for status in data.statuses:
        require(orders[status["order_id"]]["created_at"] <= status["timestamp"] < end, "status timestamp")
    for row in data.movements:
        pair = (row["product_id"], row["warehouse_id"])
        require(row["event_key"] not in keys and row["occurred_at"] < end, "movement event key/date")
        keys.add(row["event_key"])
        if row["movement_type"] == "opening":
            require(pair not in openings, "duplicate opening")
            openings.add(pair)
        else:
            require(pair in openings, "missing opening")
        balances[pair] += row["quantity_delta"]
        require(balances[pair] == row["balance_after"] and balances[pair] >= 0, "inventory balance")
        if row["movement_type"] == "sale":
            require(row["order_item_id"] in items, "sale without order item")
            sales[row["order_item_id"]] -= row["quantity_delta"]
    require(dict(balances) == data.inventory, "closing inventory")
    require(all(sales[item["id"]] == item["quantity"] for item in data.items), "sale allocation")
    require(len(orders) == len(data.orders) and len(items) == len(data.items), "duplicate order/item IDs")
    return {
        "orders": len(data.orders),
        "order_items": len(data.items),
        "movements": len(data.movements),
        "returns": len(data.returns),
        "ordered_units": sum(item["quantity"] for item in data.items),
        "unfilled_simulated_demand": data.unfilled_units,
    }


async def validate_database(conn: asyncpg.Connection) -> dict[str, int]:
    """Read-only checks usable by the handover recipient after stock integrations."""
    mismatches = await conn.fetchval("""SELECT COUNT(*) FROM (
        SELECT wi.product_id, wi.warehouse_id FROM warehouse_inventory wi
        LEFT JOIN inventory_movements m USING (product_id, warehouse_id)
        GROUP BY wi.product_id, wi.warehouse_id, wi.quantity
        HAVING COUNT(m.id) = 0 OR COALESCE(SUM(m.quantity_delta), 0) <> wi.quantity OR wi.quantity < 0
    ) bad""")
    broken_history = await conn.fetchval("""SELECT COUNT(*) FROM (
        SELECT balance_after, SUM(quantity_delta) OVER (
            PARTITION BY product_id, warehouse_id ORDER BY occurred_at, id) AS expected
        FROM inventory_movements
    ) history WHERE balance_after <> expected OR balance_after < 0""")
    bad_totals = await conn.fetchval("""SELECT COUNT(*) FROM (
        SELECT o.id FROM orders o JOIN order_items oi ON oi.order_id = o.id
        GROUP BY o.id, o.total, o.discount_amount
        HAVING ABS(o.total - GREATEST(SUM(oi.subtotal) - COALESCE(o.discount_amount, 0), 0)) > 0.01
    ) bad""")
    summary = {
        "inventory_mismatches": mismatches,
        "broken_history_rows": broken_history,
        "order_total_mismatches": bad_totals,
    }
    if any(summary.values()):
        raise ValueError(f"Database validation failed: {summary}")
    return summary
