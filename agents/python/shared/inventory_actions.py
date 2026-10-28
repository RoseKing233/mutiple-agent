"""Two-step chat writes: propose (no change) -> confirm (server-verified user consent).

The LLM can call ``confirm`` at any time, so consent is decided here, not by the model:
the user's newest message in the SAME conversation must be newer than the proposal and
must be an explicit, unnegated agreement. Execution reuses the HTTP service functions.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg

from shared.inventory_management import (
    StockAdjustment,
    adjust_stock,
    manager_id,
    resolve_warehouse,
    set_product_status,
)
from shared.inventory_suggestions import Decision, decide_suggestion

ACTION_TTL = timedelta(minutes=15)

_AGREE = re.compile(
    r"(确认|同意|执行|可以|好的|好|是的|没问题|\byes\b|\by\b|\bconfirm(?:ed)?\b|\bapprove[d]?\b|\bok(?:ay)?\b"
    r"|\bgo ahead\b|\bproceed\b|\bdo it\b|\bsure\b)",
    re.IGNORECASE,
)
_NEGATE = re.compile(
    r"(不|别|取消|算了|等等|先不|\bno\b|\bnot\b|\bdon'?t\b|\bcancel\b|\bstop\b|\bwait\b|\bnever\s?mind\b)",
    re.IGNORECASE,
)


def is_explicit_consent(text: str) -> bool:
    """Short, positive replies only; anything ambiguous or negated is not consent."""
    text = text.strip()
    return 0 < len(text) <= 60 and bool(_AGREE.search(text)) and not _NEGATE.search(text)


def _decode(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


async def _product_name(conn: asyncpg.Connection, product_id: uuid.UUID) -> str:
    name = await conn.fetchval("SELECT name FROM products WHERE id=$1", product_id)
    if name is None:
        raise LookupError("Product not found")
    return name


async def build_preview(conn: asyncpg.Connection, action_type: str, payload: dict) -> dict:
    """Validate the proposal now so the user confirms something that can actually run."""
    if action_type == "stock_adjustment":
        pid, wid = uuid.UUID(payload["product_id"]), uuid.UUID(payload["warehouse_id"])
        row = await conn.fetchrow(
            """SELECT wi.quantity, w.name FROM warehouse_inventory wi JOIN warehouses w ON w.id=wi.warehouse_id
               WHERE wi.product_id=$1 AND wi.warehouse_id=$2""",
            pid,
            wid,
        )
        if row is None:
            raise LookupError("Inventory row not found for this product and warehouse")
        adj = StockAdjustment.model_validate(payload["adjustment"])
        after = {
            "manual_receipt": row["quantity"] + adj.quantity,
            "manual_issue": row["quantity"] - adj.quantity,
            "stock_count_adjustment": adj.quantity,
        }[adj.kind]
        if after < 0:
            raise ValueError(f"Insufficient inventory: {row['quantity']} available")
        return {
            "summary": f"{adj.kind.replace('_', ' ')} for {await _product_name(conn, pid)} at {row['name']}",
            "current_quantity": row["quantity"],
            "quantity_after": after,
            "reason": adj.reason,
        }
    if action_type == "suggestion_decision":
        s = await conn.fetchrow(
            """SELECT s.*, p.name AS product_name, w.name AS warehouse_name FROM inventory_suggestions s
               JOIN products p ON p.id=s.product_id LEFT JOIN warehouses w ON w.id=s.warehouse_id WHERE s.id=$1""",
            uuid.UUID(payload["suggestion_id"]),
        )
        if s is None:
            raise LookupError("Suggestion not found")
        if s["status"] != "pending":
            raise ValueError(f"Suggestion is already {s['status']}")
        d = Decision.model_validate(payload["decision"])
        warehouse = s["warehouse_name"]
        if d.warehouse_id:
            warehouse = await conn.fetchval("SELECT name FROM warehouses WHERE id=$1 AND is_active", d.warehouse_id)
            if warehouse is None:
                raise ValueError("Warehouse not found or inactive")
        changes_stock = d.decision == "accept" and s["suggestion_type"] == "restock"
        return {
            "summary": f"{d.decision} {s['suggestion_type']} suggestion for {s['product_name']}",
            "stock_will_change": changes_stock,
            "quantity": (d.quantity or s["suggested_quantity"]) if changes_stock else None,
            "warehouse": warehouse if changes_stock else None,
            "note": d.note,
        }
    if action_type == "product_status":
        pid = uuid.UUID(payload["product_id"])
        return {
            "summary": f"{'list' if payload['is_active'] else 'delist'} {await _product_name(conn, pid)}",
            "is_active_after": payload["is_active"],
        }
    raise ValueError("Unknown action type")


async def propose(pool: asyncpg.Pool, email: str, conversation_id: str, action_type: str, payload: dict) -> dict:
    if not conversation_id:
        raise PermissionError("Chat write actions require an active conversation")
    async with pool.acquire() as conn:
        owner = await manager_id(conn, email)
        # Store resolved UUIDs so the confirmed action runs exactly what was previewed.
        if action_type == "stock_adjustment":
            payload["warehouse_id"] = str(await resolve_warehouse(conn, payload["warehouse_id"]))
        if action_type == "suggestion_decision" and payload["decision"].get("warehouse_id"):
            payload["decision"]["warehouse_id"] = str(
                await resolve_warehouse(conn, payload["decision"]["warehouse_id"])
            )
        preview = await build_preview(conn, action_type, payload)
        row = await conn.fetchrow(
            """INSERT INTO inventory_action_requests(owner_id, conversation_id, action_type, payload, preview,
                                                     expires_at)
               VALUES($1,$2,$3,$4::jsonb,$5::jsonb, clock_timestamp() + $6::interval) RETURNING id, expires_at""",
            owner,
            uuid.UUID(conversation_id),
            action_type,
            json.dumps(payload, default=str),
            json.dumps(preview, default=str),
            ACTION_TTL,
        )
    return {
        "status": "awaiting_user_confirmation",
        "action_id": str(row["id"]),
        "preview": preview,
        "expires_at": row["expires_at"].isoformat(),
        "instruction": (
            "Nothing has changed yet. Show this preview and ask the user to reply 'confirm' (确认) to execute "
            "or 'cancel' (取消). Only call confirm_inventory_action after the user replies."
        ),
    }


async def _latest_user_message(conn: asyncpg.Connection, conversation_id: uuid.UUID) -> asyncpg.Record | None:
    return await conn.fetchrow(
        """SELECT content, created_at FROM messages WHERE conversation_id=$1 AND role='user'
           ORDER BY created_at DESC LIMIT 1""",
        conversation_id,
    )


async def _execute(conn: asyncpg.Connection, action_type: str, payload: dict, email: str) -> dict:
    if action_type == "stock_adjustment":
        return await adjust_stock(
            conn,
            uuid.UUID(payload["product_id"]),
            uuid.UUID(payload["warehouse_id"]),
            StockAdjustment.model_validate(payload["adjustment"]),
            email,
        )
    if action_type == "suggestion_decision":
        return await decide_suggestion(
            conn, uuid.UUID(payload["suggestion_id"]), Decision.model_validate(payload["decision"]), email
        )
    return await set_product_status(conn, uuid.UUID(payload["product_id"]), payload["is_active"])


async def _locked_action(
    conn: asyncpg.Connection, owner: uuid.UUID, conversation_id: str, action_id: uuid.UUID | None
) -> asyncpg.Record:
    """By ID, or the newest pending action in this conversation.

    The orchestrator may paraphrase the specialist's reply and drop the ID, so the next turn
    cannot always quote it. Falling back to the conversation's newest pending action is safe:
    consent is still verified against the user's own message below.
    """
    if action_id:
        action = await conn.fetchrow(
            "SELECT * FROM inventory_action_requests WHERE id=$1 AND owner_id=$2 FOR UPDATE", action_id, owner
        )
    else:
        action = await conn.fetchrow(
            """SELECT * FROM inventory_action_requests
               WHERE owner_id=$1 AND conversation_id=$2 AND status='pending'
               ORDER BY created_at DESC LIMIT 1 FOR UPDATE""",
            owner,
            uuid.UUID(conversation_id),
        )
    if action is None or str(action["conversation_id"]) != conversation_id:
        raise LookupError("No matching action in this conversation")
    return action


async def confirm(pool: asyncpg.Pool, email: str, conversation_id: str, action_id: uuid.UUID | None = None) -> dict:
    if not conversation_id:
        raise PermissionError("Chat write actions require an active conversation")
    async with pool.acquire() as conn:
        owner = await manager_id(conn, email)
        async with conn.transaction():
            action = await _locked_action(conn, owner, conversation_id, action_id)
            action_id = action["id"]
            if action["status"] != "pending":
                return {"status": action["status"], "action_id": str(action_id), "result": _decode(action["result"])}
            if action["expires_at"] < datetime.now(UTC):
                await conn.execute(
                    "UPDATE inventory_action_requests SET status='cancelled', resolved_at=NOW(), "
                    'result=\'{"reason":"expired"}\' WHERE id=$1',
                    action_id,
                )
                return {"status": "expired", "action_id": str(action_id), "message": "Propose the action again."}
            latest = await _latest_user_message(conn, action["conversation_id"])
            if latest is None or latest["created_at"] <= action["created_at"]:
                return {
                    "status": "awaiting_user_confirmation",
                    "action_id": str(action_id),
                    "message": "The user has not replied since the preview. Ask them to confirm first.",
                }
            if not is_explicit_consent(latest["content"]):
                return {
                    "status": "awaiting_user_confirmation",
                    "action_id": str(action_id),
                    "message": "The user's latest reply is not an explicit confirmation. Nothing was changed.",
                }
            payload = _decode(action["payload"])
            try:
                async with conn.transaction():  # savepoint: a failed execution still records the outcome
                    result = await _execute(conn, action["action_type"], payload, email)
                status = "executed"
            except (ValueError, LookupError, PermissionError) as exc:
                result, status = {"error": str(exc)}, "failed"
            await conn.execute(
                "UPDATE inventory_action_requests SET status=$2, result=$3::jsonb, resolved_at=NOW() WHERE id=$1",
                action_id,
                status,
                json.dumps(result, default=str),
            )
    return {"status": status, "action_id": str(action_id), "result": result}


async def cancel(pool: asyncpg.Pool, email: str, conversation_id: str, action_id: uuid.UUID | None = None) -> dict:
    if not conversation_id:
        raise PermissionError("Chat write actions require an active conversation")
    async with pool.acquire() as conn:
        owner = await manager_id(conn, email)
        async with conn.transaction():
            action = await _locked_action(conn, owner, conversation_id, action_id)
            if action["status"] != "pending":
                raise LookupError(f"Action is already {action['status']}")
            await conn.execute(
                "UPDATE inventory_action_requests SET status='cancelled', resolved_at=NOW() WHERE id=$1", action["id"]
            )
    return {"status": "cancelled", "action_id": str(action["id"]), "stock_changed": False}
