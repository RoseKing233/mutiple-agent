"""Manager-only tools. Identity is always derived from authenticated ContextVars."""

from datetime import UTC, date, datetime, timedelta
from typing import Annotated
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from agent_framework import tool
from pydantic import Field

from shared.context import current_agent_request_id, current_user_email, current_user_role
from shared.db import get_pool
from shared.forecasting.config import ForecastRequest
from shared.forecasting.service import performance_report
from shared.forecasting.store import get_report, list_reports, save_report
from shared.sales_analysis import AnalysisWindow, historical_analysis


def denied() -> dict | None:
    if not current_user_email.get() or current_user_role.get() != "store_manager":
        return {"error": "permission_denied", "message": "Store manager access required"}
    return None


def specification(as_of: str, horizon: int, product_id: str, category: str) -> ForecastRequest:
    return ForecastRequest(
        **({"as_of": as_of} if as_of else {}), horizon=horizon, product_id=product_id or None, category=category or None
    )


def compact_report(report: dict, *, operation: str = "read_saved_report") -> dict:
    """Keep multi-product tool responses bounded; full curves live in the saved dashboard."""
    products = []
    for p in report["products"]:
        f = p["forecast"]
        series = f.get("series", [])
        products.append(
            {
                "product_id": p["product_id"],
                "name": p["name"],
                "performance": p["performance"],
                "forecast": {k: v for k, v in f.items() if k not in {"series", "backtest"}},
                "forecast_units": round(sum(r["units"] for r in series), 2) if f["available"] else None,
                "starting_stock_at_cutoff": p["performance"]["stock_at_cutoff"],
                "projected_ending_stock": series[-1]["stock"] if series else None,
                "forecast_start": series[0]["date"] if series else None,
                "forecast_end": series[-1]["date"] if series else None,
                "model_selection": (
                    "Recent-mean fallback because fewer than two backtest folds are available"
                    if len(f.get("backtest", {}).get("folds", [])) < 2
                    else "Selected by rolling-origin backtesting: lowest daily MAE, then horizon-total MAE"
                )
                if f["available"]
                else None,
                "selected_model_backtest": next(
                    (s for s in f.get("backtest", {}).get("scores", []) if s["model"] == f.get("model")), None
                ),
            }
        )
    return {k: v for k, v in report.items() if k not in {"products", "series"}} | {
        "products": products,
        "dashboard_url": f"/analysis?run_id={report['id']}",
        "operation": operation,
        "sales_definition": "Non-cancelled order units, including pending/unfulfilled and returned orders",
        "stock_definition": "Starting stock is historical EOD at the cutoff; it is not current live inventory",
    }


@tool(
    name="get_sales_history",
    description="Manager only: historical sales and end-of-day inventory for a product/category.",
)
async def get_sales_history(
    start_date: Annotated[str, Field(description="Inclusive UTC YYYY-MM-DD; default last 28 days")] = "",
    end_date: Annotated[str, Field(description="Inclusive UTC YYYY-MM-DD; default yesterday")] = "",
    product_id: Annotated[str, Field(description="Product UUID, empty for all selected products")] = "",
    category: Annotated[str, Field(description="Exact category, empty for all")] = "",
) -> dict:
    if error := denied():
        return error
    try:
        end = date.fromisoformat(end_date) if end_date else datetime.now(UTC).date() - timedelta(days=1)
        window = AnalysisWindow(date.fromisoformat(start_date) if start_date else end - timedelta(days=27), end)
        async with get_pool().acquire() as conn:
            async with conn.transaction(isolation="repeatable_read", readonly=True):
                result = await historical_analysis(
                    conn, window, category or None, UUID(product_id) if product_id else None
                )
                return {k: v for k, v in result.items() if k not in {"products", "warehouses"}}
    except (ValueError, LookupError) as exc:
        return {"error": "invalid_analysis_request", "message": str(exc)}


@tool(
    name="analyze_product_performance",
    description="Manager only: evidence for growing, declining, slow-moving and overstock flags.",
)
async def analyze_product_performance(
    as_of: Annotated[str, Field(description="Complete UTC YYYY-MM-DD, default yesterday")] = "",
    product_id: Annotated[str, Field(description="Product UUID, empty for all")] = "",
    category: Annotated[str, Field(description="Exact category, empty for all")] = "",
) -> dict:
    if error := denied():
        return error
    try:
        spec = specification(as_of, 14, product_id, category)
        async with get_pool().acquire() as conn:
            async with conn.transaction(isolation="repeatable_read", readonly=True):
                return await performance_report(conn, spec)
    except (ValueError, LookupError) as exc:
        return {"error": "invalid_analysis_request", "message": str(exc)}


@tool(
    name="forecast_sales_inventory",
    description="Manager only: calculate AND save sales/stock forecasts and stockout risks. Never changes stock.",
)
async def forecast_sales_inventory(
    horizon: Annotated[int, Field(description="Forecast days: 7, 14 or 28")] = 14,
    as_of: Annotated[str, Field(description="Complete UTC YYYY-MM-DD, default yesterday")] = "",
    product_id: Annotated[str, Field(description="Product UUID, empty for all")] = "",
    category: Annotated[str, Field(description="Exact category, empty for all")] = "",
    request_id: Annotated[str, Field(description="Optional UUID to deduplicate retries of the same request")] = "",
) -> dict:
    if error := denied():
        return error
    try:
        spec = specification(as_of, horizon, product_id, category)
        # A stream can fail after committing a report. Its blocking retry must
        # reuse the same owner/request key, even if the model invents a new UUID.
        # Include parameters so one invocation can still forecast multiple scopes.
        invocation = current_agent_request_id.get()
        save_id = (
            uuid5(NAMESPACE_URL, f"sales-forecast:{invocation}:{spec.model_dump_json()}")
            if invocation
            else UUID(request_id)
            if request_id
            else uuid4()
        )
        result = await save_report(
            get_pool(),
            current_user_email.get(),
            spec,
            save_id,
        )
        return compact_report(result, operation="computed_and_saved_report")
    except (ValueError, LookupError, PermissionError) as exc:
        return {"error": "invalid_analysis_request", "message": str(exc)}


@tool(
    name="list_saved_sales_analyses",
    description="Manager only: list your own saved forecast/analysis snapshots, newest first.",
)
async def list_saved_sales_analyses(
    offset: Annotated[int, Field(description="Pagination offset, >=0")] = 0,
) -> dict:
    if error := denied():
        return error
    if offset < 0:
        return {"error": "invalid_analysis_request", "message": "Offset must be nonnegative"}
    async with get_pool().acquire() as conn:
        return await list_reports(conn, current_user_email.get(), offset=offset)


@tool(
    name="get_saved_sales_analysis",
    description="Manager only: read your own saved immutable sales forecast by run UUID.",
)
async def get_saved_sales_analysis(
    run_id: Annotated[str, Field(description="Saved analysis run UUID")],
) -> dict:
    if error := denied():
        return error
    try:
        async with get_pool().acquire() as conn:
            return compact_report(await get_report(conn, current_user_email.get(), UUID(run_id)))
    except (ValueError, LookupError) as exc:
        return {"error": "analysis_not_found", "message": str(exc)}


SALES_ANALYSIS_TOOLS = [
    get_sales_history,
    analyze_product_performance,
    forecast_sales_inventory,
    list_saved_sales_analyses,
    get_saved_sales_analysis,
]
