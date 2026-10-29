"""Shared return tools — eligibility checks, returns, refunds."""

from __future__ import annotations

from typing import Annotated

from agent_framework import tool
from pydantic import Field, ValidationError

from shared.context import current_user_email
from shared.db import get_pool
from shared.guardrails.roles import requires_role
from shared.idempotency import idempotent
from shared.return_policy import evaluate_return_window
from shared.tool_inputs import (
    InitiateReturnInput,
    ProcessRefundInput,
    validation_error_payload,
)


@tool(
    name="check_return_eligibility",
    description="Check whether a delivered order is within the 30-day return window.",
)
async def check_return_eligibility(
    order_id: Annotated[str, Field(description="UUID of the order to check")],
) -> dict:
    email = current_user_email.get()
    if not email:
        return {"error": "No user context available"}

    pool = get_pool()
    async with pool.acquire() as conn:
        order = await conn.fetchrow(
            """SELECT o.id, o.status, o.total, o.created_at
               FROM orders o
               JOIN users u ON o.user_id = u.id
               WHERE o.id = $1 AND u.email = $2""",
            order_id, email,
        )
        if not order:
            return {"error": f"Order not found or access denied: {order_id}"}

        # Check if already returned
        existing_return = await conn.fetchrow(
            "SELECT id, status FROM returns WHERE order_id = $1",
            order_id,
        )
        if existing_return:
            return {
                "eligible": False,
                "order_id": str(order["id"]),
                "reason": f"A return already exists for this order (status: {existing_return['status']}).",
                "return_id": str(existing_return["id"]),
            }

        if order["status"] != "delivered":
            return {
                "eligible": False,
                "order_id": str(order["id"]),
                "status": order["status"],
                "reason": f"Order must be in 'delivered' status to initiate a return. Current status: {order['status']}.",
            }

        # Older orders without a delivery event use their creation time rather
        # than receiving a fresh, unconditional 30-day window.
        delivered_entry = await conn.fetchrow(
            """SELECT timestamp FROM order_status_history
               WHERE order_id = $1 AND status = 'delivered'
               ORDER BY timestamp DESC LIMIT 1""",
            order_id,
        )

        window = evaluate_return_window(
            order_created_at=order["created_at"],
            delivered_at=delivered_entry["timestamp"] if delivered_entry else None,
        )
        if not window["eligible"]:
            reference_time = window["reference_time"]
            date_label = "order date" if window["used_order_date_fallback"] else "delivery date"
            return {
                "eligible": False,
                "order_id": str(order["id"]),
                "reason": (
                    f"Return window expired. The {date_label} is more than 30 days ago "
                    "(30-day limit)."
                ),
                "delivered_at": reference_time.isoformat(),
            }

        return {
            "eligible": True,
            "order_id": str(order["id"]),
            "total": float(order["total"]),
            "days_remaining": window["days_remaining"],
            "delivery_date_estimated": window["used_order_date_fallback"],
            "message": (
                f"Order is eligible for return. {window['days_remaining']} days remaining in the return window."
            ),
        }


@tool(
    name="initiate_return",
    description="Submit a return request for an eligible delivered order. A demo label is available after approval.",
    approval_mode="always_require",
)
@idempotent("initiate_return")
async def initiate_return(
    order_id: Annotated[str, Field(description="UUID of the order to return")],
    reason: Annotated[str, Field(description="Reason for the return")],
    refund_method: Annotated[str, Field(description="Refund method: 'original_payment' or 'store_credit'")] = "original_payment",
) -> dict:
    email = current_user_email.get()
    if not email:
        return {"error": "No user context available"}

    try:
        validated = InitiateReturnInput(
            order_id=order_id, reason=reason, refund_method=refund_method
        )
    except ValidationError as exc:
        return validation_error_payload("initiate_return", exc)
    order_id = str(validated.order_id)
    reason = validated.reason
    refund_method = validated.refund_method

    pool = get_pool()
    async with pool.acquire() as conn:
        # Lock the order row + the existence-check on `returns` together
        # so two concurrent agents can't both observe "no return yet"
        # and create one each.
        async with conn.transaction():
            order = await conn.fetchrow(
                """SELECT o.id, o.user_id, o.status, o.total, o.created_at
                   FROM orders o
                   JOIN users u ON o.user_id = u.id
                   WHERE o.id = $1 AND u.email = $2
                   FOR UPDATE OF o""",
                order_id, email,
            )
            if not order:
                return {"error": f"Order not found or access denied: {order_id}"}

            if order["status"] != "delivered":
                return {"error": f"Cannot return order in '{order['status']}' status. Only delivered orders can be returned."}

            delivered_entry = await conn.fetchrow(
                """SELECT timestamp FROM order_status_history
                   WHERE order_id = $1 AND status = 'delivered'
                   ORDER BY timestamp DESC LIMIT 1""",
                order_id,
            )
            window = evaluate_return_window(
                order_created_at=order["created_at"],
                delivered_at=delivered_entry["timestamp"] if delivered_entry else None,
            )
            if not window["eligible"]:
                return {
                    "error": (
                        "Return window expired. Returns must be requested within 30 days "
                        "of delivery (or order date when delivery history is unavailable)."
                    ),
                    "eligible": False,
                }

            existing = await conn.fetchrow(
                "SELECT id FROM returns WHERE order_id = $1",
                order_id,
            )
            if existing:
                return {"error": "A return has already been initiated for this order.", "return_id": str(existing["id"])}

            return_id = await conn.fetchval(
                """INSERT INTO returns (order_id, user_id, reason, status, return_label_url, refund_method, refund_amount)
                   VALUES ($1, $2, $3, 'requested', NULL, $4, $5)
                   RETURNING id""",
                order_id, order["user_id"], reason, refund_method, order["total"],
            )
            await conn.execute(
                "UPDATE orders SET status = 'returned' WHERE id = $1",
                order_id,
            )
            await conn.execute(
                """INSERT INTO order_status_history (order_id, status, notes)
                   VALUES ($1, 'returned', $2)""",
                order_id, f"Return initiated: {reason}",
            )

        return {
            "return_id": str(return_id),
            "order_id": str(order["id"]),
            "status": "requested",
            "reason": reason,
            "refund_method": refund_method,
            "refund_amount": float(order["total"]),
            "return_label_url": None,
            "message": (
                "Return request submitted. The label becomes available after approval. "
                "After the item is received, an admin can mark the demo refund complete; "
                "no real payment will be transferred."
            ),
        }


@tool(
    name="process_refund",
    description="Mark a refund complete after the returned item is received. This demo does not transfer money.",
    approval_mode="always_require",
)
@idempotent("process_refund", cache_result_fn=lambda result: "error" not in result)
@requires_role("customer", "seller", "admin")
async def process_refund(
    return_id: Annotated[str, Field(description="UUID of the return to process refund for")],
) -> dict:
    email = current_user_email.get()
    if not email:
        return {"error": "No user context available"}

    try:
        validated = ProcessRefundInput(return_id=return_id)
    except ValidationError as exc:
        return validation_error_payload("process_refund", exc)
    return_id = str(validated.return_id)

    pool = get_pool()
    async with pool.acquire() as conn:
        # Lock the return row before re-checking status. Without this a
        # double-click on "issue refund" can fund the customer twice.
        async with conn.transaction():
            ret = await conn.fetchrow(
                """SELECT r.id, r.order_id, r.status, r.refund_method, r.refund_amount
                   FROM returns r
                   JOIN users u ON r.user_id = u.id
                   WHERE r.id = $1 AND u.email = $2
                   FOR UPDATE OF r""",
                return_id, email,
            )
            if not ret:
                return {"error": f"Return not found or access denied: {return_id}"}

            if ret["status"] == "refunded":
                return {"error": "This return has already been refunded.", "return_id": str(ret["id"])}

            if ret["status"] != "received":
                return {
                    "error": (
                        f"Cannot refund a return in '{ret['status']}' status. "
                        "The returned item must be marked received first."
                    ),
                    "return_id": str(ret["id"]),
                    "current_status": ret["status"],
                }

            await conn.execute(
                "UPDATE returns SET status = 'refunded', resolved_at = NOW() WHERE id = $1",
                return_id,
            )
            await conn.execute(
                """INSERT INTO order_status_history (order_id, status, notes)
                   VALUES ($1, 'returned', 'Demo refund marked complete after return receipt')""",
                ret["order_id"],
            )

        refund_amount = float(ret["refund_amount"]) if ret["refund_amount"] else 0
        refund_method = ret["refund_method"] or "original_payment"

        return {
            "return_id": str(ret["id"]),
            "order_id": str(ret["order_id"]),
            "status": "refunded",
            "refund_method": refund_method,
            "refund_amount": refund_amount,
            "refund_mode": "simulated",
            "message": (
                f"Demo refund of ${refund_amount:.2f} marked complete via "
                f"{refund_method.replace('_', ' ')}. No payment provider is connected, "
                "so no money was transferred."
            ),
        }


@tool(name="get_return_status", description="Get the current return processing status for an order.")
async def get_return_status(
    order_id: Annotated[str, Field(description="UUID of the order to check return status for")],
) -> dict:
    email = current_user_email.get()
    if not email:
        return {"error": "No user context available"}

    pool = get_pool()
    async with pool.acquire() as conn:
        # Verify order ownership
        order_check = await conn.fetchrow(
            """SELECT o.id FROM orders o
               JOIN users u ON o.user_id = u.id
               WHERE o.id = $1 AND u.email = $2""",
            order_id, email,
        )
        if not order_check:
            return {"error": f"Order not found or access denied: {order_id}"}

        ret = await conn.fetchrow(
            """SELECT id, reason, status, return_label_url, refund_method,
                      refund_amount, created_at, resolved_at
               FROM returns
               WHERE order_id = $1""",
            order_id,
        )
        if not ret:
            return {
                "order_id": order_id,
                "has_return": False,
                "message": "No return found for this order.",
            }

        return {
            "return_id": str(ret["id"]),
            "order_id": order_id,
            "has_return": True,
            "status": ret["status"],
            "reason": ret["reason"],
            "refund_method": ret["refund_method"],
            "refund_amount": float(ret["refund_amount"]) if ret["refund_amount"] else None,
            "return_label_url": ret["return_label_url"],
            "created_at": ret["created_at"].isoformat(),
            "resolved_at": ret["resolved_at"].isoformat() if ret["resolved_at"] else None,
        }
