"""Manager tools for the whole store, without seller ownership filters."""

from __future__ import annotations

from typing import Annotated

from agent_framework import tool
from pydantic import Field

from shared import store_management
from shared.context import current_user_email, current_user_role
from shared.db import get_pool
from shared.tool_inputs import clamp_limit


def _authorize() -> None:
    if not current_user_email.get() or current_user_role.get() != "store_manager":
        raise PermissionError("Store manager access required")


@tool(
    name="get_store_products",
    description="List all store products, including unlisted products. Store manager only.",
)
async def get_store_products(
    category: Annotated[str | None, Field(description="Optional category filter")] = None,
    limit: Annotated[int, Field(description="Max results")] = 50,
) -> dict:
    _authorize()
    async with get_pool().acquire() as conn:
        return await store_management.list_products(conn, category, clamp_limit(limit, default=50, maximum=200))


@tool(
    name="get_store_orders",
    description="List all store orders and their status, across all products. Store manager only.",
)
async def get_store_orders(
    status: Annotated[str | None, Field(description="Optional order status")] = None,
    limit: Annotated[int, Field(description="Max results")] = 20,
) -> dict:
    _authorize()
    async with get_pool().acquire() as conn:
        return await store_management.list_orders(conn, status, clamp_limit(limit, default=20, maximum=200))


@tool(
    name="get_store_stats",
    description="Whole-store product/order counts, item sales amount and average rating. Store manager only.",
)
async def get_store_stats() -> dict:
    _authorize()
    async with get_pool().acquire() as conn:
        return await store_management.statistics(conn)


@tool(name="get_store_inventory", description="Read inventory across every product and warehouse. Store manager only.")
async def get_store_inventory(
    low_stock_only: Annotated[bool, Field(description="Only show low stock items")] = False,
) -> list[dict]:
    _authorize()
    async with get_pool().acquire() as conn:
        return await store_management.inventory(conn, low_stock_only)
