"""Load a consistent snapshot; reconstruct cancellation knowledge at each origin.

Only event timestamps are available in the original order-status table. This is
event-time backtesting, not an ingestion-time/bitemporal audit of late corrections.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

import asyncpg

from shared.forecasting.config import ForecastRequest
from shared.sales_analysis import scope_products


@dataclass
class ProductHistory:
    product_id: str
    name: str
    category: str
    days: list[date]
    # Order day, quantity, earliest cancellation day (known at that day).
    orders: list[tuple[date, int, date | None]] = field(default_factory=list)
    stock: list[int | None] = field(default_factory=list)
    constrained: list[bool] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    status_complete: bool = True

    def sales_at(self, cutoff: date) -> list[float]:
        totals: dict[date, int] = {}
        for day, quantity, cancelled in self.orders:
            if day <= cutoff and (cancelled is None or cancelled > cutoff):
                totals[day] = totals.get(day, 0) + quantity
        return [float(totals.get(day, 0)) for day in self.days if day <= cutoff]


async def load_histories(conn: asyncpg.Connection, spec: ForecastRequest) -> list[ProductHistory]:
    products = await scope_products(conn, spec.category, spec.product_id)
    if spec.product_id and not products:
        raise LookupError("Product not found in the selected category")
    if len(products) > 200:
        raise ValueError("Select a category or product: at most 200 products per forecast")
    ids = [p["id"] for p in products]
    start = spec.as_of - timedelta(days=179)
    boundary = datetime.combine(spec.as_of + timedelta(days=1), datetime.min.time(), UTC)
    coverage = await conn.fetchval(
        """SELECT COALESCE((SELECT MIN(start_date) FROM sales_dataset_runs WHERE start_date<=$1),
        (SELECT MIN((created_at AT TIME ZONE 'UTC')::date) FROM orders WHERE created_at<$2))""",
        spec.as_of,
        boundary,
    )
    rows = await conn.fetch(
        """SELECT oi.product_id, (o.created_at AT TIME ZONE 'UTC')::date AS day,
        oi.quantity, o.status,
        MIN(h.timestamp) FILTER(WHERE h.status='cancelled') AS cancelled_at,
        MIN(h.timestamp) FILTER(WHERE h.status IN ('placed','confirmed')) AS initial_at
        FROM orders o JOIN order_items oi ON oi.order_id=o.id
        LEFT JOIN order_status_history h ON h.order_id=o.id
        WHERE oi.product_id=ANY($1::uuid[]) AND o.created_at >= $2 AND o.created_at < $3
        GROUP BY oi.id,o.id ORDER BY oi.product_id,o.created_at,oi.id""",
        ids,
        datetime.combine(start, datetime.min.time(), UTC),
        boundary,
    )
    # Fetch all earlier events too: the last balance before the training start
    # is the opening observation, not zero. Only <= cutoff events are visible.
    events = await conn.fetch(
        """SELECT product_id,warehouse_id,balance_after,quantity_delta,occurred_at
        FROM inventory_movements WHERE product_id=ANY($1::uuid[]) AND occurred_at<$2
        ORDER BY occurred_at,id""",
        ids,
        boundary,
    )
    pairs = await conn.fetch(
        "SELECT product_id,warehouse_id FROM warehouse_inventory WHERE product_id=ANY($1::uuid[])",
        ids,
    )
    result = []
    for p in products:
        first = max(start, coverage or spec.as_of + timedelta(days=1), p["known_launch"])
        days = [first + timedelta(days=i) for i in range(max(0, (spec.as_of - first).days + 1))]
        history = ProductHistory(str(p["id"]), p["name"], p["category"], days)
        for row in rows:
            if row["product_id"] != p["id"]:
                continue
            cancelled = row["cancelled_at"].astimezone(UTC).date() if row["cancelled_at"] else None
            history.orders.append((row["day"], row["quantity"], cancelled))
            if row["initial_at"] is None or (row["status"] == "cancelled" and cancelled is None):
                history.status_complete = False
        if not history.status_complete:
            history.warnings.append("Order status history is incomplete; reliable as-of reconstruction is unavailable")
        warehouses = {r["warehouse_id"] for r in pairs if r["product_id"] == p["id"]}
        product_events = [r for r in events if r["product_id"] == p["id"]]
        warehouses.update(r["warehouse_id"] for r in product_events)
        balances: dict[Any, int] = {}
        index = 0
        for day in days:
            while index < len(product_events) and product_events[index]["occurred_at"].astimezone(UTC).date() < day:
                event = product_events[index]
                balances[event["warehouse_id"]] = event["balance_after"]
                index += 1
            known = bool(warehouses) and warehouses.issubset(balances)
            minimum = sum(balances.values()) if known else None
            while index < len(product_events) and product_events[index]["occurred_at"].astimezone(UTC).date() == day:
                event = product_events[index]
                balances[event["warehouse_id"]] = event["balance_after"]
                if warehouses.issubset(balances):
                    total = sum(balances.values())
                    minimum = total if minimum is None else min(minimum, total)
                index += 1
            closing = sum(balances.values()) if warehouses and warehouses.issubset(balances) else None
            history.stock.append(closing)
            history.constrained.append(minimum == 0)
        if any(s is None for s in history.stock):
            history.warnings.append("Inventory history has unknown days; stockout effects cannot be fully excluded")
        result.append(history)
    return result
