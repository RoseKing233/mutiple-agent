"""Inventory CRUD, suggestions and chat consent against real PostgreSQL; LLM writers are fakes."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from shared import inventory_actions as actions
from shared import inventory_suggestions as sug
from shared.jwt_utils import create_access_token, hash_password
from shared.manager_accounts import MANAGER_EMAIL, ensure_manager


@pytest_asyncio.fixture
async def inv(clean_db, monkeypatch):
    import shared.db as db

    monkeypatch.setattr(db, "_pool", clean_db)
    created = datetime.now(UTC) - timedelta(days=60)
    async with clean_db.acquire() as conn:
        manager = await ensure_manager(conn)
        customer = uuid.uuid4()
        await conn.execute(
            """INSERT INTO users(id,email,password_hash,name,role)
            VALUES($1,'customer@test.example',$2,'Customer','customer')""",
            customer,
            hash_password("password123"),
        )
        stocked, empty, east, west = [uuid.uuid4() for _ in range(4)]
        for pid, name in [(stocked, "Stocked Book"), (empty, "Empty Book")]:
            await conn.execute(
                "INSERT INTO products(id,name,description,category,price,created_at) "
                "VALUES($1,$2,'Demo','Books',10,$3)",
                pid,
                name,
                created,
            )
        for wh, name in [(east, "East"), (west, "West")]:
            await conn.execute("INSERT INTO warehouses(id,name,location,region) VALUES($1,$2,'Demo','east')", wh, name)
        for pid, wh, qty in [(stocked, east, 30), (empty, east, 0)]:
            await conn.execute(
                "INSERT INTO warehouse_inventory(product_id,warehouse_id,quantity,reorder_threshold) "
                "VALUES($1,$2,$3,10)",
                pid,
                wh,
                qty,
            )
            await conn.execute(
                """INSERT INTO inventory_movements
                (event_key,product_id,warehouse_id,movement_type,quantity_delta,balance_after,occurred_at)
                VALUES($1,$2,$3,'opening',$4,$4,$5)""",
                f"opening:{wh}:{pid}",
                pid,
                wh,
                qty,
                created,
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
            "stocked": stocked,
            "empty": empty,
            "east": east,
            "west": west,
        }


def auth(d, role="store_manager"):
    email = MANAGER_EMAIL if role == "store_manager" else "customer@test.example"
    uid = d["manager"] if role == "store_manager" else d["customer"]
    return {"Authorization": f"Bearer {create_access_token(email, role, str(uid))}"}


async def ledger_matches(pool, pid, wh) -> int:
    async with pool.acquire() as conn:
        qty = await conn.fetchval(
            "SELECT quantity FROM warehouse_inventory WHERE product_id=$1 AND warehouse_id=$2", pid, wh
        )
        total = await conn.fetchval(
            "SELECT SUM(quantity_delta) FROM inventory_movements WHERE product_id=$1 AND warehouse_id=$2", pid, wh
        )
    assert qty == total
    return qty


# ── Permissions ─────────────────────────────────────────────────────────────


async def test_inventory_endpoints_require_manager(inv):
    d = inv
    for method, path in [
        ("GET", "/api/manager/inventory"),
        ("GET", "/api/manager/warehouses"),
        ("GET", "/api/manager/inventory-suggestions"),
        ("POST", f"/api/manager/inventory/{d['stocked']}/{d['east']}/adjustments"),
        ("PATCH", f"/api/manager/products/{d['stocked']}/status"),
    ]:
        assert (await d["http"].request(method, path, json={})).status_code == 401
        assert (await d["http"].request(method, path, json={}, headers=auth(d, "customer"))).status_code == 403


# ── Inventory rows and adjustments ──────────────────────────────────────────


async def test_adjustments_write_ledger_and_reject_oversell(inv):
    d = inv
    url = f"/api/manager/inventory/{d['stocked']}/{d['east']}/adjustments"
    receipt = {"kind": "manual_receipt", "quantity": 5, "reason": "Supplier delivery"}
    r = await d["http"].post(url, json=receipt, headers=auth(d))
    assert r.status_code == 200, r.text
    assert r.json()["quantity"] == 35
    issue = await d["http"].post(
        url, json={"kind": "manual_issue", "quantity": 99, "reason": "Damaged"}, headers=auth(d)
    )
    assert issue.status_code == 422 and "Insufficient" in issue.json()["detail"]
    count = await d["http"].post(
        url, json={"kind": "stock_count_adjustment", "quantity": 31, "reason": "Cycle count"}, headers=auth(d)
    )
    assert count.json()["quantity_delta"] == -4 and count.json()["quantity"] == 31
    assert await ledger_matches(d["pool"], d["stocked"], d["east"]) == 31
    history = await d["http"].get(f"/api/manager/inventory/{d['stocked']}/{d['east']}/movements", headers=auth(d))
    types = [m["movement_type"] for m in history.json()["movements"]]
    assert types == ["stock_count_adjustment", "manual_receipt", "opening"]
    assert "by manager.demo@gmail.com" in history.json()["movements"][0]["notes"]


async def test_retried_request_id_does_not_apply_twice(inv):
    d = inv
    url = f"/api/manager/inventory/{d['stocked']}/{d['east']}/adjustments"
    body = {"kind": "manual_receipt", "quantity": 7, "reason": "Delivery", "request_id": str(uuid.uuid4())}
    first = await d["http"].post(url, json=body, headers=auth(d))
    second = await d["http"].post(url, json=body, headers=auth(d))
    assert first.json()["quantity"] == second.json()["quantity"] == 37
    assert second.json()["replayed"] is True
    assert await ledger_matches(d["pool"], d["stocked"], d["east"]) == 37


async def test_inventory_row_create_threshold_and_delete_rules(inv):
    d = inv
    created = await d["http"].post(
        "/api/manager/inventory",
        json={"product_id": str(d["stocked"]), "warehouse_id": str(d["west"]), "initial_quantity": 4},
        headers=auth(d),
    )
    assert created.status_code == 201 and created.json()["quantity"] == 4
    assert await ledger_matches(d["pool"], d["stocked"], d["west"]) == 4
    duplicate = await d["http"].post(
        "/api/manager/inventory",
        json={"product_id": str(d["stocked"]), "warehouse_id": str(d["west"])},
        headers=auth(d),
    )
    assert duplicate.status_code == 409
    patched = await d["http"].patch(
        f"/api/manager/inventory/{d['stocked']}/{d['west']}", json={"reorder_threshold": 3}, headers=auth(d)
    )
    assert patched.json()["reorder_threshold"] == 3
    blocked = await d["http"].delete(f"/api/manager/inventory/{d['stocked']}/{d['west']}", headers=auth(d))
    assert blocked.status_code == 422
    await d["http"].post(
        f"/api/manager/inventory/{d['stocked']}/{d['west']}/adjustments",
        json={"kind": "manual_issue", "quantity": 4, "reason": "Transfer out"},
        headers=auth(d),
    )
    deleted = await d["http"].delete(f"/api/manager/inventory/{d['stocked']}/{d['west']}", headers=auth(d))
    assert deleted.status_code == 200
    low = await d["http"].get("/api/manager/inventory?low_stock_only=true", headers=auth(d))
    assert [i["product_name"] for i in low.json()["items"]] == ["Empty Book"]


async def test_transfer_moves_stock_creates_destination_row_and_is_idempotent(inv):
    d = inv
    body = {
        "product_id": str(d["stocked"]),
        "from_warehouse_id": str(d["east"]),
        "to_warehouse_id": str(d["west"]),  # no row there yet
        "quantity": 30,  # everything: the store-wide total must still never read zero
        "reason": "Rebalance to West",
        "request_id": str(uuid.uuid4()),
    }
    first = await d["http"].post("/api/manager/inventory/transfers", json=body, headers=auth(d))
    assert first.status_code == 200, first.text
    assert (first.json()["from_quantity"], first.json()["to_quantity"]) == (0, 30)
    retry = await d["http"].post("/api/manager/inventory/transfers", json=body, headers=auth(d))
    assert retry.json()["replayed"] is True
    assert await ledger_matches(d["pool"], d["stocked"], d["east"]) == 0
    assert await ledger_matches(d["pool"], d["stocked"], d["west"]) == 30
    async with d["pool"].acquire() as conn:
        legs = await conn.fetch(
            """SELECT movement_type, occurred_at FROM inventory_movements
               WHERE event_key LIKE 'transfer:%' ORDER BY occurred_at, id"""
        )
    assert [r["movement_type"] for r in legs] == ["transfer_in", "transfer_out"]
    assert legs[0]["occurred_at"] == legs[1]["occurred_at"]


async def test_transfer_rejects_bad_requests(inv):
    d = inv
    base = {"product_id": str(d["stocked"]), "reason": "Rebalance", "quantity": 5}
    url = "/api/manager/inventory/transfers"
    same = await d["http"].post(
        url, json=base | {"from_warehouse_id": str(d["east"]), "to_warehouse_id": str(d["east"])}, headers=auth(d)
    )
    assert same.status_code == 422
    too_many = await d["http"].post(
        url,
        json=base | {"quantity": 31, "from_warehouse_id": str(d["east"]), "to_warehouse_id": str(d["west"])},
        headers=auth(d),
    )
    assert too_many.status_code == 422 and "Insufficient" in too_many.json()["detail"]
    no_source = await d["http"].post(
        url, json=base | {"from_warehouse_id": str(d["west"]), "to_warehouse_id": str(d["east"])}, headers=auth(d)
    )
    assert no_source.status_code == 404
    async with d["pool"].acquire() as conn:
        # The failed request rolled back, including the destination row it would have created.
        assert not await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM warehouse_inventory WHERE product_id=$1 AND warehouse_id=$2)",
            d["stocked"],
            d["west"],
        )
    assert (await d["http"].post(url, json=base, headers=auth(d, "customer"))).status_code == 403


async def test_product_without_stock_gets_zero_row_in_first_warehouse(inv):
    d = inv
    created = await d["http"].post(
        "/api/manager/products",
        json={"name": "Plain Mug", "description": "White mug", "category": "Home", "price": 9},
        headers=auth(d),
    )
    assert created.status_code == 201, created.text
    stock = created.json()["stock"]
    assert [(s["warehouse_name"], s["quantity"]) for s in stock] == [("East", 0)]  # "East" sorts before "West"
    listed = await d["http"].get("/api/manager/inventory?search=Plain Mug", headers=auth(d))
    assert [i["warehouse_name"] for i in listed.json()["items"]] == ["East"]
    receipt = await d["http"].post(
        f"/api/manager/inventory/{created.json()['id']}/{stock[0]['warehouse_id']}/adjustments",
        json={"kind": "manual_receipt", "quantity": 12, "reason": "First delivery"},
        headers=auth(d),
    )
    assert receipt.json()["quantity"] == 12


# ── Warehouses ──────────────────────────────────────────────────────────────


async def test_warehouse_crud_and_deactivation_guard(inv):
    d = inv
    created = await d["http"].post(
        "/api/manager/warehouses", json={"name": "North", "location": "Sydney", "region": "North"}, headers=auth(d)
    )
    assert created.status_code == 201 and created.json()["region"] == "north"
    north = created.json()["id"]
    renamed = await d["http"].patch(f"/api/manager/warehouses/{north}", json={"name": "North DC"}, headers=auth(d))
    assert renamed.json()["name"] == "North DC"
    busy = await d["http"].delete(f"/api/manager/warehouses/{d['east']}", headers=auth(d))
    assert busy.status_code == 422 and "30 units" in busy.json()["detail"]
    assert (await d["http"].delete(f"/api/manager/warehouses/{north}", headers=auth(d))).json()["is_active"] is False
    stock_into_inactive = await d["http"].post(
        "/api/manager/inventory",
        json={"product_id": str(d["stocked"]), "warehouse_id": north, "initial_quantity": 1},
        headers=auth(d),
    )
    assert stock_into_inactive.status_code == 422
    listing = await d["http"].get("/api/manager/warehouses", headers=auth(d))
    assert {w["name"]: w["total_quantity"] for w in listing.json()["warehouses"]}["East"] == 30


# ── Products ────────────────────────────────────────────────────────────────


async def test_product_create_update_and_delist_blocks_shopping(inv):
    d = inv
    created = await d["http"].post(
        "/api/manager/products",
        json={
            "name": "New Lamp",
            "description": "Warm desk lamp",
            "category": "Home",
            "price": 39.5,
            "specs": {"watts": 8},
            "stock": [{"warehouse_id": str(d["east"]), "initial_quantity": 12, "reorder_threshold": 4}],
        },
        headers=auth(d),
    )
    assert created.status_code == 201, created.text
    product = created.json()
    assert product["total_quantity"] == 12 and product["specs"] == {"watts": 8}
    assert await ledger_matches(d["pool"], uuid.UUID(product["id"]), d["east"]) == 12
    updated = await d["http"].patch(
        f"/api/manager/products/{product['id']}", json={"price": 35, "brand": "Lumo"}, headers=auth(d)
    )
    assert updated.json()["price"] == 35 and updated.json()["brand"] == "Lumo"
    delisted = await d["http"].patch(
        f"/api/manager/products/{product['id']}/status", json={"is_active": False}, headers=auth(d)
    )
    assert delisted.json()["is_active"] is False
    listing = await d["http"].get("/api/products?search=Lamp")
    assert product["id"] not in [p["id"] for p in listing.json()["products"]]
    add = await d["http"].post(
        "/api/cart/items", json={"product_id": product["id"], "quantity": 1}, headers=auth(d, "customer")
    )
    assert add.status_code == 400 and add.json()["detail"] == "Product is no longer available"
    relisted = await d["http"].patch(
        f"/api/manager/products/{product['id']}/status", json={"is_active": True}, headers=auth(d)
    )
    assert relisted.json()["is_active"] is True
    listing = await d["http"].get("/api/products?search=Lamp")
    assert product["id"] in [p["id"] for p in listing.json()["products"]]


# ── Suggestion rules (pure) ─────────────────────────────────────────────────


def report_for(perf: dict, forecast: dict) -> dict:
    return {
        "products": [
            {"product_id": "p1", "name": "Widget", "category": "Books", "performance": perf, "forecast": forecast}
        ]
    }


def rows(qty: int, threshold: int = 10) -> dict:
    return {
        "p1": [
            {
                "warehouse_id": "w1",
                "warehouse_name": "East",
                "warehouse_active": True,
                "quantity": qty,
                "reorder_threshold": threshold,
            }
        ]
    }


PERF = {"trend": "stable", "recent_units": 56, "comparison_days": 28, "days_of_cover": 10, "overstock": False}


def test_rule_restock_from_forecast_with_depletion_priority():
    forecast = {"available": True, "model": "mean_28", "reliability": "moderate", "series": [{"units": 2}] * 14}
    result = sug.compute_suggestions(report_for(PERF, forecast), rows(9), sug.SuggestionRules(), date(2026, 10, 26))
    s = result[0]
    assert s["suggestion_type"] == "restock"
    assert s["evidence"]["days_to_stockout"] == 5 and s["evidence"]["projected_stockout_date"] == "2026-10-31"
    assert s["priority"] == "high"  # within urgent_days=7
    assert s["suggested_quantity"] == 28 + 10 - 9
    assert s["warehouse_name"] == "East"


def test_rule_restock_without_forecast_uses_threshold_fallback_low_confidence():
    result = sug.compute_suggestions(
        report_for(PERF, {"available": False}), rows(0), sug.SuggestionRules(), date(2026, 10, 26)
    )
    assert result[0]["suggested_quantity"] == 20 and result[0]["priority"] == "high"
    assert result[0]["evidence"]["confidence"] == "low"


def test_rule_no_suggestion_when_healthy():
    forecast = {"available": True, "series": [{"units": 1}] * 14}
    assert (
        sug.compute_suggestions(report_for(PERF, forecast), rows(100), sug.SuggestionRules(), date(2026, 10, 26)) == []
    )


def test_rule_overstock_excess_above_target_cover():
    perf = PERF | {"recent_units": 28, "overstock": True, "days_of_cover": 200}
    forecast = {"available": True, "series": [{"units": 1}] * 14}
    s = sug.compute_suggestions(report_for(perf, forecast), rows(200), sug.SuggestionRules(), date(2026, 10, 26))[0]
    assert s["suggestion_type"] == "overstock"
    assert s["evidence"]["target_stock"] == 30 and s["suggested_quantity"] == 170
    assert s["priority"] == "high"  # cover 200 > 4 * 30


def test_grounding_rejects_invented_numbers():
    s = {"suggested_quantity": 29, "evidence": {"live_stock": 9, "projected_stockout_date": "2026-10-31"}}
    assert sug.grounded("Only 9 units left; order 29 before 2026-10-31.", s)
    assert not sug.grounded("Order 500 units now.", s)
    assert not sug.grounded("It runs out on 2026-11-30.", s)


def test_grounding_ignores_numbers_inside_names():
    # Found in the live run: half of real AI rationales were rejected because of model numbers in names.
    s = {
        "product_name": "Sony WH-1000XM5",
        "warehouse_name": "Warehouse 7",
        "suggested_quantity": 60,
        "evidence": {"live_stock": 0},
    }
    assert sug.grounded("The Sony WH-1000XM5 is out of stock (0 units); order 60 for Warehouse 7.", s)
    assert not sug.grounded("The Sony WH-1000XM5 sold 1000 units.", s)


# ── Suggestions end to end ──────────────────────────────────────────────────


async def test_generate_with_ai_rationale_then_accept_receives_stock(inv):
    d = inv

    async def writer(messages):
        items = json.loads(messages[1]["content"])["items"]
        return json.dumps(
            {"rationales": [{"key": i["key"], "rationale": f"{i['product']} needs attention."} for i in items]}
        )

    result = await sug.generate_suggestions(d["pool"], MANAGER_EMAIL, sug.GenerateRequest(), writer=writer)
    empty = next(s for s in result["suggestions"] if s["product_name"] == "Empty Book")
    assert empty["suggestion_type"] == "restock" and empty["priority"] == "high"
    assert empty["rationale_source"] == "ai" and result["ai_rationale"] == "used"
    decided = await d["http"].post(
        f"/api/manager/inventory-suggestions/{empty['id']}/decision",
        json={"decision": "accept", "quantity": 15},
        headers=auth(d),
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["stock_changed"] is True and decided.json()["warehouse_balance"] == 15
    assert await ledger_matches(d["pool"], d["empty"], d["east"]) == 15
    again = await d["http"].post(
        f"/api/manager/inventory-suggestions/{empty['id']}/decision", json={"decision": "accept"}, headers=auth(d)
    )
    assert again.status_code == 409
    async with d["pool"].acquire() as conn:
        assert (
            await conn.fetchval(
                "SELECT movement_type FROM inventory_movements WHERE event_key=$1", f"suggestion:{empty['id']}"
            )
            == "restock_receipt"
        )


async def test_ai_failure_or_ungrounded_text_falls_back_to_rules(inv):
    d = inv

    async def broken(_messages):
        raise TimeoutError("provider down")

    result = await sug.generate_suggestions(d["pool"], MANAGER_EMAIL, sug.GenerateRequest(), writer=broken)
    assert result["ai_rationale"] == "unavailable" and result["suggestions"]
    assert all(s["rationale_source"] == "rule" and s["rationale"] for s in result["suggestions"])

    async def inventive(messages):
        items = json.loads(messages[1]["content"])["items"]
        return json.dumps({"rationales": [{"key": i["key"], "rationale": "Order 9999 units."} for i in items]})

    second = await sug.generate_suggestions(d["pool"], MANAGER_EMAIL, sug.GenerateRequest(), writer=inventive)
    assert all(s["rationale_source"] == "rule" for s in second["suggestions"])
    async with d["pool"].acquire() as conn:
        statuses = await conn.fetch("SELECT status, COUNT(*) FROM inventory_suggestions GROUP BY status")
    assert {r["status"]: r["count"] for r in statuses} == {"superseded": 1, "pending": 1}


async def test_reject_and_delist_do_not_change_stock(inv):
    d = inv
    result = await sug.generate_suggestions(d["pool"], MANAGER_EMAIL, sug.GenerateRequest(), writer=None)
    sid = result["suggestions"][0]["id"]
    rejected = await d["http"].post(
        f"/api/manager/inventory-suggestions/{sid}/decision",
        json={"decision": "reject", "note": "Supplier discontinued"},
        headers=auth(d),
    )
    assert rejected.json() == {"id": sid, "status": "rejected", "stock_changed": False}
    assert await ledger_matches(d["pool"], d["empty"], d["east"]) == 0
    await sug.generate_suggestions(d["pool"], MANAGER_EMAIL, sug.GenerateRequest(), writer=None)
    await d["http"].patch(f"/api/manager/products/{d['empty']}/status", json={"is_active": False}, headers=auth(d))
    pending = await d["http"].get("/api/manager/inventory-suggestions", headers=auth(d))
    assert pending.json()["total"] == 0


# ── Chat two-step consent ───────────────────────────────────────────────────


async def say(pool, conversation, content, role="user"):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO messages(conversation_id, role, content, created_at) VALUES($1,$2,$3,clock_timestamp())",
            conversation,
            role,
            content,
        )


@pytest_asyncio.fixture
async def conversation(inv):
    async with inv["pool"].acquire() as conn:
        cid = await conn.fetchval(
            "INSERT INTO conversations(user_id, title) VALUES($1,'inventory') RETURNING id", inv["manager"]
        )
    await say(inv["pool"], cid, "Receive 5 Stocked Book into East")
    return str(cid)


def receipt_payload(d, quantity=5):
    return {
        "product_id": str(d["stocked"]),
        "warehouse_id": str(d["east"]),
        "adjustment": {"kind": "manual_receipt", "quantity": quantity, "reason": "Supplier delivery"},
    }


async def test_chat_action_needs_a_newer_explicit_confirmation(inv, conversation):
    d = inv
    proposal = await actions.propose(d["pool"], MANAGER_EMAIL, conversation, "stock_adjustment", receipt_payload(d))
    assert proposal["preview"]["quantity_after"] == 35
    action_id = uuid.UUID(proposal["action_id"])
    # The model calling confirm in the same turn is refused: no user reply since the preview.
    early = await actions.confirm(d["pool"], MANAGER_EMAIL, conversation, action_id)
    assert early["status"] == "awaiting_user_confirmation"
    await say(d["pool"], conversation, "Hmm, maybe not yet")
    assert (await actions.confirm(d["pool"], MANAGER_EMAIL, conversation, action_id))["status"] == (
        "awaiting_user_confirmation"
    )
    assert await ledger_matches(d["pool"], d["stocked"], d["east"]) == 30
    await say(d["pool"], conversation, "确认")
    # Without the ID (orchestrator dropped it): the conversation's latest pending action is used.
    done = await actions.confirm(d["pool"], MANAGER_EMAIL, conversation)
    assert done["status"] == "executed" and done["result"]["quantity"] == 35
    replay = await actions.confirm(d["pool"], MANAGER_EMAIL, conversation, action_id)
    assert replay["status"] == "executed"
    assert await ledger_matches(d["pool"], d["stocked"], d["east"]) == 35


async def test_chat_proposal_accepts_warehouse_names(inv, conversation):
    # Found in the live run: the agent only knows warehouse names, never their UUIDs.
    d = inv
    proposal = await actions.propose(
        d["pool"], MANAGER_EMAIL, conversation, "stock_adjustment", receipt_payload(d) | {"warehouse_id": "east"}
    )
    assert proposal["preview"]["summary"].endswith("at East")
    async with d["pool"].acquire() as conn:
        stored = await conn.fetchval(
            "SELECT payload->>'warehouse_id' FROM inventory_action_requests WHERE id=$1",
            uuid.UUID(proposal["action_id"]),
        )
    assert stored == str(d["east"])
    with pytest.raises(LookupError):
        await actions.propose(
            d["pool"], MANAGER_EMAIL, conversation, "stock_adjustment", receipt_payload(d) | {"warehouse_id": "Mars"}
        )


async def test_chat_action_is_scoped_to_conversation_and_cancellable(inv, conversation):
    d = inv
    proposal = await actions.propose(
        d["pool"],
        MANAGER_EMAIL,
        conversation,
        "product_status",
        {
            "product_id": str(d["stocked"]),
            "is_active": False,
        },
    )
    action_id = uuid.UUID(proposal["action_id"])
    with pytest.raises(LookupError):
        await actions.confirm(d["pool"], MANAGER_EMAIL, str(uuid.uuid4()), action_id)
    cancelled = await actions.cancel(d["pool"], MANAGER_EMAIL, conversation)  # no ID: latest pending
    assert cancelled["status"] == "cancelled"
    await say(d["pool"], conversation, "yes")
    assert (await actions.confirm(d["pool"], MANAGER_EMAIL, conversation, action_id))["status"] == "cancelled"
    async with d["pool"].acquire() as conn:
        assert await conn.fetchval("SELECT is_active FROM products WHERE id=$1", d["stocked"]) is True


async def test_chat_proposal_validates_and_failed_execution_is_recorded(inv, conversation):
    d = inv
    with pytest.raises(ValueError):
        await actions.propose(
            d["pool"],
            MANAGER_EMAIL,
            conversation,
            "stock_adjustment",
            {
                **receipt_payload(d),
                "adjustment": {"kind": "manual_issue", "quantity": 99, "reason": "Damaged"},
            },
        )
    proposal = await actions.propose(
        d["pool"],
        MANAGER_EMAIL,
        conversation,
        "stock_adjustment",
        {
            **receipt_payload(d),
            "adjustment": {"kind": "manual_issue", "quantity": 25, "reason": "Damaged"},
        },
    )
    # Stock drops after the preview, so the confirmed issue can no longer be fulfilled.
    async with d["pool"].acquire() as conn:
        async with conn.transaction():
            from shared.inventory_management import StockAdjustment, adjust_stock

            await adjust_stock(
                conn, d["stocked"], d["east"], StockAdjustment(kind="manual_issue", quantity=20, reason="Sold"), "x"
            )
    await say(d["pool"], conversation, "confirm")
    failed = await actions.confirm(d["pool"], MANAGER_EMAIL, conversation, uuid.UUID(proposal["action_id"]))
    assert failed["status"] == "failed" and "Insufficient" in failed["result"]["error"]
    assert await ledger_matches(d["pool"], d["stocked"], d["east"]) == 10


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("确认", True),
        ("好的，执行吧", True),
        ("Yes, go ahead", True),
        ("confirm", True),
        ("不要", False),
        ("先不确认", False),
        ("no, cancel it", False),
        ("Can you also check West first and then maybe receive more units into it?", False),
        ("", False),
    ],
)
def test_consent_detection(text, expected):
    assert actions.is_explicit_consent(text) is expected
