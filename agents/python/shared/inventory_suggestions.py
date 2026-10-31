"""Restock / overstock suggestions: code computes the numbers, an LLM only explains them.

Flow: forecast_report (Jingtong's engine) + live stock -> rule-based suggestions ->
optional LLM rationale (JSON-schema structured output, number-grounded) -> saved as
``pending``. Nothing changes stock until a manager accepts; accepting a restock records a
``restock_receipt`` through ``change_inventory``. Overstock acceptance records the decision only.
"""

from __future__ import annotations

import json
import logging
import math
import re
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

import asyncpg
from pydantic import BaseModel, ConfigDict, Field

from shared.forecasting.config import ForecastRequest
from shared.forecasting.service import forecast_report
from shared.inventory_ledger import change_inventory
from shared.llm_options import sampling_options
from shared.sales_analysis import serialize

logger = logging.getLogger(__name__)

# messages -> raw JSON text matching RATIONALE_SCHEMA
RationaleWriter = Callable[[list[dict[str, str]]], Awaitable[str]]

RATIONALE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "rationales": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"key": {"type": "string"}, "rationale": {"type": "string"}},
                "required": ["key", "rationale"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["rationales"],
    "additionalProperties": False,
}


class SuggestionRules(BaseModel):
    """Course-project defaults, not retail standards. Stored with every suggestion's evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    horizon: Literal[7, 14, 28] = 14
    urgent_days: int = Field(default=7, ge=1, le=28)
    target_cover_days: int = Field(default=30, ge=7, le=180)
    fallback_threshold_multiplier: int = Field(default=2, ge=1, le=10)


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    as_of: date | None = None
    category: str | None = Field(default=None, max_length=100)
    product_id: uuid.UUID | None = None
    rules: SuggestionRules = Field(default_factory=SuggestionRules)
    use_ai: bool = True


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Literal["accept", "reject"]
    quantity: int | None = Field(default=None, ge=1, le=100000)
    warehouse_id: uuid.UUID | None = None
    note: str = Field(default="", max_length=500)


# ── Rules (pure, unit-testable) ─────────────────────────────────────────────


def _depletion(live: int, units: list[float], as_of: date) -> tuple[str | None, int | None]:
    cumulative = 0.0
    for i, demand in enumerate(units):
        cumulative += demand
        if live > 0 and cumulative >= live:
            return str(as_of + timedelta(days=i + 1)), i + 1
    return None, None


def _pick_warehouse(rows: list[dict]) -> dict | None:
    active = [r for r in rows if r["warehouse_active"]]
    return min(active, key=lambda r: (r["quantity"] - r["reorder_threshold"], r["warehouse_name"]), default=None)


def compute_suggestions(
    report: dict, live_stock: dict[str, list[dict]], rules: SuggestionRules, as_of: date
) -> list[dict]:
    """``live_stock`` maps product_id -> inventory rows (warehouse_id/name/active, quantity, threshold)."""
    suggestions = []
    for product in report["products"]:
        pid = product["product_id"]
        rows = live_stock.get(pid, [])
        live = sum(r["quantity"] for r in rows)
        threshold = sum(r["reorder_threshold"] for r in rows if r["warehouse_active"])
        perf, forecast = product["performance"], product["forecast"]
        units = [r["units"] for r in forecast.get("series", [])] if forecast.get("available") else None
        forecast_units = round(sum(units), 2) if units is not None else None
        stockout_date, days_to_stockout = _depletion(live, units, as_of) if units else (None, None)
        base = {
            "product_id": pid,
            "product_name": product["name"],
            "category": product["category"],
        }
        evidence = {
            "live_stock": live,
            "reorder_threshold_total": threshold,
            "horizon_days": rules.horizon,
            "forecast_available": bool(forecast.get("available")),
            "forecast_units": forecast_units,
            "forecast_model": forecast.get("model"),
            "forecast_reliability": forecast.get("reliability"),
            "projected_stockout_date": stockout_date,
            "days_to_stockout": days_to_stockout,
            "trend": perf.get("trend"),
            "recent_units": perf.get("recent_units"),
            "comparison_days": perf.get("comparison_days"),
            "days_of_cover_at_cutoff": perf.get("days_of_cover"),
            "overstock_flag": perf.get("overstock"),
            "slow_moving_flag": perf.get("slow_moving"),
            "no_recent_sales": perf.get("no_recent_sales"),
            "cutoff": str(as_of),
        }
        needs_restock = live == 0 or days_to_stockout is not None or (threshold > 0 and live <= threshold)
        if needs_restock:
            if units is not None:
                quantity = math.ceil(forecast_units + threshold - live)
                basis = "forecast_plus_safety_stock"
            else:
                quantity = max(threshold * rules.fallback_threshold_multiplier - live, threshold)
                basis = "threshold_fallback_without_forecast"
            if quantity > 0:
                priority = (
                    "high"
                    if live == 0 or (days_to_stockout is not None and days_to_stockout <= rules.urgent_days)
                    else "medium"
                    if days_to_stockout is not None
                    else "low"
                )
                target = _pick_warehouse(rows)
                suggestions.append(
                    base
                    | {
                        "suggestion_type": "restock",
                        "priority": priority,
                        "suggested_quantity": quantity,
                        "warehouse_id": target["warehouse_id"] if target else None,
                        "warehouse_name": target["warehouse_name"] if target else None,
                        "evidence": evidence
                        | {
                            "quantity_basis": basis,
                            "safety_stock": threshold,
                            "urgent_days_rule": rules.urgent_days,
                            "confidence": "low" if units is None else forecast.get("reliability"),
                        },
                    }
                )
                continue
        if live > 0 and (perf.get("overstock") is True or perf.get("slow_moving") is True):
            width = perf.get("comparison_days") or 28
            daily = (perf.get("recent_units") or 0) / width
            target_stock = math.ceil(daily * rules.target_cover_days)
            excess = live - target_stock
            if excess > 0:
                cover = perf.get("days_of_cover")
                priority = (
                    "high"
                    if perf.get("no_recent_sales") or (cover is not None and cover > 4 * rules.target_cover_days)
                    else "medium"
                    if perf.get("overstock")
                    else "low"
                )
                suggestions.append(
                    base
                    | {
                        "suggestion_type": "overstock",
                        "priority": priority,
                        "suggested_quantity": excess,
                        "warehouse_id": None,
                        "warehouse_name": None,
                        "evidence": evidence
                        | {
                            "average_daily_units": round(daily, 2),
                            "target_cover_days": rules.target_cover_days,
                            "target_stock": target_stock,
                            "excess_units": excess,
                            "recommended_actions": ["promotion_or_markdown", "pause_replenishment"],
                        },
                    }
                )
    order = {"high": 0, "medium": 1, "low": 2}
    suggestions.sort(key=lambda s: (order[s["priority"]], s["suggestion_type"], s["product_name"]))
    return suggestions


def rule_rationale(s: dict) -> str:
    e = s["evidence"]
    if s["suggestion_type"] == "restock":
        if e["live_stock"] == 0:
            situation = "is out of stock now"
        elif e["projected_stockout_date"]:
            situation = (
                f"has {e['live_stock']} units and is forecast to run out on {e['projected_stockout_date']} "
                f"({e['days_to_stockout']} days)"
            )
        else:
            situation = (
                f"has {e['live_stock']} units, at or below its reorder threshold of {e['reorder_threshold_total']}"
            )
        if e["quantity_basis"] == "forecast_plus_safety_stock":
            basis = (
                f"Forecast demand over {e['horizon_days']} days is {e['forecast_units']} units; adding safety stock "
                f"of {e['safety_stock']} gives {s['suggested_quantity']} units to order"
            )
        else:
            basis = (
                f"No reliable forecast is available, so the quantity ({s['suggested_quantity']}) restores stock "
                "to a multiple of the reorder threshold; treat it as low confidence"
            )
        return f"{s['product_name']} {situation}. {basis}."
    reason = (
        "has no recent sales"
        if e["no_recent_sales"]
        else f"sold {e['recent_units']:g} units in {e['comparison_days']} days"
    )
    return (
        f"{s['product_name']} holds {e['live_stock']} units but {reason}. About {e['target_stock']} units cover "
        f"{e['target_cover_days']} days, so {e['excess_units']} units are excess. Consider a promotion and pause "
        "replenishment."
    )


# ── AI rationale with structured output and number grounding ───────────────

_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")


def _allowed_values(value: Any, numbers: set[float], dates: set[str]) -> None:
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)):
        numbers.add(float(value))
    elif isinstance(value, str) and _DATE.fullmatch(value):
        dates.add(value)
    elif isinstance(value, dict):
        for item in value.values():
            _allowed_values(item, numbers, dates)
    elif isinstance(value, list):
        for item in value:
            _allowed_values(item, numbers, dates)


def grounded(text: str, suggestion: dict) -> bool:
    """Every number/date in the text must come from the suggestion's own evidence.

    Names are removed first: "Sony WH-1000XM5" or "Levi's 501" are not claimed figures.
    """
    numbers: set[float] = set()
    dates: set[str] = set()
    _allowed_values({"q": suggestion["suggested_quantity"], **suggestion["evidence"]}, numbers, dates)
    for name in (suggestion.get("product_name"), suggestion.get("warehouse_name")):
        if name:
            text = re.sub(re.escape(name), " ", text, flags=re.IGNORECASE)
    for found in _DATE.findall(text):
        if found not in dates:
            return False
    stripped = _DATE.sub(" ", text)
    for token in _NUMBER.findall(stripped):
        value = float(token)
        if not any(abs(value - allowed) <= 0.51 or math.isclose(value, allowed, rel_tol=0.01) for allowed in numbers):
            return False
    return True


def rationale_messages(suggestions: list[dict]) -> list[dict[str, str]]:
    items = [
        {
            "key": str(i),
            "product": s["product_name"],
            "type": s["suggestion_type"],
            "priority": s["priority"],
            "suggested_quantity": s["suggested_quantity"],
            "warehouse": s["warehouse_name"],
            "evidence": s["evidence"],
        }
        for i, s in enumerate(suggestions)
    ]
    return [
        {
            "role": "system",
            "content": (
                "You explain inventory suggestions to a store manager. The quantities and evidence were computed "
                "by code and are authoritative. For each item write 1-3 plain English sentences explaining why the "
                "suggestion was made and what the manager should check. Use ONLY numbers and dates that appear in "
                "that item's evidence or suggested_quantity; never invent or recompute figures. Mention low forecast "
                "reliability when present. Do not claim any stock has been changed. Return one rationale per key."
            ),
        },
        {"role": "user", "content": json.dumps({"items": items}, default=str)},
    ]


def apply_rationales(suggestions: list[dict], raw: str | None) -> None:
    """Attach AI text where valid and grounded; otherwise fall back to the rule template."""
    by_key: dict[str, str] = {}
    if raw is not None:
        try:
            parsed = json.loads(raw)
            for item in parsed.get("rationales", []):
                if isinstance(item, dict) and isinstance(item.get("rationale"), str):
                    by_key[str(item.get("key"))] = item["rationale"].strip()
        except (json.JSONDecodeError, AttributeError):
            logger.warning("inventory_suggestions.rationale_invalid_json")
    for i, s in enumerate(suggestions):
        text = by_key.get(str(i), "")
        if text and len(text) <= 800 and grounded(text, s):
            s["rationale"], s["rationale_source"] = text, "ai"
        else:
            s["rationale"], s["rationale_source"] = rule_rationale(s), "rule"


async def openai_rationale_writer(messages: list[dict[str, str]]) -> str:
    from shared.config import settings
    from shared.factory import get_embeddings_client

    if settings.LLM_PROVIDER.lower() not in {"openai", "azure"}:
        raise RuntimeError("Structured rationale requires the openai or azure provider")
    # get_embeddings_client returns the plain OpenAI/Azure SDK client for the active provider.
    client = get_embeddings_client()
    model = settings.AZURE_OPENAI_DEPLOYMENT if settings.LLM_PROVIDER.lower() == "azure" else settings.LLM_MODEL
    response = await client.chat.completions.create(
        model=model,
        messages=messages,
        **sampling_options(0.2, model=model),
        timeout=30,
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "inventory_rationales", "strict": True, "schema": RATIONALE_SCHEMA},
        },
    )
    return response.choices[0].message.content or ""


# ── Persistence ─────────────────────────────────────────────────────────────


async def live_stock_rows(conn: asyncpg.Connection, product_ids: list[str]) -> dict[str, list[dict]]:
    rows = await conn.fetch(
        """SELECT wi.product_id, wi.warehouse_id, w.name AS warehouse_name, w.is_active AS warehouse_active,
                  wi.quantity, wi.reorder_threshold
           FROM warehouse_inventory wi JOIN warehouses w ON w.id = wi.warehouse_id
           WHERE wi.product_id = ANY($1::uuid[])""",
        product_ids,
    )
    result: dict[str, list[dict]] = {}
    for row in rows:
        result.setdefault(str(row["product_id"]), []).append({**dict(row), "warehouse_id": str(row["warehouse_id"])})
    return result


async def generate_suggestions(
    pool: asyncpg.Pool,
    email: str,
    body: GenerateRequest,
    writer: RationaleWriter | None = openai_rationale_writer,
) -> dict:
    from shared.inventory_management import manager_id

    spec = ForecastRequest(
        **({"as_of": body.as_of} if body.as_of else {}),
        horizon=body.rules.horizon,
        category=body.category,
        product_id=body.product_id,
    )
    async with pool.acquire() as conn:
        owner = await manager_id(conn, email)
        async with conn.transaction(isolation="repeatable_read", readonly=True):
            report = await forecast_report(conn, spec)
            active = {
                str(r["id"])
                for r in await conn.fetch(
                    "SELECT id FROM products WHERE id = ANY($1::uuid[]) AND is_active",
                    [p["product_id"] for p in report["products"]],
                )
            }
            report["products"] = [p for p in report["products"] if p["product_id"] in active]
            live = await live_stock_rows(conn, list(active))
    suggestions = compute_suggestions(report, live, body.rules, spec.as_of)

    raw, ai_error = None, None
    if suggestions and body.use_ai and writer is not None:
        # The LLM call happens outside any transaction; failure degrades to rule text.
        try:
            raw = await writer(rationale_messages(suggestions))
        except Exception as exc:  # noqa: BLE001 - any provider failure must degrade, not fail
            ai_error = type(exc).__name__
            logger.warning("inventory_suggestions.rationale_unavailable error=%s", ai_error)
    apply_rationales(suggestions, raw)

    batch_id = uuid.uuid4()
    async with pool.acquire() as conn:
        async with conn.transaction():
            for s in suggestions:
                await conn.execute(
                    """UPDATE inventory_suggestions SET status='superseded', decision_note='Replaced by a newer batch'
                       WHERE product_id=$1 AND suggestion_type=$2 AND status='pending'""",
                    uuid.UUID(s["product_id"]),
                    s["suggestion_type"],
                )
                s["id"] = str(
                    await conn.fetchval(
                        """INSERT INTO inventory_suggestions
                           (batch_id, owner_id, product_id, warehouse_id, suggestion_type, priority,
                            suggested_quantity, as_of, horizon, evidence, rationale, rationale_source)
                           VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11,$12) RETURNING id""",
                        batch_id,
                        owner,
                        uuid.UUID(s["product_id"]),
                        uuid.UUID(s["warehouse_id"]) if s["warehouse_id"] else None,
                        s["suggestion_type"],
                        s["priority"],
                        s["suggested_quantity"],
                        spec.as_of,
                        spec.horizon,
                        json.dumps(s["evidence"], default=str, allow_nan=False),
                        s["rationale"],
                        s["rationale_source"],
                    )
                )
    return {
        "batch_id": str(batch_id),
        "as_of": str(spec.as_of),
        "horizon": spec.horizon,
        "rules": body.rules.model_dump(),
        "products_checked": len(report["products"]),
        "ai_rationale": "unavailable" if ai_error else ("used" if raw is not None else "disabled"),
        "summary": {
            "restock": sum(s["suggestion_type"] == "restock" for s in suggestions),
            "overstock": sum(s["suggestion_type"] == "overstock" for s in suggestions),
            "high_priority": sum(s["priority"] == "high" for s in suggestions),
        },
        "suggestions": [{k: v for k, v in s.items() if k != "category"} | {"status": "pending"} for s in suggestions],
        "note": "Suggestions are pending; stock changes only after a manager accepts one.",
    }


def _decode(row: dict) -> dict:
    if isinstance(row.get("evidence"), str):
        row["evidence"] = json.loads(row["evidence"])
    return row


async def list_suggestions(
    conn: asyncpg.Connection,
    *,
    status: str | None = "pending",
    suggestion_type: str | None = None,
    product_id: uuid.UUID | None = None,
    offset: int = 0,
    limit: int = 50,
) -> dict:
    where = """WHERE ($1::text IS NULL OR s.status=$1) AND ($2::text IS NULL OR s.suggestion_type=$2)
                 AND ($3::uuid IS NULL OR s.product_id=$3)"""
    rows = await conn.fetch(
        f"""SELECT s.id, s.batch_id, s.product_id, p.name AS product_name, p.category, s.warehouse_id,
                   w.name AS warehouse_name, s.suggestion_type, s.priority, s.suggested_quantity, s.as_of,
                   s.horizon, s.evidence, s.rationale, s.rationale_source, s.status, s.decided_at,
                   s.decision_note, s.executed_quantity, s.executed_warehouse_id, s.created_at
            FROM inventory_suggestions s JOIN products p ON p.id=s.product_id
            LEFT JOIN warehouses w ON w.id=s.warehouse_id
            {where}
            ORDER BY CASE s.priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, s.created_at DESC, s.id
            LIMIT $4 OFFSET $5""",
        status,
        suggestion_type,
        product_id,
        limit,
        offset,
    )
    total = await conn.fetchval(
        f"SELECT COUNT(*) FROM inventory_suggestions s {where}", status, suggestion_type, product_id
    )
    return {"suggestions": [_decode(r) for r in serialize(rows)], "total": total, "offset": offset, "limit": limit}


async def decide_suggestion(conn: asyncpg.Connection, suggestion_id: uuid.UUID, body: Decision, email: str) -> dict:
    """Must run inside the caller's transaction (HTTP route or confirmed chat action)."""
    from shared.inventory_management import manager_id

    actor = await manager_id(conn, email)
    s = await conn.fetchrow("SELECT * FROM inventory_suggestions WHERE id=$1 FOR UPDATE", suggestion_id)
    if s is None:
        raise LookupError("Suggestion not found")
    if s["status"] != "pending":
        raise ValueError(f"Suggestion is already {s['status']}")
    now = datetime.now(UTC)
    if body.decision == "reject":
        await conn.execute(
            """UPDATE inventory_suggestions SET status='rejected', decided_by=$2, decided_at=$3, decision_note=$4
               WHERE id=$1""",
            suggestion_id,
            actor,
            now,
            body.note,
        )
        return {"id": str(suggestion_id), "status": "rejected", "stock_changed": False}
    if s["suggestion_type"] == "overstock":
        await conn.execute(
            """UPDATE inventory_suggestions SET status='accepted', decided_by=$2, decided_at=$3, decision_note=$4
               WHERE id=$1""",
            suggestion_id,
            actor,
            now,
            body.note,
        )
        return {
            "id": str(suggestion_id),
            "status": "accepted",
            "stock_changed": False,
            "message": "Overstock decision recorded; run the promotion and pause replenishment manually.",
        }
    quantity = body.quantity or s["suggested_quantity"]
    warehouse_id = body.warehouse_id or s["warehouse_id"]
    if warehouse_id is None:
        raise ValueError("Choose a warehouse to receive the restock")
    if not await conn.fetchval("SELECT is_active FROM products WHERE id=$1", s["product_id"]):
        raise ValueError("Product is delisted; relist it before restocking")
    active = await conn.fetchval("SELECT is_active FROM warehouses WHERE id=$1", warehouse_id)
    if not active:
        raise ValueError("Warehouse not found or inactive")
    await conn.execute(
        """INSERT INTO warehouse_inventory(product_id, warehouse_id, quantity) VALUES($1,$2,0)
           ON CONFLICT DO NOTHING""",
        s["product_id"],
        warehouse_id,
    )
    event_key = f"suggestion:{suggestion_id}"
    balance = await change_inventory(
        conn,
        product_id=s["product_id"],
        warehouse_id=warehouse_id,
        quantity_delta=quantity,
        movement_type="restock_receipt",
        event_key=event_key,
        notes=f"Accepted restock suggestion {suggestion_id} (by {email}) {body.note}".strip(),
    )
    await conn.execute(
        """UPDATE inventory_suggestions SET status='accepted', decided_by=$2, decided_at=$3, decision_note=$4,
                  executed_quantity=$5, executed_warehouse_id=$6, movement_event_key=$7
           WHERE id=$1""",
        suggestion_id,
        actor,
        now,
        body.note,
        quantity,
        warehouse_id,
        event_key,
    )
    return {
        "id": str(suggestion_id),
        "status": "accepted",
        "stock_changed": True,
        "received_quantity": quantity,
        "warehouse_id": str(warehouse_id),
        "warehouse_balance": balance,
    }
