"""Manager-only read APIs; numeric analysis does not invoke an LLM."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field

from shared.db import get_pool
from shared.forecasting.config import ForecastRequest
from shared.forecasting.service import performance_report
from shared.forecasting.store import get_report, list_reports, save_report
from shared.sales_analysis import AnalysisWindow, historical_analysis, product_list, product_orders, serialize

from .legacy import require_auth

router = APIRouter(prefix="/api/manager", tags=["manager"])


async def require_manager(user: dict[str, Any] = Depends(require_auth)) -> dict[str, Any]:
    if user.get("role") != "store_manager":
        raise HTTPException(403, "Store manager access required")
    return user


def analysis_window(start_date: date | None = None, end_date: date | None = None) -> AnalysisWindow:
    end = end_date or datetime.now(UTC).date()
    try:
        return AnalysisWindow(start_date or end - timedelta(days=27), end)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


Window = Annotated[AnalysisWindow, Depends(analysis_window)]
Manager = Annotated[dict[str, Any], Depends(require_manager)]


class SaveAnalysisRequest(ForecastRequest):
    request_id: uuid.UUID = Field(default_factory=uuid.uuid4)


@router.get("/performance")
async def performance(
    _user: Manager,
    as_of: date | None = None,
    category: str | None = None,
    product_id: uuid.UUID | None = None,
) -> dict:
    try:
        spec = ForecastRequest(**({"as_of": as_of} if as_of else {}), category=category, product_id=product_id)
        async with get_pool().acquire() as conn:
            async with conn.transaction(isolation="repeatable_read", readonly=True):
                return await performance_report(conn, spec)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/analysis-runs")
async def create_analysis(body: SaveAnalysisRequest, user: Manager) -> dict:
    spec = ForecastRequest.model_validate(body.model_dump(exclude={"request_id"}))
    try:
        return await save_report(get_pool(), user["sub"], spec, body.request_id)
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409 if "Request ID" in str(exc) else 422, str(exc)) from exc


@router.get("/analysis-runs")
async def saved_analyses(
    user: Manager,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    async with get_pool().acquire() as conn:
        return await list_reports(conn, user["sub"], limit, offset)


@router.get("/analysis-runs/{run_id}")
async def saved_analysis(run_id: uuid.UUID, user: Manager) -> dict:
    async with get_pool().acquire() as conn:
        try:
            return await get_report(conn, user["sub"], run_id)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc


@router.get("/catalog")
async def catalog(_user: Manager) -> dict:
    async with get_pool().acquire() as conn:
        rows = await conn.fetch("SELECT id,name,category FROM products ORDER BY name,id")
    return {"products": serialize(rows), "categories": sorted({r["category"] for r in rows})}


@router.get("/products")
async def products(
    _user: Manager,
    window: Window,
    category: str | None = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    product_id: uuid.UUID | None = None,
) -> dict:
    async with get_pool().acquire() as conn:
        async with conn.transaction(isolation="repeatable_read", readonly=True):
            return await product_list(conn, window, category, search, offset, limit, product_id)


@router.get("/analysis")
async def analysis(
    _user: Manager,
    window: Window,
    category: str | None = None,
    product_id: uuid.UUID | None = None,
) -> dict:
    async with get_pool().acquire() as conn:
        async with conn.transaction(isolation="repeatable_read", readonly=True):
            try:
                return await historical_analysis(conn, window, category, product_id)
            except LookupError as exc:
                raise HTTPException(404, str(exc)) from exc


@router.get("/products/{product_id}/orders")
async def orders(
    product_id: uuid.UUID,
    _user: Manager,
    window: Window,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
) -> dict:
    async with get_pool().acquire() as conn:
        async with conn.transaction(isolation="repeatable_read", readonly=True):
            if not await conn.fetchval("SELECT EXISTS(SELECT 1 FROM products WHERE id=$1)", product_id):
                raise HTTPException(404, "Product not found")
            return await product_orders(conn, product_id, window, offset, limit)
