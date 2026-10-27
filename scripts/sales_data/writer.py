"""Bulk-write a validated simulation inside the caller's seed transaction."""

from __future__ import annotations

import json

import asyncpg

from scripts.sales_data.config import GENERATOR_VERSION
from scripts.sales_data.generator import ADDRESS, Simulation
from scripts.sales_data.validate import validate_simulation


async def write_simulation(conn: asyncpg.Connection, data: Simulation) -> dict[str, int]:
    if not conn.is_in_transaction():
        raise RuntimeError("Simulation writes require an enclosing transaction")
    summary = validate_simulation(data)
    config = {
        "days": data.config.days,
        "seed": data.config.seed,
        "end_date": str(data.config.end_date),
        "profiles": data.profiles,
        "future_receipts_assumed": False,
    }
    await conn.execute(
        """INSERT INTO sales_dataset_runs
        (id, generator_version, random_seed, start_date, end_date, config, summary)
        VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb)""",
        data.run_id,
        GENERATOR_VERSION,
        data.config.seed,
        data.config.start_date,
        data.config.end_date,
        json.dumps(config),
        json.dumps(summary),
    )
    address = json.dumps(ADDRESS)
    await conn.executemany(
        """INSERT INTO orders
        (id, user_id, status, total, shipping_address, billing_address, shipping_carrier, tracking_number, created_at)
        VALUES ($1, $2, $3, $4, $5::jsonb, $5::jsonb, 'Standard Shipping', $6, $7)""",
        [
            (
                r["id"],
                r["user_id"],
                r["status"],
                r["total"],
                address,
                f"TRK{r['id'].hex[:12].upper()}"
                if r["status"] in {"shipped", "out_for_delivery", "delivered"}
                else None,
                r["created_at"],
            )
            for r in data.orders
        ],
    )
    await conn.executemany(
        """INSERT INTO order_items (id, order_id, product_id, quantity, unit_price, subtotal)
        VALUES ($1, $2, $3, $4, $5, $6)""",
        [
            tuple(r[k] for k in ("id", "order_id", "product_id", "quantity", "unit_price", "subtotal"))
            for r in data.items
        ],
    )
    await conn.executemany(
        """INSERT INTO order_status_history (order_id, status, notes, timestamp)
        VALUES ($1, $2, 'Synthetic history', $3)""",
        [(r["order_id"], r["status"], r["timestamp"]) for r in data.statuses],
    )
    await conn.executemany(
        """INSERT INTO returns
        (id, order_id, user_id, reason, status, refund_amount, refund_method, return_label_url, created_at, resolved_at)
        VALUES ($1, $2, $3, 'Synthetic completed return', 'refunded', $4, 'original_payment', $5, $6, $7)""",
        [
            (
                r["id"],
                r["order_id"],
                r["user_id"],
                r["refund_amount"],
                f"https://labels.demo/{r['id']}",
                r["created_at"],
                r["resolved_at"],
            )
            for r in data.returns
        ],
    )
    await conn.executemany(
        """INSERT INTO inventory_movements
        (event_key, product_id, warehouse_id, movement_type, quantity_delta, balance_after,
         order_id, order_item_id, return_id, occurred_at, dataset_run_id, notes)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,'Offline synthetic history')""",
        [
            tuple(
                r[k]
                for k in (
                    "event_key",
                    "product_id",
                    "warehouse_id",
                    "movement_type",
                    "quantity_delta",
                    "balance_after",
                    "order_id",
                    "order_item_id",
                    "return_id",
                    "occurred_at",
                )
            )
            + (data.run_id,)
            for r in data.movements
        ],
    )
    await conn.executemany(
        """INSERT INTO warehouse_inventory (product_id, warehouse_id, quantity)
        VALUES ($1,$2,$3)""",
        [(pid, wh, qty) for (pid, wh), qty in data.inventory.items()],
    )
    await conn.executemany(
        "INSERT INTO price_history (product_id, price, recorded_at) VALUES ($1,$2,$3)",
        [(r["product_id"], r["price"], r["recorded_at"]) for r in data.prices],
    )
    await conn.executemany("UPDATE products SET created_at = $2 WHERE id = $1", list(data.launches.items()))
    # Live checkout reads today's catalog price. Match it to the latest known historical price.
    latest = {r["product_id"]: r["price"] for r in data.prices}
    await conn.executemany("UPDATE products SET price = $2 WHERE id = $1", list(latest.items()))
    await conn.execute("""UPDATE users u SET total_spend = COALESCE((
        SELECT SUM(o.total) FROM orders o WHERE o.user_id = u.id AND o.status NOT IN ('cancelled', 'returned')
    ), 0) WHERE u.role = 'customer'""")
    return summary
