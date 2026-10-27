"""Manager inventory, warehouse and product maintenance shared by HTTP routes and Agent tools.

Every stock change goes through ``change_inventory`` inside the caller's transaction, so
balances and ``inventory_movements`` never drift. Products and warehouses are deactivated,
never deleted: orders and movements keep referencing them.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Literal

import asyncpg
from pydantic import BaseModel, ConfigDict, Field

from shared.inventory_ledger import change_inventory
from shared.sales_analysis import serialize

AdjustmentKind = Literal["manual_receipt", "manual_issue", "stock_count_adjustment"]


class StockAdjustment(BaseModel):
    """Receipt/issue take a positive ``quantity``; a stock count takes the counted total."""

    model_config = ConfigDict(extra="forbid")
    kind: AdjustmentKind
    quantity: int = Field(ge=0, le=100000)
    reason: str = Field(min_length=3, max_length=500)
    request_id: uuid.UUID = Field(default_factory=uuid.uuid4)


class InventoryRowCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    reorder_threshold: int = Field(default=10, ge=0, le=100000)
    initial_quantity: int = Field(default=0, ge=0, le=100000)
    request_id: uuid.UUID = Field(default_factory=uuid.uuid4)


class WarehouseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    location: str = Field(min_length=1, max_length=255)
    region: str = Field(min_length=1, max_length=50)


class WarehouseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=100)
    location: str | None = Field(default=None, min_length=1, max_length=255)
    region: str | None = Field(default=None, min_length=1, max_length=50)
    is_active: bool | None = None


class ProductStock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    warehouse_id: uuid.UUID
    reorder_threshold: int = Field(default=10, ge=0, le=100000)
    initial_quantity: int = Field(default=0, ge=0, le=100000)


class ProductCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=5000)
    category: str = Field(min_length=1, max_length=100)
    brand: str | None = Field(default=None, max_length=100)
    price: float = Field(gt=0, le=1_000_000)
    original_price: float | None = Field(default=None, gt=0, le=1_000_000)
    image_url: str | None = Field(default=None, max_length=500)
    specs: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True
    stock: list[ProductStock] = Field(default_factory=list, max_length=50)


class ProductUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, min_length=1, max_length=5000)
    category: str | None = Field(default=None, min_length=1, max_length=100)
    brand: str | None = Field(default=None, max_length=100)
    price: float | None = Field(default=None, gt=0, le=1_000_000)
    original_price: float | None = Field(default=None, gt=0, le=1_000_000)
    image_url: str | None = Field(default=None, max_length=500)
    specs: dict[str, Any] | None = None


def _notes(reason: str, actor_email: str) -> str:
    return f"{reason} (by {actor_email})"


async def manager_id(conn: asyncpg.Connection, email: str) -> uuid.UUID:
    owner = await conn.fetchval(
        "SELECT id FROM users WHERE email=$1 AND role IN ('store_manager','admin') AND is_active", email
    )
    if owner is None:
        raise PermissionError("Store manager account required")
    return owner


async def resolve_warehouse(conn: asyncpg.Connection, ref: str) -> uuid.UUID:
    """Accept a UUID or a name ("Central", "central warehouse"); chat users speak in names."""
    try:
        return uuid.UUID(ref)
    except ValueError:
        pass
    rows = await conn.fetch(
        "SELECT id, name FROM warehouses WHERE name ILIKE $1 OR name ILIKE '%' || $1 || '%' OR region ILIKE $1",
        ref.strip(),
    )
    exact = [r for r in rows if r["name"].lower() == ref.strip().lower()]
    if len(exact) == 1 or len(rows) == 1:
        return (exact or rows)[0]["id"]
    if not rows:
        raise LookupError(f"No warehouse matches '{ref}'")
    raise ValueError(f"'{ref}' matches several warehouses: {', '.join(r['name'] for r in rows)}")


# ── Inventory rows ──────────────────────────────────────────────────────────


async def list_inventory(
    conn: asyncpg.Connection,
    *,
    search: str | None = None,
    category: str | None = None,
    warehouse_id: uuid.UUID | None = None,
    low_stock_only: bool = False,
    include_inactive: bool = True,
    offset: int = 0,
    limit: int = 50,
) -> dict:
    where = """WHERE ($1::text IS NULL OR p.name ILIKE '%' || $1 || '%' OR p.brand ILIKE '%' || $1 || '%')
                 AND ($2::text IS NULL OR p.category=$2)
                 AND ($3::uuid IS NULL OR w.id=$3)
                 AND (NOT $4 OR wi.quantity <= wi.reorder_threshold)
                 AND ($5 OR (p.is_active AND w.is_active))"""
    args = [search or None, category or None, warehouse_id, low_stock_only, include_inactive]
    rows = await conn.fetch(
        f"""SELECT p.id AS product_id, p.name AS product_name, p.category, p.brand,
                   p.is_active AS product_active, w.id AS warehouse_id, w.name AS warehouse_name,
                   w.region, w.is_active AS warehouse_active, wi.quantity, wi.reorder_threshold,
                   wi.quantity <= wi.reorder_threshold AS low_stock, wi.quantity = 0 AS out_of_stock
            FROM warehouse_inventory wi
            JOIN products p ON p.id = wi.product_id
            JOIN warehouses w ON w.id = wi.warehouse_id
            {where}
            ORDER BY (wi.quantity <= wi.reorder_threshold) DESC, p.name, w.name
            LIMIT $6 OFFSET $7""",
        *args,
        limit,
        offset,
    )
    total = await conn.fetchval(
        f"""SELECT COUNT(*) FROM warehouse_inventory wi
            JOIN products p ON p.id = wi.product_id JOIN warehouses w ON w.id = wi.warehouse_id {where}""",
        *args,
    )
    return {"items": serialize(rows), "total": total, "offset": offset, "limit": limit}


async def _active_warehouse(conn: asyncpg.Connection, warehouse_id: uuid.UUID) -> None:
    active = await conn.fetchval("SELECT is_active FROM warehouses WHERE id=$1", warehouse_id)
    if active is None:
        raise LookupError("Warehouse not found")
    if not active:
        raise ValueError("Warehouse is inactive; reactivate it before adding stock")


async def create_inventory_row(conn: asyncpg.Connection, body: InventoryRowCreate, actor_email: str) -> dict:
    async with conn.transaction():
        if not await conn.fetchval("SELECT EXISTS(SELECT 1 FROM products WHERE id=$1)", body.product_id):
            raise LookupError("Product not found")
        await _active_warehouse(conn, body.warehouse_id)
        inserted = await conn.fetchval(
            """INSERT INTO warehouse_inventory(product_id, warehouse_id, quantity, reorder_threshold)
               VALUES($1,$2,0,$3) ON CONFLICT DO NOTHING RETURNING 1""",
            body.product_id,
            body.warehouse_id,
            body.reorder_threshold,
        )
        if not inserted:
            raise ValueError("This product already has an inventory row in this warehouse")
        balance = 0
        if body.initial_quantity:
            balance = await change_inventory(
                conn,
                product_id=body.product_id,
                warehouse_id=body.warehouse_id,
                quantity_delta=body.initial_quantity,
                movement_type="manual_receipt",
                event_key=f"manual:{body.request_id}",
                notes=_notes("Initial stock for new inventory row", actor_email),
            )
    return {"product_id": str(body.product_id), "warehouse_id": str(body.warehouse_id), "quantity": balance}


async def update_threshold(
    conn: asyncpg.Connection, product_id: uuid.UUID, warehouse_id: uuid.UUID, reorder_threshold: int
) -> dict:
    if reorder_threshold < 0:
        raise ValueError("Reorder threshold must be nonnegative")
    row = await conn.fetchrow(
        """UPDATE warehouse_inventory SET reorder_threshold=$3
           WHERE product_id=$1 AND warehouse_id=$2 RETURNING quantity, reorder_threshold""",
        product_id,
        warehouse_id,
        reorder_threshold,
    )
    if row is None:
        raise LookupError("Inventory row not found")
    return {"product_id": str(product_id), "warehouse_id": str(warehouse_id), **dict(row)}


async def adjust_stock(
    conn: asyncpg.Connection,
    product_id: uuid.UUID,
    warehouse_id: uuid.UUID,
    body: StockAdjustment,
    actor_email: str,
) -> dict:
    """Must run inside the caller's transaction so it composes with other business updates."""
    event_key = f"manual:{body.request_id}"
    previous = await conn.fetchrow(
        "SELECT product_id, warehouse_id, quantity_delta, balance_after FROM inventory_movements WHERE event_key=$1",
        event_key,
    )
    if previous:
        # A retried request returns the original result; a stock count must not recompute its delta.
        if (previous["product_id"], previous["warehouse_id"]) != (product_id, warehouse_id):
            raise ValueError("Request ID already used for a different inventory row")
        return {"quantity_delta": previous["quantity_delta"], "quantity": previous["balance_after"], "replayed": True}
    current = await conn.fetchval(
        "SELECT quantity FROM warehouse_inventory WHERE product_id=$1 AND warehouse_id=$2 FOR UPDATE",
        product_id,
        warehouse_id,
    )
    if current is None:
        raise LookupError("Inventory row not found; create it first")
    if body.kind == "manual_receipt":
        delta = body.quantity
    elif body.kind == "manual_issue":
        delta = -body.quantity
    else:
        delta = body.quantity - current
    if body.kind != "stock_count_adjustment" and delta == 0:
        raise ValueError("Quantity must be positive")
    if delta > 0:
        await _active_warehouse(conn, warehouse_id)
    if current + delta < 0:
        raise ValueError(f"Insufficient inventory: {current} available, {-delta} requested")
    balance = await change_inventory(
        conn,
        product_id=product_id,
        warehouse_id=warehouse_id,
        quantity_delta=delta,
        movement_type=body.kind,
        event_key=event_key,
        notes=_notes(body.reason, actor_email),
    )
    return {"quantity_delta": delta, "quantity": balance, "previous_quantity": current, "replayed": False}


async def delete_inventory_row(conn: asyncpg.Connection, product_id: uuid.UUID, warehouse_id: uuid.UUID) -> dict:
    async with conn.transaction():
        quantity = await conn.fetchval(
            "SELECT quantity FROM warehouse_inventory WHERE product_id=$1 AND warehouse_id=$2 FOR UPDATE",
            product_id,
            warehouse_id,
        )
        if quantity is None:
            raise LookupError("Inventory row not found")
        if quantity:
            raise ValueError(f"Inventory row still holds {quantity} units; issue or count it to zero first")
        await conn.execute(
            "DELETE FROM warehouse_inventory WHERE product_id=$1 AND warehouse_id=$2", product_id, warehouse_id
        )
    return {"deleted": True, "movement_history": "kept"}


async def list_movements(
    conn: asyncpg.Connection, product_id: uuid.UUID, warehouse_id: uuid.UUID, offset: int = 0, limit: int = 50
) -> dict:
    rows = await conn.fetch(
        """SELECT id, event_key, movement_type, quantity_delta, balance_after, order_id, return_id,
                  occurred_at, recorded_at, notes
           FROM inventory_movements WHERE product_id=$1 AND warehouse_id=$2
           ORDER BY occurred_at DESC, id DESC LIMIT $3 OFFSET $4""",
        product_id,
        warehouse_id,
        limit,
        offset,
    )
    total = await conn.fetchval(
        "SELECT COUNT(*) FROM inventory_movements WHERE product_id=$1 AND warehouse_id=$2", product_id, warehouse_id
    )
    return {"movements": serialize(rows), "total": total, "offset": offset, "limit": limit}


# ── Warehouses ──────────────────────────────────────────────────────────────


async def list_warehouses(conn: asyncpg.Connection) -> dict:
    rows = await conn.fetch(
        """SELECT w.id, w.name, w.location, w.region, w.is_active, w.created_at,
                  COALESCE(SUM(wi.quantity), 0) AS total_quantity, COUNT(wi.product_id) AS product_rows
           FROM warehouses w LEFT JOIN warehouse_inventory wi ON wi.warehouse_id = w.id
           GROUP BY w.id ORDER BY w.is_active DESC, w.name"""
    )
    return {"warehouses": serialize(rows)}


async def create_warehouse(conn: asyncpg.Connection, body: WarehouseCreate) -> dict:
    row = await conn.fetchrow(
        "INSERT INTO warehouses(name, location, region) VALUES($1,$2,$3) RETURNING *",
        body.name,
        body.location,
        body.region.lower(),
    )
    return serialize([row])[0]


async def update_warehouse(conn: asyncpg.Connection, warehouse_id: uuid.UUID, body: WarehouseUpdate) -> dict:
    async with conn.transaction():
        current = await conn.fetchrow("SELECT * FROM warehouses WHERE id=$1 FOR UPDATE", warehouse_id)
        if current is None:
            raise LookupError("Warehouse not found")
        if body.is_active is False and current["is_active"]:
            stock = await conn.fetchval(
                "SELECT COALESCE(SUM(quantity),0) FROM warehouse_inventory WHERE warehouse_id=$1", warehouse_id
            )
            if stock:
                raise ValueError(f"Warehouse still holds {stock} units; move or issue them before deactivating")
        changes = body.model_dump(exclude_none=True)
        if "region" in changes:
            changes["region"] = changes["region"].lower()
        if not changes:
            return serialize([current])[0]
        columns = list(changes)
        assignments = ", ".join(f"{column}=${i + 2}" for i, column in enumerate(columns))
        row = await conn.fetchrow(
            f"UPDATE warehouses SET {assignments} WHERE id=$1 RETURNING *",
            warehouse_id,
            *[changes[c] for c in columns],
        )
    return serialize([row])[0]


# ── Products ────────────────────────────────────────────────────────────────


async def create_product(conn: asyncpg.Connection, body: ProductCreate, actor_email: str) -> dict:
    warehouses = [s.warehouse_id for s in body.stock]
    if len(set(warehouses)) != len(warehouses):
        raise ValueError("Each warehouse may appear only once")
    async with conn.transaction():
        product_id = await conn.fetchval(
            """INSERT INTO products(name, description, category, brand, price, original_price, image_url,
                                    specs, is_active)
               VALUES($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9) RETURNING id""",
            body.name,
            body.description,
            body.category,
            body.brand,
            body.price,
            body.original_price,
            body.image_url,
            json.dumps(body.specs),
            body.is_active,
        )
        for stock in body.stock:
            await _active_warehouse(conn, stock.warehouse_id)
            await conn.execute(
                "INSERT INTO warehouse_inventory(product_id, warehouse_id, quantity, reorder_threshold) "
                "VALUES($1,$2,0,$3)",
                product_id,
                stock.warehouse_id,
                stock.reorder_threshold,
            )
            # A zero opening quantity is still recorded so the row's history starts at creation.
            await change_inventory(
                conn,
                product_id=product_id,
                warehouse_id=stock.warehouse_id,
                quantity_delta=stock.initial_quantity,
                movement_type="manual_receipt",
                event_key=f"product-create:{product_id}:{stock.warehouse_id}",
                notes=_notes("Initial stock for new product", actor_email),
            )
        return await get_product(conn, product_id)


async def get_product(conn: asyncpg.Connection, product_id: uuid.UUID) -> dict:
    row = await conn.fetchrow(
        """SELECT id, name, description, category, brand, price, original_price, image_url, specs,
                  is_active, created_at FROM products WHERE id=$1""",
        product_id,
    )
    if row is None:
        raise LookupError("Product not found")
    product = serialize([row])[0]
    if isinstance(product.get("specs"), str):
        product["specs"] = json.loads(product["specs"])
    stock = await conn.fetch(
        """SELECT w.id AS warehouse_id, w.name AS warehouse_name, wi.quantity, wi.reorder_threshold
           FROM warehouse_inventory wi JOIN warehouses w ON w.id=wi.warehouse_id
           WHERE wi.product_id=$1 ORDER BY w.name""",
        product_id,
    )
    product["stock"] = serialize(stock)
    product["total_quantity"] = sum(r["quantity"] for r in stock)
    return product


async def update_product(conn: asyncpg.Connection, product_id: uuid.UUID, body: ProductUpdate) -> dict:
    changes = body.model_dump(exclude_unset=True)
    for required in ("name", "description", "category", "price"):
        if required in changes and changes[required] is None:
            raise ValueError(f"{required} cannot be empty")
    if "specs" in changes:
        changes["specs"] = json.dumps(changes["specs"] or {})
    if changes:
        columns = list(changes)
        assignments = ", ".join(
            f"{column}=${i + 2}{'::jsonb' if column == 'specs' else ''}" for i, column in enumerate(columns)
        )
        updated = await conn.fetchval(
            f"UPDATE products SET {assignments} WHERE id=$1 RETURNING id",
            product_id,
            *[changes[c] for c in columns],
        )
        if updated is None:
            raise LookupError("Product not found")
    return await get_product(conn, product_id)


async def set_product_status(conn: asyncpg.Connection, product_id: uuid.UUID, is_active: bool) -> dict:
    """Delisting hides the product from shopping and blocks checkout; history stays intact."""
    async with conn.transaction():
        updated = await conn.fetchval(
            "UPDATE products SET is_active=$2 WHERE id=$1 RETURNING id", product_id, is_active
        )
        if updated is None:
            raise LookupError("Product not found")
        if not is_active:
            # A delisted product cannot be restocked by an old suggestion.
            await conn.execute(
                """UPDATE inventory_suggestions SET status='superseded', decision_note='Product delisted'
                   WHERE product_id=$1 AND status='pending'""",
                product_id,
            )
    return {"product_id": str(product_id), "is_active": is_active}
