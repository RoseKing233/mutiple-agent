"""Manager inventory, warehouse, product and suggestion APIs. Writes are store_manager/admin only."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from shared import inventory_management as inv
from shared import inventory_suggestions as sug
from shared.db import get_pool

from .manager import Manager

router = APIRouter(prefix="/api/manager", tags=["manager-inventory"])

Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0)]


def http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(404, str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(403, str(exc))
    return HTTPException(409 if "already" in str(exc) else 422, str(exc))


class ThresholdUpdate(BaseModel):
    reorder_threshold: int = Field(ge=0, le=100000)


class StatusUpdate(BaseModel):
    is_active: bool


# ── Inventory rows ──────────────────────────────────────────────────────────


@router.get("/inventory")
async def inventory(
    _user: Manager,
    search: Annotated[str | None, Query(max_length=200)] = None,
    category: str | None = None,
    warehouse_id: uuid.UUID | None = None,
    low_stock_only: bool = False,
    include_inactive: bool = True,
    offset: Offset = 0,
    limit: Limit = 50,
) -> dict:
    async with get_pool().acquire() as conn:
        return await inv.list_inventory(
            conn,
            search=search,
            category=category,
            warehouse_id=warehouse_id,
            low_stock_only=low_stock_only,
            include_inactive=include_inactive,
            offset=offset,
            limit=limit,
        )


@router.post("/inventory", status_code=201)
async def create_inventory(body: inv.InventoryRowCreate, user: Manager) -> dict:
    try:
        async with get_pool().acquire() as conn:
            return await inv.create_inventory_row(conn, body, user["sub"])
    except (ValueError, LookupError) as exc:
        raise http_error(exc) from exc


@router.patch("/inventory/{product_id}/{warehouse_id}")
async def update_inventory(product_id: uuid.UUID, warehouse_id: uuid.UUID, body: ThresholdUpdate, _user: Manager):
    try:
        async with get_pool().acquire() as conn:
            return await inv.update_threshold(conn, product_id, warehouse_id, body.reorder_threshold)
    except (ValueError, LookupError) as exc:
        raise http_error(exc) from exc


@router.post("/inventory/{product_id}/{warehouse_id}/adjustments")
async def adjust_inventory(
    product_id: uuid.UUID, warehouse_id: uuid.UUID, body: inv.StockAdjustment, user: Manager
) -> dict:
    try:
        async with get_pool().acquire() as conn:
            async with conn.transaction():
                return await inv.adjust_stock(conn, product_id, warehouse_id, body, user["sub"])
    except (ValueError, LookupError) as exc:
        raise http_error(exc) from exc


@router.delete("/inventory/{product_id}/{warehouse_id}")
async def delete_inventory(product_id: uuid.UUID, warehouse_id: uuid.UUID, _user: Manager) -> dict:
    try:
        async with get_pool().acquire() as conn:
            return await inv.delete_inventory_row(conn, product_id, warehouse_id)
    except (ValueError, LookupError) as exc:
        raise http_error(exc) from exc


@router.get("/inventory/{product_id}/{warehouse_id}/movements")
async def movements(
    product_id: uuid.UUID, warehouse_id: uuid.UUID, _user: Manager, offset: Offset = 0, limit: Limit = 50
) -> dict:
    async with get_pool().acquire() as conn:
        return await inv.list_movements(conn, product_id, warehouse_id, offset, limit)


# ── Warehouses ──────────────────────────────────────────────────────────────


@router.get("/warehouses")
async def warehouses(_user: Manager) -> dict:
    async with get_pool().acquire() as conn:
        return await inv.list_warehouses(conn)


@router.post("/warehouses", status_code=201)
async def create_warehouse(body: inv.WarehouseCreate, _user: Manager) -> dict:
    async with get_pool().acquire() as conn:
        return await inv.create_warehouse(conn, body)


@router.patch("/warehouses/{warehouse_id}")
async def update_warehouse(warehouse_id: uuid.UUID, body: inv.WarehouseUpdate, _user: Manager) -> dict:
    try:
        async with get_pool().acquire() as conn:
            return await inv.update_warehouse(conn, warehouse_id, body)
    except (ValueError, LookupError) as exc:
        raise http_error(exc) from exc


@router.delete("/warehouses/{warehouse_id}")
async def deactivate_warehouse(warehouse_id: uuid.UUID, _user: Manager) -> dict:
    """Soft delete: movements and orders keep referencing the warehouse."""
    try:
        async with get_pool().acquire() as conn:
            return await inv.update_warehouse(conn, warehouse_id, inv.WarehouseUpdate(is_active=False))
    except (ValueError, LookupError) as exc:
        raise http_error(exc) from exc


# ── Products ────────────────────────────────────────────────────────────────


@router.post("/products", status_code=201)
async def create_product(body: inv.ProductCreate, user: Manager) -> dict:
    try:
        async with get_pool().acquire() as conn:
            return await inv.create_product(conn, body, user["sub"])
    except (ValueError, LookupError) as exc:
        raise http_error(exc) from exc


@router.get("/products/{product_id}/detail")
async def product_detail(product_id: uuid.UUID, _user: Manager) -> dict:
    try:
        async with get_pool().acquire() as conn:
            return await inv.get_product(conn, product_id)
    except LookupError as exc:
        raise http_error(exc) from exc


@router.patch("/products/{product_id}")
async def update_product(product_id: uuid.UUID, body: inv.ProductUpdate, _user: Manager) -> dict:
    try:
        async with get_pool().acquire() as conn:
            return await inv.update_product(conn, product_id, body)
    except (ValueError, LookupError) as exc:
        raise http_error(exc) from exc


@router.patch("/products/{product_id}/status")
async def product_status(product_id: uuid.UUID, body: StatusUpdate, _user: Manager) -> dict:
    try:
        async with get_pool().acquire() as conn:
            return await inv.set_product_status(conn, product_id, body.is_active)
    except LookupError as exc:
        raise http_error(exc) from exc


# ── Suggestions ─────────────────────────────────────────────────────────────


@router.post("/inventory-suggestions/generate")
async def generate_suggestions(body: sug.GenerateRequest, user: Manager) -> dict:
    try:
        return await sug.generate_suggestions(get_pool(), user["sub"], body)
    except (ValueError, LookupError, PermissionError) as exc:
        raise http_error(exc) from exc


@router.get("/inventory-suggestions")
async def suggestions(
    _user: Manager,
    status: Literal["pending", "accepted", "rejected", "superseded", "all"] = "pending",
    suggestion_type: Literal["restock", "overstock"] | None = None,
    product_id: uuid.UUID | None = None,
    offset: Offset = 0,
    limit: Limit = 50,
) -> dict:
    async with get_pool().acquire() as conn:
        return await sug.list_suggestions(
            conn,
            status=None if status == "all" else status,
            suggestion_type=suggestion_type,
            product_id=product_id,
            offset=offset,
            limit=limit,
        )


@router.post("/inventory-suggestions/{suggestion_id}/decision")
async def decide(suggestion_id: uuid.UUID, body: sug.Decision, user: Manager) -> dict:
    try:
        async with get_pool().acquire() as conn:
            async with conn.transaction():
                return await sug.decide_suggestion(conn, suggestion_id, body, user["sub"])
    except (ValueError, LookupError, PermissionError) as exc:
        raise http_error(exc) from exc
