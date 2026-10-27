"""Manager permissions and sales/inventory aggregation against real PostgreSQL."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from shared.inventory_ledger import change_inventory
from shared.jwt_utils import create_access_token, hash_password
from shared.manager_accounts import MANAGER_EMAIL, ensure_manager


@pytest_asyncio.fixture
async def manager_data(clean_db, monkeypatch):
    import shared.db as db

    monkeypatch.setattr(db, "_pool", clean_db)
    start = (datetime.now(UTC) - timedelta(days=5)).replace(hour=0, minute=0, second=0, microsecond=0)
    async with clean_db.acquire() as conn:
        manager = await ensure_manager(conn)
        customer = uuid.uuid4()
        await conn.execute(
            """INSERT INTO users(id,email,password_hash,name,role)
            VALUES($1,'customer@test.example',$2,'Customer','customer')""",
            customer,
            hash_password("password123"),
        )
        p1, p2, w1, w2 = [uuid.uuid4() for _ in range(4)]
        for pid, name in [(p1, "Alpha"), (p2, "Beta")]:
            await conn.execute(
                """INSERT INTO products(id,name,description,category,price,created_at)
                VALUES($1,$2,'Demo','Books',10,$3)""",
                pid,
                name,
                start - timedelta(days=2),
            )
        for wh, name in [(w1, "East"), (w2, "West")]:
            await conn.execute("INSERT INTO warehouses(id,name,location,region) VALUES($1,$2,'Demo','east')", wh, name)
        for pid, wh, qty, moment in [
            (p1, w1, 10, start - timedelta(days=1)),
            (p1, w2, 20, start - timedelta(days=1)),
            (p2, w1, 5, start + timedelta(days=2)),
        ]:
            await conn.execute(
                "INSERT INTO warehouse_inventory(product_id,warehouse_id,quantity) VALUES($1,$2,$3)", pid, wh, qty
            )
            await conn.execute(
                """INSERT INTO inventory_movements
                (event_key,product_id,warehouse_id,movement_type,quantity_delta,balance_after,occurred_at)
                VALUES($1,$2,$3,'opening',$4,$4,$5)""",
                f"opening:{pid}:{wh}",
                pid,
                wh,
                qty,
                moment,
            )
        first, cancelled, returned = [uuid.uuid4() for _ in range(3)]
        for oid, status, total, moment in [
            (first, "delivered", 50, start + timedelta(hours=10)),
            (cancelled, "cancelled", 40, start + timedelta(hours=11)),
            (returned, "returned", 10, start + timedelta(days=1, hours=10)),
        ]:
            await conn.execute(
                """INSERT INTO orders(id,user_id,status,total,shipping_address,created_at)
                VALUES($1,$2,$3,$4,'{}',$5)""",
                oid,
                customer,
                status,
                total,
                moment,
            )
        for oid, pid, qty in [(first, p1, 2), (first, p2, 3), (cancelled, p1, 4), (returned, p1, 1)]:
            await conn.execute(
                """INSERT INTO order_items(order_id,product_id,quantity,unit_price,subtotal)
                VALUES($1,$2,$3,10,$4)""",
                oid,
                pid,
                qty,
                qty * 10,
            )
        async with conn.transaction():
            await change_inventory(
                conn,
                product_id=p1,
                warehouse_id=w1,
                quantity_delta=-2,
                movement_type="sale",
                event_key="first",
                order_id=first,
                occurred_at=start + timedelta(hours=10),
            )
            await change_inventory(
                conn,
                product_id=p1,
                warehouse_id=w1,
                quantity_delta=-1,
                movement_type="sale",
                event_key="returned-sale",
                order_id=returned,
                occurred_at=start + timedelta(days=1, hours=10),
            )
    from orchestrator.routes import router

    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield {
            "http": http,
            "pool": clean_db,
            "manager": manager,
            "customer": customer,
            "p1": p1,
            "p2": p2,
            "start": start,
            "query": f"start_date={start.date()}&end_date={(start + timedelta(days=3)).date()}",
        }


def auth(data, role="store_manager"):
    email = MANAGER_EMAIL if role == "store_manager" else "customer@test.example"
    uid = data["manager"] if role == "store_manager" else data["customer"]
    return {"Authorization": f"Bearer {create_access_token(email, role, str(uid))}"}


async def test_manager_login_and_customer_cannot_access_management(manager_data):
    d = manager_data
    response = await d["http"].post("/api/auth/login", json={"email": MANAGER_EMAIL, "password": "manager123"})
    assert response.status_code == 200 and response.json()["user"]["role"] == "store_manager"
    for path in [
        "/api/manager/catalog",
        "/api/manager/products",
        "/api/manager/analysis",
        f"/api/manager/products/{d['p1']}/orders",
    ]:
        assert (await d["http"].get(path)).status_code == 401
        assert (await d["http"].get(path, headers=auth(d, "customer"))).status_code == 403
    assert (await d["http"].get("/api/admin/usage", headers=auth(d))).status_code == 403


async def test_aggregation_counts_orders_once_and_carries_each_warehouse(manager_data):
    d = manager_data
    response = await d["http"].get(f"/api/manager/analysis?{d['query']}", headers=auth(d))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["summary"]["units"] == 6
    assert result["summary"]["order_count"] == 2
    assert result["summary"]["item_amount"] == 60
    assert result["summary"]["cancelled_units"] == 4
    assert result["summary"]["returned_order_units"] == 1
    assert [r["closing_stock"] for r in result["series"]] == [None, None, 32, 32]
    assert [r["units"] for r in result["series"]] == [5, 1, 0, 0]
    single = await d["http"].get(f"/api/manager/analysis?{d['query']}&product_id={d['p1']}", headers=auth(d))
    assert [r["closing_stock"] for r in single.json()["series"]] == [28, 27, 27, 27]
    assert result["forecast"]["available"] is True
    assert result["forecast"]["endpoint"] == "/api/manager/analysis-runs"


async def test_products_orders_filters_and_invalid_ranges(manager_data):
    d = manager_data
    headers = auth(d)
    result = (await d["http"].get(f"/api/manager/products?{d['query']}&search=Alpha&limit=1", headers=headers)).json()
    assert result["total"] == 1 and result["products"][0]["units"] == 3
    orders = (
        await d["http"].get(f"/api/manager/products/{d['p1']}/orders?{d['query']}&limit=1", headers=headers)
    ).json()
    assert orders["total"] == 3 and len(orders["orders"]) == 1
    assert "shipping_address" not in orders["orders"][0] and "user_id" not in orders["orders"][0]
    for query in ["start_date=2026-10-01&end_date=2026-01-01", "start_date=2020-01-01", "product_id=invalid"]:
        assert (await d["http"].get(f"/api/manager/analysis?{query}", headers=headers)).status_code == 422
    assert (
        await d["http"].get(f"/api/manager/analysis?{d['query']}&product_id={uuid.uuid4()}", headers=headers)
    ).status_code == 404
    empty = (await d["http"].get(f"/api/manager/analysis?{d['query']}&category=Missing", headers=headers)).json()
    assert empty["summary"]["product_count"] == 0 and all(r["units"] is None for r in empty["series"])


async def test_manager_cannot_shop_and_setup_cannot_promote_customers(manager_data):
    d = manager_data
    assert (await d["http"].get("/api/cart", headers=auth(d))).status_code == 403
    assert (
        await d["http"].post("/api/cart/items", headers=auth(d), json={"product_id": str(d["p1"]), "quantity": 1})
    ).status_code == 403
    async with d["pool"].acquire() as conn:
        with pytest.raises(ValueError, match="different role"):
            await ensure_manager(conn, "customer@test.example")
        assert await ensure_manager(conn) == d["manager"]


async def test_unknown_history_stays_unknown_before_recorded_coverage(manager_data):
    d = manager_data
    start = (d["start"] - timedelta(days=4)).date()
    end = (d["start"] - timedelta(days=3)).date()
    result = (
        await d["http"].get(
            f"/api/manager/analysis?start_date={start}&end_date={end}&product_id={d['p1']}",
            headers=auth(d),
        )
    ).json()
    assert all(row["units"] is None and row["closing_stock"] is None for row in result["series"])
    assert result["summary"]["current_stock"] == 27
    from shared.sales_analysis import scope_products

    async with d["pool"].acquire() as conn:
        await conn.execute("SET TIME ZONE 'America/Los_Angeles'")
        rows = await scope_products(conn, product_id=d["p1"])
        assert rows[0]["known_launch"] == (d["start"] - timedelta(days=2)).date()


async def test_signup_cannot_self_assign_manager_role(manager_data):
    response = await manager_data["http"].post(
        "/api/auth/signup",
        json={
            "email": "new-customer@test.example",
            "password": "password123",
            "name": "Customer",
            "role": "store_manager",
        },
    )
    assert response.status_code == 200
    assert response.json()["user"]["role"] == "customer"


async def test_manager_identity_and_cart_tool_guard(monkeypatch):
    from shared.auth import _identity_anomaly
    from shared.config import settings
    from shared.context import current_user_role
    from shared.tools.cart_tools import add_to_cart, get_cart

    assert _identity_anomaly(MANAGER_EMAIL, "store_manager") is None
    monkeypatch.setattr(settings, "GUARDRAILS_ENABLED", False)
    token = current_user_role.set("store_manager")
    try:
        assert (await add_to_cart(product_id=str(uuid.uuid4())))["error"] == "permission_denied"
        assert (await get_cart())["error"] == "permission_denied"
    finally:
        current_user_role.reset(token)
