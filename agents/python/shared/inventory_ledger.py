"""Atomic stock changes. Call inside the SAME transaction as the business operation.

Cancellation reversals reuse these helpers after authorization and state checks.
Recording a recommendation must never change inventory.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import asyncpg


async def change_inventory(
    conn: asyncpg.Connection,
    *,
    product_id: uuid.UUID,
    warehouse_id: uuid.UUID,
    quantity_delta: int,
    movement_type: str,
    event_key: str,
    order_id: uuid.UUID | None = None,
    order_item_id: uuid.UUID | None = None,
    return_id: uuid.UUID | None = None,
    occurred_at: datetime | None = None,
    notes: str = "",
) -> int:
    """Lock stock, reject negative balances, deduplicate retries, and append history."""
    if not conn.is_in_transaction():
        raise RuntimeError("change_inventory requires an enclosing database transaction")
    if not event_key or not movement_type or not isinstance(quantity_delta, int) or isinstance(quantity_delta, bool):
        raise ValueError("A nonempty event key/type and an integer quantity delta are required")
    moment = occurred_at or datetime.now(UTC)
    if moment.tzinfo is None:
        raise ValueError("occurred_at must include a timezone")
    await conn.execute("SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", event_key)
    existing = await conn.fetchrow("SELECT * FROM inventory_movements WHERE event_key = $1", event_key)
    if existing:
        expected = (product_id, warehouse_id, quantity_delta, movement_type, order_id, order_item_id, return_id)
        actual = tuple(
            existing[key]
            for key in (
                "product_id",
                "warehouse_id",
                "quantity_delta",
                "movement_type",
                "order_id",
                "order_item_id",
                "return_id",
            )
        )
        if actual != expected:
            raise ValueError("Event key already belongs to a different inventory operation")
        return existing["balance_after"]
    stock = await conn.fetchval(
        "SELECT quantity FROM warehouse_inventory WHERE product_id = $1 AND warehouse_id = $2 FOR UPDATE",
        product_id,
        warehouse_id,
    )
    if stock is None:
        raise ValueError("Inventory row does not exist; create a zero-stock row first")
    # A concurrent transaction may have held this stock lock; timestamp AFTER waiting.
    moment = occurred_at or datetime.now(UTC)
    latest_row = await conn.fetchrow(
        """SELECT occurred_at, balance_after FROM inventory_movements
           WHERE product_id = $1 AND warehouse_id = $2 ORDER BY occurred_at DESC, id DESC LIMIT 1""",
        product_id,
        warehouse_id,
    )
    latest = latest_row["occurred_at"] if latest_row else None
    if latest_row and latest_row["balance_after"] != stock:
        raise ValueError("Current stock differs from ledger; reconcile unrecorded changes before continuing")
    if latest and moment < latest:
        raise ValueError("Backdated stock changes require a separate history rebuild")
    if latest is None:
        await conn.execute(
            """INSERT INTO inventory_movements
               (event_key, product_id, warehouse_id, movement_type, quantity_delta, balance_after, occurred_at, notes)
               VALUES ($1, $2, $3, 'opening', $4, $4, $5, 'First recorded stock baseline')""",
            f"opening:{warehouse_id}:{product_id}",
            product_id,
            warehouse_id,
            stock,
            moment - timedelta(microseconds=1),
        )
    balance = stock + quantity_delta
    if balance < 0:
        raise ValueError("Insufficient inventory")
    await conn.execute(
        "UPDATE warehouse_inventory SET quantity = $3 WHERE product_id = $1 AND warehouse_id = $2",
        product_id,
        warehouse_id,
        balance,
    )
    await conn.execute(
        """INSERT INTO inventory_movements
           (event_key, product_id, warehouse_id, movement_type, quantity_delta, balance_after,
            order_id, order_item_id, return_id, occurred_at, notes)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)""",
        event_key,
        product_id,
        warehouse_id,
        movement_type,
        quantity_delta,
        balance,
        order_id,
        order_item_id,
        return_id,
        moment,
        notes,
    )
    return balance


async def release_cancelled_order_inventory(
    conn: asyncpg.Connection,
    *,
    order_id: uuid.UUID,
) -> int:
    """Reverse recorded checkout sales for a cancelled, not-yet-shipped order."""
    if not conn.is_in_transaction():
        raise RuntimeError("release_cancelled_order_inventory requires an enclosing database transaction")

    sales = await conn.fetch(
        """SELECT id, event_key, product_id, warehouse_id, quantity_delta
           FROM inventory_movements
           WHERE order_id = $1 AND movement_type = 'sale' AND quantity_delta < 0
           ORDER BY product_id, warehouse_id, id""",
        order_id,
    )
    released_quantity = 0
    for sale in sales:
        quantity = -sale["quantity_delta"]
        await change_inventory(
            conn,
            product_id=sale["product_id"],
            warehouse_id=sale["warehouse_id"],
            quantity_delta=quantity,
            movement_type="cancel_release",
            event_key=f"cancel:{sale['event_key']}",
            order_id=order_id,
            notes="Released from cancelled order",
        )
        released_quantity += quantity
    return released_quantity
