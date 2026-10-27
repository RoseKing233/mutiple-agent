"""Deterministic simulation and real PostgreSQL migration/ledger contracts."""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest

from scripts.sales_data.config import SimulationConfig
from scripts.sales_data.generator import NAMESPACE, generate
from scripts.sales_data.validate import validate_database, validate_simulation
from scripts.sales_data.writer import write_simulation
from scripts.seed import seed_database
from shared.db_migrations import apply_migrations
from shared.inventory_ledger import change_inventory


def catalog(count=14):
    return [
        {"id": uuid.uuid5(NAMESPACE, f"product:{i}"), "name": f"Product {i}", "price": Decimal("25.00")}
        for i in range(count)
    ]


def simulation(seed=42):
    return generate(
        catalog(),
        [uuid.uuid5(NAMESPACE, f"warehouse:{i}") for i in range(3)],
        [uuid.uuid5(NAMESPACE, "customer")],
        SimulationConfig(end_date=date(2026, 1, 1), seed=seed),
    )


def test_simulation_is_reproducible_and_balances_reconcile():
    first, second = simulation(), simulation()
    assert first == second
    assert first.orders != simulation(43).orders
    report = validate_simulation(first)
    assert report["orders"] > 1000 and report["returns"] > 0
    assert report["unfilled_simulated_demand"] > 0
    assert {"opening", "historical_receipt", "sale", "cancel_release", "return_received"} == {
        row["movement_type"] for row in first.movements
    }


def test_profiles_have_measurable_patterns_and_launch_boundaries():
    data = simulation()
    daily = defaultdict(Counter)
    for item, order in zip(data.items, data.orders, strict=True):
        daily[str(item["product_id"])][order["created_at"].date()] += item["quantity"]
    for pid, profile in data.profiles.items():
        values = daily[pid]
        early = sum(q for day, q in values.items() if day < data.config.start_date + timedelta(days=45))
        late = sum(q for day, q in values.items() if day > data.config.end_date - timedelta(days=45))
        if profile == "growing":
            assert late > early * 1.5
        if profile == "declining":
            assert early > late * 1.5
        if profile == "weekly":
            weekend = sum(q for day, q in values.items() if day.weekday() >= 5) / 2
            weekday = sum(q for day, q in values.items() if day.weekday() < 5) / 5
            assert weekend > weekday * 1.5
        if profile == "intermittent":
            assert len(values) < data.config.days * 0.4
        if profile == "new":
            assert min(values) >= data.config.end_date - timedelta(days=27)


def test_prices_match_order_dates_and_invalid_configuration_is_rejected():
    data = simulation()
    prices = {(p["product_id"], p["recorded_at"].date()): p["price"] for p in data.prices}
    orders = {o["id"]: o for o in data.orders}
    for item in data.items:
        assert item["unit_price"] == prices[item["product_id"], orders[item["order_id"]]["created_at"].date()]
    with pytest.raises(ValueError):
        SimulationConfig(days=5)
    with pytest.raises(ValueError):
        SimulationConfig(end_date=datetime.now(UTC).date())
    with pytest.raises(ValueError):
        SimulationConfig(seed=2**31)


async def insert_stock(conn, quantity=10):
    pid, wh = uuid.uuid4(), uuid.uuid4()
    await conn.execute("INSERT INTO products(id,name,description,category,price) VALUES($1,'P','D','Books',25)", pid)
    await conn.execute("INSERT INTO warehouses(id,name,location,region) VALUES($1,'W','L','east')", wh)
    await conn.execute(
        "INSERT INTO warehouse_inventory(product_id,warehouse_id,quantity) VALUES($1,$2,$3)", pid, wh, quantity
    )
    return pid, wh


async def test_migration_baselines_existing_inventory_without_replaying_orders(clean_db):
    async with clean_db.acquire() as conn:
        pid, wh = await insert_stock(conn, 17)
        assert await apply_migrations(conn) == [
            "001_sales_inventory_history.sql",
            "002_manager_analysis.sql",
            "003_analysis_runs.sql",
            "004_inventory_management.sql",
        ]
        assert await apply_migrations(conn) == []
        rows = await conn.fetch("SELECT * FROM inventory_movements WHERE product_id=$1", pid)
        assert len(rows) == 1 and rows[0]["quantity_delta"] == 17
        assert rows[0]["movement_type"] == "opening"
        assert await conn.fetchval("SELECT quantity FROM warehouse_inventory WHERE warehouse_id=$1", wh) == 17
        assert not await seed_database(conn, SimulationConfig(end_date=date(2026, 1, 1)))
        assert await conn.fetchval("SELECT COUNT(*) FROM products") == 1


async def test_ledger_deduplicates_and_rolls_back_failures(clean_db):
    async with clean_db.acquire() as conn:
        pid, wh = await insert_stock(conn)
        kwargs = dict(product_id=pid, warehouse_id=wh, quantity_delta=-3, movement_type="sale", event_key="sale:test")
        async with conn.transaction():
            assert await change_inventory(conn, **kwargs) == 7
        async with conn.transaction():
            assert await change_inventory(conn, **kwargs) == 7
        with pytest.raises(ValueError, match="different inventory operation"):
            async with conn.transaction():
                await change_inventory(conn, **{**kwargs, "quantity_delta": -1})
        assert await conn.fetchval("SELECT COUNT(*) FROM inventory_movements WHERE movement_type='sale'") == 1
        assert not any((await validate_database(conn)).values())


async def test_ledger_negative_stock_and_business_rollback(clean_db):
    async with clean_db.acquire() as conn:
        pid, wh = await insert_stock(conn)
        with pytest.raises(ValueError):
            async with conn.transaction():
                await change_inventory(
                    conn,
                    product_id=pid,
                    warehouse_id=wh,
                    quantity_delta=-11,
                    movement_type="sale",
                    event_key="too-many",
                )
        assert await conn.fetchval("SELECT COUNT(*) FROM inventory_movements") == 0
        with pytest.raises(RuntimeError, match="later business failure"):
            async with conn.transaction():
                await change_inventory(
                    conn, product_id=pid, warehouse_id=wh, quantity_delta=-2, movement_type="sale", event_key="rollback"
                )
                raise RuntimeError("later business failure")
        assert await conn.fetchval("SELECT quantity FROM warehouse_inventory") == 10
        assert await conn.fetchval("SELECT COUNT(*) FROM inventory_movements") == 0


async def test_bulk_writer_and_daily_views_on_real_postgres(clean_db):
    data = simulation()
    async with clean_db.acquire() as conn:
        async with conn.transaction():
            for p in catalog():
                await conn.execute(
                    """INSERT INTO products(id,name,description,category,price)
                    VALUES($1,$2,'demo','Books',$3)""",
                    p["id"],
                    p["name"],
                    p["price"],
                )
            for wh in {pair[1] for pair in data.inventory}:
                await conn.execute("INSERT INTO warehouses(id,name,location,region) VALUES($1,'W','L','east')", wh)
            await conn.execute(
                """INSERT INTO users(id,email,password_hash,name,role)
                VALUES($1,'simulation@example.com','hash','C','customer')""",
                data.orders[0]["user_id"],
            )
            await write_simulation(conn, data)
        assert not any((await validate_database(conn)).values())
        assert await conn.fetchval("SELECT SUM(ordered_units) FROM sales_daily") == sum(
            i["quantity"] for i in data.items
        )
        assert await conn.fetchval("SELECT COUNT(*) FROM inventory_daily_changes") > 180
        assert await conn.fetchval("SELECT COUNT(*) FROM sales_dataset_runs") == 1


async def test_full_seeder_preserves_existing_data_on_second_run(clean_db):
    async with clean_db.acquire() as conn:
        config = SimulationConfig(days=60, end_date=date(2026, 1, 1))
        assert await seed_database(conn, config)
        before = await conn.fetchval("SELECT COUNT(*) FROM orders")
        assert before > 1000
        assert not await seed_database(conn, config)
        assert await conn.fetchval("SELECT COUNT(*) FROM orders") == before
        assert not any((await validate_database(conn)).values())
        first = await conn.fetch("SELECT id,user_id,status,total,created_at FROM orders ORDER BY id")
        assert await seed_database(conn, config, reset=True)
        assert await conn.fetch("SELECT id,user_id,status,total,created_at FROM orders ORDER BY id") == first
        assert not any((await validate_database(conn)).values())


async def test_migration_checksum_detects_edits(clean_db):
    async with clean_db.acquire() as conn:
        await apply_migrations(conn)
        await conn.execute("UPDATE schema_migrations SET checksum='changed'")
        with pytest.raises(RuntimeError, match="Applied migration changed"):
            await apply_migrations(conn)


def test_validator_rejects_corrupted_history():
    data = simulation()
    data.movements[-1]["balance_after"] += 1
    with pytest.raises(ValueError, match="inventory balance"):
        validate_simulation(data)
