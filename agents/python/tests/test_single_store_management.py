"""Real PostgreSQL coverage for role migration and whole-store manager access."""

from __future__ import annotations

import uuid

import asyncpg
import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

import shared.db as db
from orchestrator.routes import inventory, legacy, manager, marketing
from shared.config import settings
from shared.context import current_user_email, current_user_role
from shared.db_migrations import apply_migrations
from shared.jwt_utils import create_access_token
from shared.tools.store_tools import get_store_inventory, get_store_orders, get_store_products, get_store_stats

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def store(clean_db: asyncpg.Pool, monkeypatch: pytest.MonkeyPatch) -> dict:
    monkeypatch.setattr(db, "_pool", clean_db)
    monkeypatch.setattr(settings, "AUTH_MODE", "local")
    users = {}
    async with clean_db.acquire() as conn:
        await apply_migrations(conn)
        for name, role in [
            ("manager1", "store_manager"),
            ("manager2", "store_manager"),
            ("buyer", "customer"),
            ("admin", "admin"),
        ]:
            users[name] = await conn.fetchval(
                "INSERT INTO users(email,name,password_hash,role) VALUES($1,$1,'hash',$2) RETURNING id",
                f"{name}@test.example",
                role,
            )
        warehouse = await conn.fetchval(
            "INSERT INTO warehouses(name,location,region) VALUES('Central','Sydney','east') RETURNING id"
        )
        products = []
        for i, owner in enumerate([users["manager1"], users["manager2"], None]):
            pid = await conn.fetchval(
                """INSERT INTO products(name,description,category,price,seller_id,is_active)
                   VALUES($1,'Description','Books',10,$2,$3) RETURNING id""",
                f"Product {i}",
                owner,
                i != 1,
            )
            products.append(pid)
            await conn.execute(
                "INSERT INTO warehouse_inventory(product_id,warehouse_id,quantity) VALUES($1,$2,10)", pid, warehouse
            )
        for status in ["placed", "cancelled"]:
            oid = await conn.fetchval(
                "INSERT INTO orders(user_id,status,total,shipping_address) VALUES($1,$2,30,'{}') RETURNING id",
                users["buyer"],
                status,
            )
            for pid in products:
                await conn.execute(
                    "INSERT INTO order_items(order_id,product_id,quantity,unit_price,subtotal) VALUES($1,$2,1,10,10)",
                    oid,
                    pid,
                )
    return {"pool": clean_db, "users": users, "products": products, "warehouse": warehouse}


def headers(data: dict, name: str = "manager1", role: str = "store_manager") -> dict[str, str]:
    return {"Authorization": "Bearer " + create_access_token(f"{name}@test.example", role, str(data["users"][name]))}


def app() -> FastAPI:
    instance = FastAPI()
    instance.include_router(legacy.router)
    instance.include_router(inventory.router)
    instance.include_router(manager.router)
    instance.include_router(marketing.router)
    return instance


async def test_manager_reads_all_legacy_owners_unowned_products_and_multi_item_orders(store: dict) -> None:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app()), base_url="http://test") as client:
        for name in ["manager1", "manager2"]:
            auth = headers(store, name)
            for path in ["/api/manager/store/products", "/api/seller/products"]:
                response = await client.get(path, headers=auth)
                assert response.status_code == 200
                assert response.json()["total"] == 3
                assert {row["id"] for row in response.json()["products"]} == {str(pid) for pid in store["products"]}
            orders = (await client.get("/api/manager/orders", headers=auth)).json()
            assert orders["total"] == 2
            assert all(row["item_count"] == 3 for row in orders["orders"])
            filtered = (await client.get("/api/manager/orders?status=placed&limit=1", headers=auth)).json()
            assert filtered["total"] == 1 and len(filtered["orders"]) == 1
            stats = (await client.get("/api/manager/store/stats", headers=auth)).json()
            assert stats["order_count"] == 2 and stats["product_count"] == 3
            assert stats["item_sales_amount"] == 30  # Excludes cancelled; each item counted once.


async def test_manager_edits_other_owner_and_adds_product_with_ledger_stock(store: dict) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app()), base_url="http://test", headers=headers(store)
    ) as client:
        second = str(store["products"][1])
        assert (await client.patch(f"/api/manager/products/{second}", json={"price": 12})).status_code == 200
        assert (
            await client.patch(f"/api/manager/products/{second}/status", json={"is_active": True})
        ).status_code == 200
        response = await client.post(
            "/api/manager/products",
            json={
                "name": "New item",
                "description": "New store item",
                "category": "Books",
                "price": 15,
                "stock": [{"warehouse_id": str(store["warehouse"]), "initial_quantity": 7}],
            },
        )
        assert response.status_code == 201
        pid = response.json()["id"]
        async with store["pool"].acquire() as conn:
            assert await conn.fetchval("SELECT seller_id FROM products WHERE id=$1", uuid.UUID(pid)) is None
            assert (
                await conn.fetchval(
                    "SELECT SUM(quantity_delta) FROM inventory_movements WHERE product_id=$1", uuid.UUID(pid)
                )
                == 7
            )
        listing = (await client.get("/api/manager/store/products")).json()
        assert listing["total"] == 4 and pid in {p["id"] for p in listing["products"]}


@pytest.mark.parametrize(
    "path",
    [
        "/api/manager/store/products",
        "/api/manager/orders",
        "/api/manager/store/stats",
        "/api/seller/products",
        "/api/seller/orders",
        "/api/seller/stats",
    ],
)
async def test_customer_cannot_read_business_data_without_optional_guardrails(
    store: dict, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    monkeypatch.setattr(settings, "GUARDRAILS_ENABLED", False)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app()), base_url="http://test") as client:
        assert (await client.get(path)).status_code == 401
        assert (await client.get(path, headers=headers(store, "buyer", "customer"))).status_code == 403
        assert (await client.get(path, headers=headers(store, role="seller"))).status_code == 401
        assert (await client.get("/api/admin/returns", headers=headers(store))).status_code == 403


async def test_whole_store_tools_read_all_products_and_warehouses(store: dict) -> None:
    current_user_email.set("manager1@test.example")
    current_user_role.set("store_manager")
    assert (await get_store_products())["total"] == 3
    assert (await get_store_orders())["total"] == 2
    assert (await get_store_stats())["item_sales_amount"] == 30
    assert len(await get_store_inventory()) == 3


async def test_whole_store_tool_permissions_are_always_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "GUARDRAILS_ENABLED", False)
    current_user_email.set("buyer@test.example")
    current_user_role.set("customer")
    for function in [get_store_products, get_store_orders, get_store_stats, get_store_inventory]:
        with pytest.raises(PermissionError, match="Store manager"):
            await function()


async def test_role_migration_preserves_business_data_and_is_repeatable(store: dict) -> None:
    async with store["pool"].acquire() as conn:
        await conn.execute("UPDATE users SET role='seller' WHERE id=$1", store["users"]["manager2"])
        await conn.execute("UPDATE users SET role='power_user' WHERE id=$1", store["users"]["buyer"])
        tables = ["products", "orders", "order_items"]
        before = {table: await conn.fetch(f"SELECT * FROM {table} ORDER BY id") for table in tables}
        stock = await conn.fetch("SELECT * FROM warehouse_inventory ORDER BY product_id,warehouse_id")
        await conn.execute("DELETE FROM schema_migrations WHERE version='007_single_store_roles.sql'")
        assert await apply_migrations(conn) == ["007_single_store_roles.sql"]
        assert await conn.fetchval("SELECT role FROM users WHERE id=$1", store["users"]["manager2"]) == "store_manager"
        assert await conn.fetchval("SELECT role FROM users WHERE id=$1", store["users"]["buyer"]) == "customer"
        for table, rows in before.items():
            assert await conn.fetch(f"SELECT * FROM {table} ORDER BY id") == rows
        assert await conn.fetch("SELECT * FROM warehouse_inventory ORDER BY product_id,warehouse_id") == stock
        assert await apply_migrations(conn) == []


@pytest.mark.parametrize("name,role", [("buyer", "customer"), ("admin", "admin")])
async def test_non_managers_cannot_read_or_write_store_operations(store: dict, name: str, role: str) -> None:
    pid, wid = str(store["products"][0]), str(store["warehouse"])
    requests = [
        ("GET", "/api/manager/inventory", None),
        ("GET", "/api/manager/warehouses", None),
        ("GET", "/api/manager/catalog", None),
        ("GET", "/api/manager/analysis", None),
        ("GET", "/api/manager/analysis-runs", None),
        ("POST", "/api/manager/analysis-runs", {}),
        (
            "POST",
            "/api/manager/products",
            {"name": "Forbidden", "description": "test", "category": "Books", "price": 10},
        ),
        ("PATCH", f"/api/manager/products/{pid}", {"price": 99}),
        ("PATCH", f"/api/manager/products/{pid}/status", {"is_active": False}),
        (
            "POST",
            f"/api/manager/inventory/{pid}/{wid}/adjustments",
            {"operation": "receipt", "quantity": 5, "reason": "test"},
        ),
        ("POST", "/api/manager/marketing/copy", {"name": "test", "category": "Books"}),
        ("POST", "/api/manager/marketing/images", {"name": "test", "category": "Books"}),
    ]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app()), base_url="http://test", headers=headers(store, name, role)
    ) as client:
        for method, path, body in requests:
            response = await client.request(method, path, **({"json": body} if body is not None else {}))
            assert response.status_code == 403, (method, path, response.text)
    async with store["pool"].acquire() as conn:
        assert await conn.fetchval("SELECT price FROM products WHERE id=$1", store["products"][0]) == 10
        assert (
            await conn.fetchval(
                "SELECT quantity FROM warehouse_inventory WHERE product_id=$1 AND warehouse_id=$2",
                store["products"][0],
                store["warehouse"],
            )
            == 10
        )
        assert await conn.fetchval("SELECT count(*) FROM products") == 3
        assert await conn.fetchval("SELECT count(*) FROM marketing_generations") == 0


@pytest.mark.parametrize("name,role", [("manager1", "store_manager"), ("admin", "admin")])
async def test_non_customers_cannot_shop_even_with_valid_tokens(store: dict, name: str, role: str) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app()), base_url="http://test", headers=headers(store, name, role)
    ) as client:
        for path in ["/api/cart", "/api/orders"]:
            assert (await client.get(path)).status_code == 403
        response = await client.post("/api/cart/items", json={"product_id": str(store["products"][0]), "quantity": 1})
        assert response.status_code == 403
        assert (await client.post("/api/checkout", json={})).status_code == 403
    async with store["pool"].acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM carts") == 0
        assert await conn.fetchval("SELECT count(*) FROM orders") == 2


async def test_customer_shops_and_only_admin_reads_approval_pages(store: dict) -> None:
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app()), base_url="http://test") as client:
        for name, role in [("buyer", "customer"), ("manager1", "store_manager"), ("admin", "admin")]:
            auth = headers(store, name, role)
            assert (await client.get("/api/admin/returns", headers=auth)).status_code == (
                200 if role == "admin" else 403
            )
        auth = headers(store, "buyer", "customer")
        assert (await client.get("/api/orders", headers=auth)).status_code == 200
        assert (await client.get("/api/cart", headers=auth)).status_code == 200


@pytest.mark.parametrize("role", ["customer", "admin"])
async def test_business_ai_tools_deny_non_managers_with_safety_flag_off(
    role: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from inventory_fulfillment.tools import calculate_fulfillment_plan
    from review_sentiment.tools import draft_seller_response
    from shared.tools.sales_analysis_tools import get_sales_history

    monkeypatch.setattr(settings, "GUARDRAILS_ENABLED", False)
    current_user_role.set(role)
    current_user_email.set("identity@test.example")
    for fn in [get_store_products, get_store_orders, get_store_stats, get_store_inventory]:
        with pytest.raises(PermissionError):
            await fn()
    assert (await get_sales_history())["error"] == "permission_denied"
    assert (await calculate_fulfillment_plan(product_ids=[], destination_region="east"))["error"] == "permission_denied"
    assert (await draft_seller_response(review_id=str(uuid.uuid4())))["error"] == "permission_denied"


@pytest.mark.parametrize("role", ["store_manager", "admin"])
async def test_personal_order_and_cart_tools_deny_non_customers(role: str, monkeypatch: pytest.MonkeyPatch) -> None:
    from order_management import tools as order_tools
    from shared.tools import cart_tools, return_tools

    monkeypatch.setattr(settings, "GUARDRAILS_ENABLED", False)
    current_user_role.set(role)
    current_user_email.set("identity@test.example")
    calls = [
        (cart_tools.get_cart, {}),
        (cart_tools.add_to_cart, {"product_id": str(uuid.uuid4())}),
        (order_tools.get_user_orders, {}),
        (order_tools.cancel_order, {"order_id": str(uuid.uuid4()), "reason": "test"}),
        (return_tools.initiate_return, {"order_id": str(uuid.uuid4()), "reason": "test"}),
        (return_tools.process_refund, {"return_id": str(uuid.uuid4())}),
    ]
    for fn, kwargs in calls:
        assert (await fn(**kwargs))["error"] == "permission_denied"
