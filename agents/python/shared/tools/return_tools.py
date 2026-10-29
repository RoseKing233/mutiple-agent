"""Shared return tools — eligibility checks, returns, refunds."""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import uuid4

from agent_framework import tool
from pydantic import Field, ValidationError

from shared.context import current_session_id, current_user_email
from shared.db import get_pool
from shared.guardrails.roles import requires_role
from shared.idempotency import idempotent
from shared.return_policy import evaluate_return_window
from shared.tool_inputs import (
    InitiateReturnInput,
    ProcessRefundInput,
    validation_error_payload,
)

logger = logging.getLogger(__name__)


@tool(
    name="check_return_eligibility",
    description="Check whether a delivered order is within the 30-day return request window.",
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
            order_id,
            email,
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
                "reason": (
                    f"Order must be in 'delivered' status to initiate a return. Current status: {order['status']}."
                ),
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
                "reason": (f"Return window expired. The {date_label} is more than 30 days ago (30-day limit)."),
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
    description=(
        "Automatically approve an eligible delivered-order return requested within 30 days and provide a return label. "
        "Choose the preferred refund method; after the item is received, "
        "the system submits a refund for admin approval."
    ),
)
@idempotent("initiate_return", cache_result_fn=lambda result: "return_id" in result)
async def initiate_return(
    order_id: Annotated[str, Field(description="UUID of the order to return")],
    reason: Annotated[str, Field(description="Reason for the return")],
    refund_method: Annotated[
        str, Field(description="Preferred refund method: 'original_payment' or 'store_credit'")
    ] = "original_payment",
) -> dict:
    email = current_user_email.get()
    if not email:
        return {"error": "No user context available"}

    try:
        validated = InitiateReturnInput(order_id=order_id, reason=reason, refund_method=refund_method)
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
                order_id,
                email,
            )
            if not order:
                return {"error": f"Order not found or access denied: {order_id}"}

            if order["status"] != "delivered":
                return {
                    "error": (
                        f"Cannot return order in '{order['status']}' status. Only delivered orders can be returned."
                    )
                }

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
                return {
                    "error": "A return has already been initiated for this order.",
                    "return_id": str(existing["id"]),
                }

            label_token = uuid4().hex[:12]
            label_url = f"/api/returns/{label_token}/label"
            return_id = await conn.fetchval(
                """INSERT INTO returns
                       (order_id, user_id, reason, status, return_label_url, refund_method, refund_amount)
                   VALUES ($1, $2, $3, 'approved', $4, $5, $6)
                   RETURNING id""",
                order_id,
                order["user_id"],
                reason,
                label_url,
                refund_method,
                order["total"],
            )
            await conn.execute(
                "UPDATE orders SET status = 'returned' WHERE id = $1",
                order_id,
            )
            await conn.execute(
                """INSERT INTO order_status_history (order_id, status, notes)
                   VALUES ($1, 'approved', $2)""",
                order_id,
                f"Return initiated and approved: {reason}",
            )

        return {
            "return_id": str(return_id),
            "order_id": str(order["id"]),
            "status": "approved",
            "reason": reason,
            "refund_method": refund_method,
            "return_label_url": label_url,
            "message": (
                "Your eligible return has been approved automatically and the demo label is ready. "
                "After the returned item is received, a refund request will be sent for admin approval. "
                "No refund has been processed yet."
            ),
        }


@tool(
    name="process_refund",
    description=(
        "Submit a refund for admin approval only after the returned item is received. "
        "A qualifying return is required; this tool never refunds an order without a received return. "
        "No payment provider is connected; this records the request without transferring funds."
    ),
)
# Retries recheck the return status and reuse any pending approval below.
@idempotent("process_refund", cache_result_fn=lambda _result: False)
@requires_role("customer", "seller", "admin")
async def process_refund(
    return_id: Annotated[str, Field(description="UUID of the return to process refund for")],
    refund_method: Annotated[
        str, Field(description="Requested refund method: 'original_payment' or 'store_credit'")
    ] = "original_payment",
) -> dict:
    email = current_user_email.get()
    if not email:
        return {"error": "No user context available"}

    try:
        validated = ProcessRefundInput(return_id=return_id, refund_method=refund_method)
    except ValidationError as exc:
        return validation_error_payload("process_refund", exc)
    return_id = str(validated.return_id)
    refund_method = validated.refund_method

    pool = get_pool()
    review_reason = "The returned item has been received; the refund is awaiting admin approval."
    async with pool.acquire() as conn:
        # Lock the return row before checking receipt status and preparing approval.
        async with conn.transaction():
            ret = await conn.fetchrow(
                """SELECT r.id, r.order_id, r.user_id, r.status, r.refund_method, r.refund_amount,
                          o.created_at, o.total
                   FROM returns r
                   JOIN users u ON r.user_id = u.id
                   JOIN orders o ON o.id = r.order_id
                   WHERE r.id = $1 AND u.email = $2
                   FOR UPDATE OF r""",
                return_id,
                email,
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

    from shared.hitl import _create_hitl_request

    existing_request = await pool.fetchrow(
        """SELECT id, tool_input
           FROM tool_approval_requests
           WHERE user_email = $1
             AND tool_name = 'process_refund'
             AND status IN ('pending', 'processing')
             AND tool_input->>'return_id' = $2
           ORDER BY created_at DESC
           LIMIT 1""",
        email,
        return_id,
    )
    if existing_request is None:
        try:
            request_id = await _create_hitl_request(
                user_email=email,
                session_id=current_session_id.get() or None,
                agent_name="order-management",
                tool_name="process_refund",
                tool_input={
                    "return_id": return_id,
                    "refund_method": refund_method,
                    "review_reason": review_reason,
                },
            )
        except Exception:
            logger.exception("refund.approval_request_failed user=%s return_id=%s", email, return_id)
            return {
                "error": (
                    f"{review_reason} The admin approval request could not be submitted right now; "
                    "no refund was processed. Please try again later."
                ),
                "no_changes": True,
            }
        await pool.execute(
            """UPDATE returns SET refund_method = $2, refund_amount = COALESCE(refund_amount, $3)
               WHERE id = $1 AND status = 'received'""",
            return_id,
            refund_method,
            ret["total"],
        )
    else:
        request_id = existing_request["id"]
        stored_tool_input = existing_request["tool_input"]
        if isinstance(stored_tool_input, str):
            import json

            stored_tool_input = json.loads(stored_tool_input)
        refund_method = stored_tool_input.get("refund_method", refund_method)
    return {
        "status": "pending_approval",
        "return_id": str(ret["id"]),
        "order_id": str(ret["order_id"]),
        "request_id": str(request_id),
        "refund_method": refund_method,
        "refund_amount": float(ret["refund_amount"] or ret["total"]),
        "reason": review_reason,
        "message": f"{review_reason} No refund has been processed.",
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
            order_id,
            email,
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

        refund_approval_status = None
        if ret["status"] == "received":
            refund_approval_status = await conn.fetchval(
                """SELECT status
                   FROM tool_approval_requests
                   WHERE user_email = $1
                     AND tool_name = 'process_refund'
                     AND tool_input->>'return_id' = $2
                   ORDER BY created_at DESC
                   LIMIT 1""",
                email,
                str(ret["id"]),
            )
        status_messages = {
            "approved": "The return is approved automatically. Download the demo label and mark it shipped when ready.",
            "shipped_back": "The return is marked shipped and is waiting for simulated receipt confirmation.",
            "refunded": "The refund is complete in the order record. No payment provider is connected.",
            "denied": "The return was denied. No refund was processed.",
        }
        if refund_approval_status == "denied":
            status_message = "The refund request was denied by an admin. No refund was processed."
        elif refund_approval_status == "executed":
            status_message = "The admin approved the refund. It is marked complete in the order record."
        elif ret["status"] == "received" and refund_approval_status in {"pending", "processing"}:
            status_message = "The return was received. Its refund is awaiting admin approval; no second request is needed."
        elif ret["status"] == "received":
            status_message = "The return was received, but its refund has not been approved."
        else:
            status_message = status_messages.get(ret["status"], "The return is being processed.")
        return {
            "return_id": str(ret["id"]),
            "order_id": order_id,
            "has_return": True,
            "status": ret["status"],
            "refund_approval_status": refund_approval_status,
            "message": status_message,
            "reason": ret["reason"],
            "refund_method": ret["refund_method"],
            "refund_amount": float(ret["refund_amount"]) if ret["refund_amount"] else None,
            "return_label_url": ret["return_label_url"],
            "created_at": ret["created_at"].isoformat(),
            "resolved_at": ret["resolved_at"].isoformat() if ret["resolved_at"] else None,
        }
