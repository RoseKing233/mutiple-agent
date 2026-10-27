"""Marketing assist against real PostgreSQL; the copy writer and image generator are fakes."""

from __future__ import annotations

import json
import uuid

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from shared import marketing
from shared.jwt_utils import create_access_token, hash_password
from shared.manager_accounts import MANAGER_EMAIL, ensure_manager

LAMP = marketing.CopyRequest(
    name="Lumo Desk Lamp 2",
    category="Home",
    brand="Lumo",
    price=39.5,
    description="Warm LED desk lamp with 3 brightness levels.",
    keywords=["eye care", "USB-C"],
)


def variant(title="Lumo Desk Lamp 2 for calm evenings", description="Three brightness levels.", highlights=None):
    return {"angle": "benefit", "title": title, "description": description, "highlights": highlights or ["USB-C"]}


def writer_returning(*variants):
    async def write(messages):
        write.messages = messages
        return json.dumps({"variants": list(variants)})

    return write


@pytest_asyncio.fixture
async def mk(clean_db, monkeypatch):
    import shared.db as db

    monkeypatch.setattr(db, "_pool", clean_db)
    async with clean_db.acquire() as conn:
        manager = await ensure_manager(conn)
        customer = uuid.uuid4()
        await conn.execute(
            """INSERT INTO users(id,email,password_hash,name,role)
            VALUES($1,'customer@test.example',$2,'Customer','customer')""",
            customer,
            hash_password("password123"),
        )
    from orchestrator.routes import router

    app = FastAPI()
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        yield {"http": http, "pool": clean_db, "manager": manager, "customer": customer}


def auth(d, role="store_manager"):
    email = MANAGER_EMAIL if role == "store_manager" else "customer@test.example"
    uid = d["manager"] if role == "store_manager" else d["customer"]
    return {"Authorization": f"Bearer {create_access_token(email, role, str(uid))}"}


async def product_count(pool) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT COUNT(*) FROM products")


# ── Copy ────────────────────────────────────────────────────────────────────


def test_variant_numbers_must_come_from_the_input():
    kept = marketing.valid_variants(
        json.dumps(
            {
                "variants": [
                    variant(description="Only $39.50 with 3 brightness levels."),  # price and 3 are in the input
                    variant(description="Rated 4.9 stars by 10,000 buyers."),  # invented
                    variant(highlights=["2-year warranty"]),  # invented
                    variant(title=""),  # malformed
                ]
            }
        ),
        LAMP,
    )
    assert [v["description"] for v in kept] == ["Only $39.50 with 3 brightness levels."]


def test_numbers_inside_product_name_are_not_claims():
    kept = marketing.valid_variants(json.dumps({"variants": [variant(title="LUMO DESK LAMP 2 by Lumo")]}), LAMP)
    assert len(kept) == 1


async def test_copy_generation_logs_and_never_touches_products(mk):
    d = mk
    writer = writer_returning(variant(), variant(title="Lumo glow"), variant(title="Desk calm"))
    result = await marketing.generate_copy(d["pool"], MANAGER_EMAIL, LAMP, writer=writer)
    assert [v["title"] for v in result["variants"]] == ["Lumo Desk Lamp 2 for calm evenings", "Lumo glow", "Desk calm"]
    assert "Never invent" in writer.messages[0]["content"]
    assert json.loads(writer.messages[1]["content"])["price"] == 39.5
    assert await product_count(d["pool"]) == 0
    async with d["pool"].acquire() as conn:
        row = await conn.fetchrow("SELECT kind, status, output FROM marketing_generations")
    assert (row["kind"], row["status"]) == ("copy", "succeeded")
    assert len(json.loads(row["output"])["variants"]) == 3


@pytest.mark.parametrize("failure", ["exception", "all_invalid", "bad_json"])
async def test_copy_failure_is_503_logged_and_form_safe(mk, monkeypatch, failure):
    d = mk

    async def broken(_messages):
        if failure == "exception":
            raise TimeoutError("provider down")
        return "not json" if failure == "bad_json" else json.dumps({"variants": [variant(description="Save 50%")]})

    monkeypatch.setattr(marketing, "openai_copy_writer", broken)
    response = await d["http"].post("/api/manager/marketing/copy", json=LAMP.model_dump(), headers=auth(d))
    assert response.status_code == 503
    assert "form is unchanged" in response.json()["detail"]
    async with d["pool"].acquire() as conn:
        assert await conn.fetchval("SELECT status FROM marketing_generations") == "failed"
    assert await product_count(d["pool"]) == 0


async def test_marketing_endpoints_require_manager(mk):
    d = mk
    for path in ["/api/manager/marketing/copy", "/api/manager/marketing/images"]:
        body = {"name": "x", "category": "Home"}
        assert (await d["http"].post(path, json=body)).status_code == 401
        assert (await d["http"].post(path, json=body, headers=auth(d, "customer"))).status_code == 403


# ── Images ──────────────────────────────────────────────────────────────────


async def test_images_are_stored_served_publicly_and_usable_as_product_image(mk, monkeypatch):
    d = mk
    calls = []

    async def fake_images(prompt, count):
        calls.append((prompt, count))
        return [b"RIFF-one-WEBP", b"RIFF-two-WEBP"]

    monkeypatch.setattr(marketing, "openai_image_generator", fake_images)
    body = {"name": "Lumo Desk Lamp", "category": "Home", "description": "Warm LED lamp", "style": "lifestyle"}
    result = await d["http"].post("/api/manager/marketing/images", json=body, headers=auth(d))
    assert result.status_code == 200, result.text
    images = result.json()["images"]
    assert len(images) == 2 and calls[0][1] == 2
    assert "Lumo Desk Lamp" in calls[0][0] and "No text" in calls[0][0] and "lifestyle" in calls[0][0]
    served = await d["http"].get(images[0]["url"])  # no auth header: product images are public
    assert served.status_code == 200 and served.content == b"RIFF-one-WEBP"
    assert served.headers["content-type"] == "image/webp"
    assert await product_count(d["pool"]) == 0

    async with d["pool"].acquire() as conn:
        warehouse = await conn.fetchval(
            "INSERT INTO warehouses(name,location,region) VALUES('East','Demo','east') RETURNING id"
        )
    saved = await d["http"].post(
        "/api/manager/products",
        json={
            "name": "Lumo Desk Lamp",
            "description": "Warm LED lamp",
            "category": "Home",
            "price": 39.5,
            "image_url": images[1]["url"],
            "stock": [{"warehouse_id": str(warehouse), "initial_quantity": 5}],
        },
        headers=auth(d),
    )
    assert saved.status_code == 201 and saved.json()["image_url"] == images[1]["url"]


async def test_image_failure_is_503_and_unknown_media_is_404(mk, monkeypatch):
    d = mk

    async def down(_prompt, _count):
        raise ConnectionError("image service down")

    monkeypatch.setattr(marketing, "openai_image_generator", down)
    response = await d["http"].post(
        "/api/manager/marketing/images", json={"name": "Lamp", "category": "Home"}, headers=auth(d)
    )
    assert response.status_code == 503
    async with d["pool"].acquire() as conn:
        assert await conn.fetchval("SELECT status FROM marketing_generations WHERE kind='image'") == "failed"
        assert await conn.fetchval("SELECT COUNT(*) FROM generated_images") == 0
    assert (await d["http"].get(f"/api/media/{uuid.uuid4()}")).status_code == 404
