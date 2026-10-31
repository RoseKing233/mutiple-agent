"""RBAC coverage for the six tools guarded by ``@requires_role`` in this change:

- ``review_sentiment.tools.draft_seller_response`` -> store_manager
- ``inventory_fulfillment.tools.calculate_fulfillment_plan`` -> store_manager
- ``inventory_fulfillment.tools.place_backorder`` -> customer
- ``order_management.tools.cancel_order`` -> customer, with ownership check
- ``order_management.tools.modify_order`` -> customer, with ownership check
- ``shared.tools.return_tools.process_refund`` -> customer, with ownership check

The generic decorator/guard-clause behavior (no implicit admin bypass, signature
preservation, flag-independent enforcement) is already exhaustively covered by
``test_guardrails_roles.py`` against a synthetic tool. This file only proves
each REAL tool got the decorator wired at the right role set and that a
denial happens before any DB work (no seed fixtures needed for the denied
cases — the guard is the outermost check in every one of these functions).
"""

from __future__ import annotations

import uuid

import asyncpg
import pytest
import pytest_asyncio

import shared.db as shared_db
from inventory_fulfillment.tools import calculate_fulfillment_plan, place_backorder
from order_management.tools import cancel_order, modify_order
from review_sentiment.tools import draft_seller_response
from shared.config import settings
from shared.context import current_user_email, current_user_role
from shared.tools.return_tools import process_refund

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def db_pool(clean_db: asyncpg.Pool, monkeypatch: pytest.MonkeyPatch) -> asyncpg.Pool:
    """Inject clean_db into shared.db so get_pool() resolves for allowed-role calls."""
    monkeypatch.setattr(shared_db, "_pool", clean_db)
    return clean_db


@pytest.fixture(autouse=True)
def _enable_guardrails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "GUARDRAILS_ENABLED", True, raising=False)
    current_user_role.set("")
    current_user_email.set("")


# ─────────────────────── store_manager-only tools ─────────────────────────────


async def test_draft_seller_response_denied_for_customer() -> None:
    current_user_role.set("customer")
    result = await draft_seller_response(review_id=str(uuid.uuid4()))
    assert result["error"] == "permission_denied"
    assert "store_manager" in result["required_roles"]


async def test_draft_seller_response_allowed_for_store_manager(db_pool: asyncpg.Pool) -> None:
    current_user_role.set("store_manager")
    result = await draft_seller_response(review_id=str(uuid.uuid4()))
    # Guard passed through to real logic (a random id simply isn't found).
    assert result["error"] != "permission_denied"
    assert result["error"].startswith("Review not found")


async def test_draft_seller_response_denied_for_admin(db_pool: asyncpg.Pool) -> None:
    current_user_role.set("admin")
    result = await draft_seller_response(review_id=str(uuid.uuid4()))
    assert result["error"] == "permission_denied"


async def test_calculate_fulfillment_plan_denied_for_customer() -> None:
    current_user_role.set("customer")
    result = await calculate_fulfillment_plan(product_ids=[], destination_region="east")
    assert result["error"] == "permission_denied"
    assert "store_manager" in result["required_roles"]


async def test_calculate_fulfillment_plan_allowed_for_store_manager() -> None:
    current_user_role.set("store_manager")
    # Empty product_ids short-circuits before any DB access — proves pass-through
    # without needing seed data.
    result = await calculate_fulfillment_plan(product_ids=[], destination_region="east")
    assert result == {"error": "No product IDs provided"}


async def test_place_backorder_denied_for_manager() -> None:
    current_user_role.set("store_manager")
    result = await place_backorder(product_id=str(uuid.uuid4()), quantity=1)
    assert result["error"] == "permission_denied"
    assert "customer" in result["required_roles"]


async def test_place_backorder_allowed_for_customer() -> None:
    current_user_role.set("customer")
    # No user context set — reaches the tool's own "no user" guard clause,
    # proving the role check passed through without needing seed data.
    result = await place_backorder(product_id=str(uuid.uuid4()), quantity=1)
    assert result["error"] != "permission_denied"


# ─────────────────────── customer/store_manager tools ─────────────────────────


async def test_cancel_order_denied_with_no_role() -> None:
    current_user_role.set("")
    result = await cancel_order(order_id=str(uuid.uuid4()), reason="changed my mind")
    assert result["error"] == "permission_denied"


async def test_cancel_order_allowed_for_customer() -> None:
    current_user_role.set("customer")
    result = await cancel_order(order_id=str(uuid.uuid4()), reason="changed my mind")
    assert result["error"] != "permission_denied"


async def test_modify_order_denied_with_no_role() -> None:
    current_user_role.set("")
    result = await modify_order(
        order_id=str(uuid.uuid4()),
        new_address={"street": "1 Main St", "city": "Springfield", "state": "IL", "zip": "62701", "country": "US"},
    )
    assert result["error"] == "permission_denied"


async def test_modify_order_allowed_for_customer() -> None:
    current_user_role.set("customer")
    result = await modify_order(
        order_id=str(uuid.uuid4()),
        new_address={"street": "1 Main St", "city": "Springfield", "state": "IL", "zip": "62701", "country": "US"},
    )
    assert result["error"] != "permission_denied"


async def test_process_refund_denied_with_no_role() -> None:
    current_user_role.set("")
    result = await process_refund(return_id=str(uuid.uuid4()))
    assert result["error"] == "permission_denied"


async def test_process_refund_allowed_for_customer() -> None:
    current_user_role.set("customer")
    result = await process_refund(return_id=str(uuid.uuid4()))
    assert result["error"] != "permission_denied"


async def test_process_refund_denied_for_admin() -> None:
    current_user_role.set("admin")
    result = await process_refund(return_id=str(uuid.uuid4()))
    assert result["error"] == "permission_denied"


# ─────────────────────── always-on authorization (representative) ────────────────────


async def test_guardrails_disabled_still_denies_wrong_role(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "GUARDRAILS_ENABLED", False)
    current_user_role.set("customer")
    result = await calculate_fulfillment_plan(product_ids=[], destination_region="east")
    # Content-safety settings never disable business authorization.
    assert result["error"] == "permission_denied"
