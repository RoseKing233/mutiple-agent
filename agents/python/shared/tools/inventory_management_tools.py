"""Manager-only inventory tools. Writes are two-step: propose_* then confirm_inventory_action.

confirm_inventory_action executes only when the server sees an explicit user confirmation
newer than the proposal in the same conversation (see shared/inventory_actions.py).
"""

from typing import Annotated, Literal
from uuid import UUID

from agent_framework import tool
from pydantic import Field

from shared import inventory_actions as actions
from shared.context import current_session_id, current_user_email
from shared.db import get_pool
from shared.inventory_management import list_inventory
from shared.inventory_suggestions import GenerateRequest, SuggestionRules, generate_suggestions, list_suggestions
from shared.tools.sales_analysis_tools import denied

ERRORS = (ValueError, LookupError, PermissionError)


def failure(exc: Exception) -> dict:
    return {"error": "inventory_request_failed", "message": str(exc), "stock_changed": False}


@tool(
    name="generate_inventory_suggestions",
    description=(
        "Manager only: compute and save restock (stockout risk) and overstock suggestions from live stock and "
        "the sales forecast. Quantities come from code. Never changes stock; suggestions stay pending."
    ),
)
async def generate_inventory_suggestions(
    horizon: Annotated[int, Field(description="Forecast days: 7, 14 or 28")] = 14,
    category: Annotated[str, Field(description="Exact category, empty for all")] = "",
    product_id: Annotated[str, Field(description="Product UUID, empty for all")] = "",
) -> dict:
    if error := denied():
        return error
    try:
        result = await generate_suggestions(
            get_pool(),
            current_user_email.get(),
            GenerateRequest(
                category=category or None,
                product_id=product_id or None,
                rules=SuggestionRules(horizon=horizon),
            ),
        )
        # Keep the tool payload bounded; the page shows the full list.
        result["suggestions"] = result["suggestions"][:15]
        return result | {"manage_url": "/inventory"}
    except ERRORS as exc:
        return failure(exc)


@tool(
    name="list_inventory_suggestions",
    description="Manager only: list saved inventory suggestions (default pending), highest priority first.",
)
async def list_inventory_suggestions(
    status: Annotated[str, Field(description="pending, accepted, rejected, superseded or all")] = "pending",
    suggestion_type: Annotated[str, Field(description="restock, overstock or empty for both")] = "",
) -> dict:
    if error := denied():
        return error
    async with get_pool().acquire() as conn:
        return await list_suggestions(
            conn,
            status=None if status == "all" else status,
            suggestion_type=suggestion_type or None,
            limit=20,
        )


@tool(
    name="list_low_stock_inventory",
    description="Manager only: current live inventory rows at or below their reorder threshold, per warehouse.",
)
async def list_low_stock_inventory(
    category: Annotated[str, Field(description="Exact category, empty for all")] = "",
) -> dict:
    if error := denied():
        return error
    async with get_pool().acquire() as conn:
        return await list_inventory(
            conn, category=category or None, low_stock_only=True, include_inactive=False, limit=50
        )


async def _propose(action_type: str, payload: dict) -> dict:
    if error := denied():
        return error
    try:
        return await actions.propose(
            get_pool(), current_user_email.get(), current_session_id.get(), action_type, payload
        )
    except ERRORS as exc:
        return failure(exc)


@tool(
    name="propose_stock_adjustment",
    description=(
        "Manager only: PREVIEW a manual stock change (receipt, issue, or stock count) for one product in one "
        "warehouse. Nothing changes until the user confirms in their next message."
    ),
)
async def propose_stock_adjustment(
    product_id: Annotated[str, Field(description="Product UUID")],
    warehouse_id: Annotated[str, Field(description="Warehouse name as the user said it (e.g. 'Central') or UUID")],
    kind: Annotated[
        Literal["manual_receipt", "manual_issue", "stock_count_adjustment"],
        Field(description="manual_receipt adds, manual_issue removes, stock_count_adjustment sets the counted total"),
    ],
    quantity: Annotated[int, Field(description="Units to add/remove, or the counted total for a stock count")],
    reason: Annotated[str, Field(description="Why the stock is changing, as stated by the user")],
) -> dict:
    return await _propose(
        "stock_adjustment",
        {
            "product_id": product_id,
            "warehouse_id": warehouse_id,
            "adjustment": {"kind": kind, "quantity": quantity, "reason": reason},
        },
    )


@tool(
    name="propose_suggestion_decision",
    description=(
        "Manager only: PREVIEW accepting or rejecting a pending inventory suggestion. Accepting a restock will "
        "receive stock; accepting overstock records the decision only. Requires the user's confirmation."
    ),
)
async def propose_suggestion_decision(
    suggestion_id: Annotated[str, Field(description="Suggestion UUID")],
    decision: Annotated[Literal["accept", "reject"], Field(description="accept or reject")],
    quantity: Annotated[int, Field(description="Override restock quantity; 0 keeps the suggested quantity")] = 0,
    warehouse_id: Annotated[str, Field(description="Override receiving warehouse name or UUID; empty keeps it")] = "",
    note: Annotated[str, Field(description="Reason or note from the user")] = "",
) -> dict:
    return await _propose(
        "suggestion_decision",
        {
            "suggestion_id": suggestion_id,
            "decision": {
                "decision": decision,
                "quantity": quantity or None,
                "warehouse_id": warehouse_id or None,
                "note": note,
            },
        },
    )


@tool(
    name="propose_product_status",
    description="Manager only: PREVIEW listing (is_active=true) or delisting a product. Requires confirmation.",
)
async def propose_product_status(
    product_id: Annotated[str, Field(description="Product UUID")],
    is_active: Annotated[bool, Field(description="true to list, false to delist")],
) -> dict:
    return await _propose("product_status", {"product_id": product_id, "is_active": is_active})


@tool(
    name="confirm_inventory_action",
    description=(
        "Manager only: execute a previously proposed inventory action AFTER the user explicitly confirmed it in "
        "their latest message. The server verifies that confirmation; if it is missing, nothing changes."
    ),
)
async def confirm_inventory_action(
    action_id: Annotated[str, Field(description="action_id from the propose_* result; empty = latest pending")] = "",
) -> dict:
    if error := denied():
        return error
    try:
        return await actions.confirm(
            get_pool(), current_user_email.get(), current_session_id.get(), UUID(action_id) if action_id else None
        )
    except ERRORS as exc:
        return failure(exc)


@tool(
    name="cancel_inventory_action",
    description="Manager only: cancel a proposed inventory action the user declined. Nothing changes.",
)
async def cancel_inventory_action(
    action_id: Annotated[str, Field(description="action_id from the propose_* result; empty = latest pending")] = "",
) -> dict:
    if error := denied():
        return error
    try:
        return await actions.cancel(
            get_pool(), current_user_email.get(), current_session_id.get(), UUID(action_id) if action_id else None
        )
    except ERRORS as exc:
        return failure(exc)


INVENTORY_MANAGEMENT_TOOLS = [
    generate_inventory_suggestions,
    list_inventory_suggestions,
    list_low_stock_inventory,
    propose_stock_adjustment,
    propose_suggestion_decision,
    propose_product_status,
    confirm_inventory_action,
    cancel_inventory_action,
]
