"""Numerical, temporal, permission and persistence contracts; no LLM calls."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from shared.forecasting.config import ForecastRequest, PerformanceRules
from shared.forecasting.data import ProductHistory, load_histories
from shared.forecasting.models import fit_forecast, predict, prepare
from shared.forecasting.performance import assess
from shared.forecasting.service import calculate, performance_guidance, stock_projection
from shared.forecasting.store import save_report
from shared.jwt_utils import create_access_token
from shared.manager_accounts import MANAGER_EMAIL, ensure_manager


def history(values: list[int], stock: int = 200) -> ProductHistory:
    end = datetime.now(UTC).date() - timedelta(days=1)
    days = [end - timedelta(days=len(values) - i - 1) for i in range(len(values))]
    return ProductHistory(
        str(uuid.uuid4()),
        "Example",
        "Books",
        days,
        [(d, q, None) for d, q in zip(days, values, strict=True) if q],
        [stock] * len(days),
        [False] * len(days),
    )


def test_thresholds_zero_baseline_and_independent_flags() -> None:
    rules = PerformanceRules()
    growing = assess(history([1] * 28 + [2] * 28), rules)
    assert growing["trend"] == "growing" and growing["overstock"] is True
    assert assess(history([2] * 28 + [1] * 28), rules)["trend"] == "declining"
    assert assess(history([0] * 28 + [1] * 28), rules)["trend"] == "new_sales"
    zero = assess(history([0] * 56), rules)
    assert zero["slow_moving"] and zero["no_recent_sales"]
    assert zero["days_of_cover"] is None and zero["overstock"] is False
    assert zero["consecutive_zero_sales_days"] == zero["consecutive_zero_days"] == 56
    assert zero["recent_stockout_days"] == 0  # No sales does not imply a stockout.
    # A large percentage from a tiny base does not satisfy the minimum-unit rule.
    assert assess(history([0] * 27 + [1] + [0] * 27 + [2]), rules)["trend"] == "stable"
    assert assess(history([1] * 56, 60), rules)["overstock"] is False
    assert assess(history([1] * 56, 61), rules)["overstock"] is True


def test_unknown_stock_new_products_and_stockout_flags() -> None:
    young = assess(history([0] * 6), PerformanceRules())
    assert young["slow_moving"] is None and young["trend"] == "insufficient_history"
    h = history([2] * 28 + [0] * 28)
    h.constrained[-4] = True
    assert assess(h, PerformanceRules())["recent_stockout_days"] == 1
    assert assess(h, PerformanceRules())["consecutive_zero_sales_days"] == 28
    assert assess(h, PerformanceRules())["trend"] == "stockout_affected"
    assert assess(h, PerformanceRules())["slow_moving"] is None
    h.constrained[-4] = False
    h.stock[-4] = None
    assert assess(h, PerformanceRules())["trend"] == "unknown_stock_history"
    assert assess(h, PerformanceRules())["overstock"] is None


def test_narration_guidance_uses_exact_flags_and_difference_threshold() -> None:
    normal, constrained = history([2] * 28 + [1] * 28), history([2] * 28 + [1] * 28)
    constrained.constrained[-1] = True
    products = [{"name": h.name + str(i), **assess(h, PerformanceRules())} for i, h in enumerate([normal, constrained])]
    result = performance_guidance(products, PerformanceRules(trend_min_units=9))
    assert result["classification_groups"]["declining"] == ["Example0"]
    assert result["classification_groups"]["stockout_affected"] == ["Example1"]
    assert result["classification_groups"]["slow_moving"] == []
    assert "previous_units - recent_units >= 9" in result["rule_descriptions"]["declining"]
    assert "days_of_cover > 60" in result["rule_descriptions"]["overstock"]
    assert "not days out of stock" in result["field_definitions"]["consecutive_zero_sales_days"]


def test_baselines_weekly_hw_and_tsb_decay() -> None:
    assert predict([3.0] * 80, 14, "mean_28") == [3.0] * 14
    weekly = [1.0, 2.0, 3.0, 4.0, 5.0, 8.0, 9.0]
    for model in ["seasonal_naive_7", "holt_winters_0.2_0.9", "holt_winters_0.5_1.0"]:
        assert predict(weekly * 12, 14, model) == pytest.approx(weekly * 2)
    assert predict([0.0] * 50, 7, "tsb_0.1") == [0.0] * 7
    assert predict([10.0] + [0.0] * 30, 7, "tsb_0.1")[0] < predict([10.0] + [0.0] * 5, 7, "tsb_0.1")[0]
    assert min(predict([20.0 - i / 10 for i in range(180)], 28, "holt_winters_0.5_1.0")) >= 0


def test_causal_imputation_and_long_stockout_abstention() -> None:
    values = [2.0] * 21 + [0.0, 100.0]
    constrained = [False] * 21 + [True, False]
    filled, count = prepare(values, constrained)
    assert count == 1 and filled[21] == 2  # Future 100 does not leak into imputation.
    h = history([2] * 70 + [0] * 14)
    h.constrained[-14:] = [True] * 14
    assert fit_forecast(h, 14)["available"] is False
    h = history([2] * 10)
    assert fit_forecast(h, 14)["model"] == "mean_28"
    assert fit_forecast(h, 14)["reliability"] == "low"
    old_stockout = history([2] * 84)
    old_stockout.constrained[20:25] = [True] * 5
    assert fit_forecast(old_stockout, 14)["reliability"] == "low"
    assert any("understate demand" in w for w in fit_forecast(old_stockout, 14)["warnings"])


def test_backtest_has_no_future_status_leakage_and_selects_weekly() -> None:
    h = history([1, 1, 1, 1, 1, 8, 8] * 20)
    fitted = fit_forecast(h, 14)
    assert fitted["model"] in {
        "seasonal_naive_7",
        "holt_winters_0.2_0.9",
        "holt_winters_0.2_1.0",
        "holt_winters_0.5_0.9",
        "holt_winters_0.5_1.0",
    }
    assert fitted["backtest"]["scores"][0]["mae"] == pytest.approx(0)
    assert len(fitted["backtest"]["folds"]) == 3
    cutoff = h.days[70]
    h.orders.append((h.days[60], 100, h.days[80]))
    assert sum(h.sales_at(cutoff)) - sum(history([1, 1, 1, 1, 1, 8, 8] * 20).sales_at(cutoff)) == 100
    assert sum(h.sales_at(h.days[-1])) == sum([1, 1, 1, 1, 1, 8, 8] * 20)


def test_stock_projection_boundary_and_no_pooling_across_products() -> None:
    cutoff = date(2026, 1, 1)
    result = stock_projection(5, [2.0, 3.0, 4.0], cutoff)
    assert result["stockout_date"] == "2026-01-03"
    assert [r["stock"] for r in result["series"]] == [3, 0, 0]
    assert result["unmet_units"] == 4
    assert stock_projection(0, [1.0], cutoff)["stockout_status"] == "already_out_of_stock"
    assert stock_projection(None, [1.0], cutoff)["stockout_status"] == "unknown_stock"
    assert stock_projection(100, [1.0], cutoff)["stockout_date"] is None
    a, b = history([2] * 84, 1), history([2] * 84, 100)
    report = calculate([a, b], ForecastRequest(horizon=7))
    assert report["series"][0]["stock"] == 98  # Spare stock of B cannot satisfy A's demand.
    assert report["series"][0]["units"] == 4
    partial = calculate([a, history([1] * 3)], ForecastRequest(horizon=7))
    assert partial["series"][0]["units"] is None
    assert partial["series"][0]["available_product_units"] == 2
    unavailable = calculate([history([1] * 3)], ForecastRequest(horizon=7))
    assert unavailable["series"][0]["available_product_units"] is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"horizon": 30},
        {"as_of": datetime.now(UTC).date()},
        {"rules": {"trend_percent": float("nan")}},
        {"surprise": True},
    ],
)
def test_invalid_specifications(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        ForecastRequest(**kwargs)


async def test_inventory_prompt_role_is_request_scoped_without_llm() -> None:
    from agent_framework import SessionContext

    from inventory_fulfillment.context import InventoryRoleProvider
    from inventory_fulfillment.prompts import get_system_prompt
    from shared.context import current_user_role

    provider = InventoryRoleProvider()  # Same provider reused across requests, as in the A2A host.
    assert "This user is a customer" not in get_system_prompt(None)
    role = current_user_role.set("store_manager")
    try:
        manager = SessionContext(input_messages=[])
        await provider.before_run(agent=None, session=None, context=manager, state={})
        assert "forecast_sales_inventory" in " ".join(manager.instructions)
        current_user_role.set("customer")
        customer = SessionContext(input_messages=[])
        await provider.before_run(agent=None, session=None, context=customer, state={})
        assert "forecast_sales_inventory" not in " ".join(customer.instructions)
        assert "customer" in " ".join(customer.instructions)
    finally:
        current_user_role.reset(role)


@pytest_asyncio.fixture
async def forecast_db(clean_db, monkeypatch):
    import shared.db as db

    monkeypatch.setattr(db, "_pool", clean_db)
    start = (datetime.now(UTC) - timedelta(days=120)).replace(hour=0, minute=0, second=0, microsecond=0)
    pid, wh = uuid.uuid4(), uuid.uuid4()
    async with clean_db.acquire() as conn:
        manager = await ensure_manager(conn)
        other = await ensure_manager(conn, "second-manager@example.test")
        await conn.execute(
            """INSERT INTO products(id,name,description,category,price,created_at)
            VALUES($1,'Forecast book','Demo','Books',10,$2)""",
            pid,
            start,
        )
        await conn.execute("INSERT INTO warehouses(id,name,location,region) VALUES($1,'East','Demo','east')", wh)
        await conn.execute(
            "INSERT INTO warehouse_inventory(product_id,warehouse_id,quantity) VALUES($1,$2,760)", pid, wh
        )
        await conn.execute(
            """INSERT INTO inventory_movements
            (event_key,product_id,warehouse_id,movement_type,quantity_delta,balance_after,occurred_at)
            VALUES('opening',$1,$2,'opening',1000,1000,$3)""",
            pid,
            wh,
            start,
        )
        for i in range(120):
            oid, moment = uuid.uuid4(), start + timedelta(days=i, hours=12)
            await conn.execute(
                """INSERT INTO orders(id,user_id,status,total,shipping_address,created_at)
                VALUES($1,$2,'delivered',20,'{}',$3)""",
                oid,
                manager,
                moment,
            )
            await conn.execute(
                "INSERT INTO order_items(order_id,product_id,quantity,unit_price,subtotal) VALUES($1,$2,2,10,20)",
                oid,
                pid,
            )
            await conn.execute(
                "INSERT INTO order_status_history(order_id,status,timestamp) VALUES($1,'placed',$2)", oid, moment
            )
            await conn.execute(
                """INSERT INTO inventory_movements
                (event_key,product_id,warehouse_id,movement_type,quantity_delta,balance_after,occurred_at,order_id)
                VALUES($1,$2,$3,'sale',-2,$4,$5,$6)""",
                str(oid),
                pid,
                wh,
                1000 - 2 * (i + 1),
                moment,
                oid,
            )
    from orchestrator.routes.manager import router

    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield {
            "pool": clean_db,
            "client": client,
            "pid": pid,
            "wh": wh,
            "start": start,
            "manager": manager,
            "headers": {"Authorization": f"Bearer {create_access_token(MANAGER_EMAIL, 'store_manager', str(manager))}"},
            "other_headers": {
                "Authorization": "Bearer "
                + create_access_token("second-manager@example.test", "store_manager", str(other))
            },
        }


async def test_real_database_asof_stock_and_cancellation(forecast_db) -> None:
    d = forecast_db
    spec = ForecastRequest(as_of=(d["start"] + timedelta(days=60)).date(), product_id=d["pid"])
    async with d["pool"].acquire() as conn:
        oid = uuid.uuid4()
        await conn.execute(
            """INSERT INTO orders(id,user_id,status,total,shipping_address,created_at)
            VALUES($1,$2,'cancelled',500,'{}',$3)""",
            oid,
            d["manager"],
            d["start"] + timedelta(days=10),
        )
        await conn.execute(
            "INSERT INTO order_items(order_id,product_id,quantity,unit_price,subtotal) VALUES($1,$2,50,10,500)",
            oid,
            d["pid"],
        )
        await conn.execute(
            "INSERT INTO order_status_history(order_id,status,timestamp) VALUES($1,'placed',$2),($1,'cancelled',$3)",
            oid,
            d["start"] + timedelta(days=10),
            d["start"] + timedelta(days=80),
        )
        loaded = await load_histories(conn, spec)
        assert loaded[0].stock[-1] == 878  # EOD cutoff, not live 760.
        assert sum(loaded[0].sales_at(spec.as_of)) == 172  # Future cancellation not used.
        later = await load_histories(conn, ForecastRequest(product_id=d["pid"]))
        assert sum(later[0].sales_at(later[0].days[-1])) == 240


async def test_save_api_immutable_owner_scoped_idempotent_and_no_stock_change(forecast_db) -> None:
    d, request_id = forecast_db, uuid.uuid4()
    body = {"product_id": str(d["pid"]), "horizon": 14, "request_id": str(request_id)}
    responses = await asyncio.gather(
        *[d["client"].post("/api/manager/analysis-runs", json=body, headers=d["headers"]) for _ in range(2)]
    )
    assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
    result = responses[0].json()
    assert result == responses[1].json()
    assert result["products"][0]["forecast"]["series"][0]["units"] == 2
    assert (
        await d["client"].get(f"/api/manager/analysis-runs/{result['id']}", headers=d["other_headers"])
    ).status_code == 404
    assert (await d["client"].get("/api/manager/analysis-runs", headers=d["other_headers"])).json()["total"] == 0
    assert (
        await d["client"].post("/api/manager/analysis-runs", json=body | {"horizon": 7}, headers=d["headers"])
    ).status_code == 409
    async with d["pool"].acquire() as conn:
        assert await conn.fetchval("SELECT quantity FROM warehouse_inventory WHERE product_id=$1", d["pid"]) == 760
        assert await conn.fetchval("SELECT COUNT(*) FROM inventory_movements") == 121
        await conn.execute("UPDATE order_items SET quantity=3,subtotal=30")
    stored = (await d["client"].get(f"/api/manager/analysis-runs/{result['id']}", headers=d["headers"])).json()
    assert stored == result  # Reads do not silently recalculate.
    assert (await d["client"].get("/api/manager/analysis-runs?offset=1", headers=d["headers"])).json()["runs"] == []


async def test_tool_api_equivalence_registration_and_permission_guards(forecast_db, monkeypatch) -> None:
    from inventory_fulfillment.agent import AGENT_TOOLS
    from shared.config import settings
    from shared.context import current_user_email, current_user_role
    from shared.tools.sales_analysis_tools import (
        SALES_ANALYSIS_TOOLS,
        analyze_product_performance,
        forecast_sales_inventory,
        get_sales_history,
        get_saved_sales_analysis,
    )

    d = forecast_db
    assert all(t in AGENT_TOOLS for t in SALES_ANALYSIS_TOOLS)
    monkeypatch.setattr(settings, "GUARDRAILS_ENABLED", False)
    role, email = current_user_role.set("customer"), current_user_email.set(MANAGER_EMAIL)
    try:
        assert (await forecast_sales_inventory())["error"] == "permission_denied"
        assert (await get_sales_history())["error"] == "permission_denied"
        assert (await get_saved_sales_analysis(run_id=str(uuid.uuid4())))["error"] == "permission_denied"
        current_user_role.set("store_manager")
        direct = await analyze_product_performance(product_id=str(d["pid"]))
        http = (await d["client"].get(f"/api/manager/performance?product_id={d['pid']}", headers=d["headers"])).json()
        assert direct == http
        assert (await forecast_sales_inventory(horizon=1))["error"] == "invalid_analysis_request"
        saved = await forecast_sales_inventory(product_id=str(d["pid"]))
        assert saved["products"][0]["forecast_units"] == 28
        assert "series" not in saved["products"][0]["forecast"]
        assert saved["operation"] == "computed_and_saved_report"
        retrieved = await get_saved_sales_analysis(run_id=saved["id"])
        assert retrieved["operation"] == "read_saved_report"
        assert retrieved | {"operation": saved["operation"]} == saved
        product = saved["products"][0]
        assert product["starting_stock_at_cutoff"] == 760
        assert product["projected_ending_stock"] == 732
        assert product["forecast_start"] and product["forecast_end"]
        assert "rolling-origin" in product["model_selection"]
        assert "pending/unfulfilled and returned" in saved["sales_definition"]
        assert saved["dashboard_url"] == f"/analysis?run_id={saved['id']}"
    finally:
        current_user_role.reset(role)
        current_user_email.reset(email)
    customer = {"Authorization": f"Bearer {create_access_token(MANAGER_EMAIL, 'customer', str(d['manager']))}"}
    for path in ["/api/manager/performance", "/api/manager/analysis-runs"]:
        assert (await d["client"].get(path)).status_code == 401
        assert (await d["client"].get(path, headers=customer)).status_code == 403
    assert (await d["client"].post("/api/manager/analysis-runs", json={}, headers=customer)).status_code == 403
    assert (
        await d["client"].post("/api/manager/analysis-runs", json={"horizon": 30}, headers=d["headers"])
    ).status_code == 422
    assert (await d["client"].get("/api/manager/performance?as_of=bad", headers=d["headers"])).status_code == 422


async def test_a2a_retry_deduplicates_forecast_save_even_with_new_model_request_ids(forecast_db) -> None:
    from shared.context import current_agent_request_id, current_user_email, current_user_role
    from shared.tools.sales_analysis_tools import forecast_sales_inventory

    invocation = str(uuid.uuid4())
    role = current_user_role.set("store_manager")
    email = current_user_email.set(MANAGER_EMAIL)
    request = current_agent_request_id.set(invocation)
    try:
        args = {"product_id": str(forecast_db["pid"]), "horizon": 7}
        first, retry = await asyncio.gather(
            forecast_sales_inventory(**args, request_id=str(uuid.uuid4())),
            forecast_sales_inventory(**args, request_id=str(uuid.uuid4())),
        )
        assert first == retry
        other_scope = await forecast_sales_inventory(product_id=args["product_id"], horizon=14)
        assert other_scope["id"] != first["id"]
        current_agent_request_id.set(str(uuid.uuid4()))
        next_invocation = await forecast_sales_inventory(**args)
        assert next_invocation["id"] != first["id"]
        async with forecast_db["pool"].acquire() as conn:
            assert await conn.fetchval("SELECT COUNT(*) FROM sales_analysis_runs") == 3
            assert await conn.fetchval("SELECT COUNT(*) FROM inventory_movements") == 121
    finally:
        current_agent_request_id.reset(request)
        current_user_email.reset(email)
        current_user_role.reset(role)


async def test_migration_idempotent_and_unknown_history_preserved(forecast_db) -> None:
    from shared.db_migrations import apply_migrations

    d = forecast_db
    report = await save_report(d["pool"], MANAGER_EMAIL, ForecastRequest(product_id=d["pid"]), uuid.uuid4())
    async with d["pool"].acquire() as conn:
        await apply_migrations(conn)
        await apply_migrations(conn)
        assert await conn.fetchval("SELECT COUNT(*) FROM sales_analysis_runs WHERE id=$1", uuid.UUID(report["id"])) == 1
        await conn.execute("DELETE FROM order_status_history")
    response = await d["client"].post(
        "/api/manager/analysis-runs", json={"product_id": str(d["pid"])}, headers=d["headers"]
    )
    assert response.status_code == 200
    assert response.json()["products"][0]["forecast"]["available"] is False
