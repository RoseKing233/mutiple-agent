"""Shared HTTP/Agent service. CPU work runs off the event loop."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta
from typing import Any

import asyncpg

from shared.forecasting.config import ENGINE_VERSION, ForecastRequest, PerformanceRules
from shared.forecasting.data import ProductHistory, load_histories
from shared.forecasting.models import fit_forecast
from shared.forecasting.performance import assess


def stock_projection(stock: int | None, units: list[float], as_of: date) -> dict[str, Any]:
    cumulative, shortfall, depletion = 0.0, 0.0, None
    series = []
    for i, demand in enumerate(units):
        day = str(as_of + timedelta(days=i + 1))
        cumulative += demand
        remaining = max(0.0, stock - cumulative) if stock is not None else None
        shortage = max(0.0, cumulative - stock) if stock is not None else None
        if stock is not None and stock > 0 and cumulative >= stock and depletion is None:
            depletion = day
        series.append(
            {
                "date": day,
                "units": round(demand, 4),
                "stock": round(remaining, 4) if remaining is not None else None,
                "shortfall": round(shortage - shortfall, 4) if shortage is not None else None,
            }
        )
        shortfall = shortage or 0.0
    return {
        "series": series,
        "stockout_date": depletion,
        "unmet_units": round(shortfall, 4) if stock is not None else None,
        "stockout_status": "unknown_stock"
        if stock is None
        else "already_out_of_stock"
        if stock == 0
        else "within_horizon"
        if depletion
        else "not_within_horizon",
    }


def calculate(histories: list[ProductHistory], spec: ForecastRequest) -> dict[str, Any]:
    products = []
    for history in histories:
        performance = assess(history, spec.rules)
        forecast = fit_forecast(history, spec.horizon)
        if not forecast["available"]:
            forecast["stockout_status"] = (
                "already_out_of_stock" if performance["stock_at_cutoff"] == 0 else "unavailable_forecast"
            )
        if forecast["available"]:
            stock = performance["stock_at_cutoff"]
            projected = stock_projection(stock, forecast.pop("units"), spec.as_of)
            lower, upper = forecast.pop("lower"), forecast.pop("upper")
            for i, row in enumerate(projected["series"]):
                row["lower_units"] = round(lower[i], 4) if lower is not None else None
                row["upper_units"] = round(upper[i], 4) if upper is not None else None
            forecast.update(projected)
            forecast["earlier_stockout_scenario"] = (
                stock_projection(stock, upper, spec.as_of)["stockout_date"] if upper else None
            )
            forecast["later_stockout_scenario"] = (
                stock_projection(stock, lower, spec.as_of)["stockout_date"] if lower else None
            )
        products.append(
            {
                "product_id": history.product_id,
                "name": history.name,
                "category": history.category,
                "performance": performance,
                "forecast": forecast,
            }
        )
    available = [p for p in products if p["forecast"]["available"]]
    complete = bool(products) and len(available) == len(products)
    series = []
    for i in range(spec.horizon):
        rows = [p["forecast"]["series"][i] for p in available]
        stock_known = complete and all(r["stock"] is not None for r in rows)
        series.append(
            {
                "date": str(spec.as_of + timedelta(days=i + 1)),
                "units": round(sum(r["units"] for r in rows), 4) if complete else None,
                "available_product_units": round(sum(r["units"] for r in rows), 4) if rows else None,
                "stock": round(sum(r["stock"] for r in rows), 4) if stock_known else None,
            }
        )
    fingerprint = hashlib.sha256(
        json.dumps([asdict(h) for h in histories], default=str, sort_keys=True).encode()
    ).hexdigest()
    return {
        "engine_version": ENGINE_VERSION,
        "parameters": spec.model_dump(mode="json"),
        "generated_at": datetime.now(UTC).isoformat(),
        "data_fingerprint": fingerprint,
        "stock_baseline": f"End of {spec.as_of} UTC; excludes transactions after this cutoff",
        "assumptions": [
            "No future receipts, returns, cancellations or manual stock adjustments",
            "Sales = order units excluding cancellations known at each cutoff; returns remain included",
            "Forecast demand is unconstrained; projected stock is floored at zero; excess demand is shortfall",
            "Forecast training uses up to 180 complete UTC days, independent of chart start date",
            "Whole-store stock is pooled across warehouses; warehouse allocation constraints are not modelled",
            "Backtests use event-time status history; late historical corrections can change regenerated results",
        ],
        "products": products,
        "series": series,
        "summary": {
            "product_count": len(products),
            "forecastable_products": len(available),
            "complete": complete,
            "growing": sum(p["performance"]["trend"] == "growing" for p in products),
            "declining": sum(p["performance"]["trend"] == "declining" for p in products),
            "slow_moving": sum(p["performance"]["slow_moving"] is True for p in products),
            "overstock": sum(p["performance"]["overstock"] is True for p in products),
        },
    }


async def forecast_report(conn: asyncpg.Connection, spec: ForecastRequest) -> dict[str, Any]:
    histories = await load_histories(conn, spec)
    return await asyncio.to_thread(calculate, histories, spec)


async def performance_report(conn: asyncpg.Connection, spec: ForecastRequest) -> dict[str, Any]:
    histories = await load_histories(conn, spec)
    products = [
        {"product_id": h.product_id, "name": h.name, "category": h.category, **assess(h, spec.rules)} for h in histories
    ]
    return {
        "as_of": str(spec.as_of),
        "rules": spec.rules.model_dump(),
        "engine_version": ENGINE_VERSION,
        "products": products,
        **performance_guidance(products, spec.rules),
    }


def performance_guidance(products: list[dict[str, Any]], rules: PerformanceRules) -> dict[str, Any]:
    """Explicit authoritative groups/formulas for narration; do not reclassify in the LLM."""
    return {
        "rule_descriptions": {
            "growing": (
                f"growth_percent >= {rules.trend_percent:g} AND recent_units - previous_units >= "
                f"{rules.trend_min_units}; the minimum applies to the DIFFERENCE, not recent sales"
            ),
            "declining": (
                f"growth_percent <= -{rules.trend_percent:g} AND previous_units - recent_units >= "
                f"{rules.trend_min_units}; the minimum applies to the DIFFERENCE, not recent sales"
            ),
            "slow_moving": (
                f"recent_units <= {rules.slow_max_units} OR consecutive_zero_days >= {rules.no_sale_days}; "
                "requires complete recent history and stock availability"
            ),
            "overstock": (
                f"stock_at_cutoff >= {rules.overstock_min_units} AND days_of_cover > {rules.overstock_days}; "
                "requires complete recent history and stock availability"
            ),
        },
        "classification_groups": {
            "growing": [p["name"] for p in products if p["trend"] == "growing"],
            "declining": [p["name"] for p in products if p["trend"] == "declining"],
            "slow_moving": [p["name"] for p in products if p["slow_moving"] is True],
            "overstock": [p["name"] for p in products if p["overstock"] is True],
            "stockout_affected": [p["name"] for p in products if p["trend"] == "stockout_affected"],
            "insufficient_history": [p["name"] for p in products if p["trend"] == "insufficient_history"],
        },
        "field_definitions": {
            "consecutive_zero_sales_days": "Consecutive days with zero SALES through cutoff, not days out of stock",
            "consecutive_zero_days": "Legacy alias of consecutive_zero_sales_days; never a stockout-day count",
            "recent_stockout_days": (
                "Days with observed intraday stockout in the recent comparison window; not necessarily consecutive"
            ),
            "trend_stockout_days": ("Observed stockout days across both trend windows; not necessarily consecutive"),
        },
        "interpretation": (
            "Use classification_groups and per-product labels as authoritative. Negative observed growth for "
            "stockout_affected items is NOT a confirmed declining classification. Slow-moving and overstock "
            "are distinct flags. Stock is historical at the cutoff, not necessarily current live stock."
        ),
    }
