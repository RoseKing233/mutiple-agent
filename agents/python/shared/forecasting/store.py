"""Owner-scoped immutable snapshots with idempotent request IDs."""

import json
import uuid
from typing import Any

import asyncpg

from shared.forecasting.config import ENGINE_VERSION, ForecastRequest
from shared.forecasting.service import forecast_report
from shared.sales_analysis import serialize


def decode(value: Any) -> Any:
    return json.loads(value) if isinstance(value, str) else value


async def save_report(pool: asyncpg.Pool, email: str, spec: ForecastRequest, request_id: uuid.UUID) -> dict:
    async with pool.acquire() as conn:
        owner = await conn.fetchval("SELECT id FROM users WHERE email=$1 AND role IN ('store_manager','admin')", email)
        if owner is None:
            raise PermissionError("Store manager account required")
        # Session lock before establishing the repeatable-read snapshot: a retry
        # waits for the original commit, then can see and return that same row.
        lock = f"analysis:{owner}:{request_id}"
        await conn.execute("SELECT pg_advisory_lock(hashtextextended($1,0))", lock)
        try:
            async with conn.transaction(isolation="repeatable_read"):
                previous = await conn.fetchrow(
                    "SELECT id,result,parameters FROM sales_analysis_runs WHERE owner_id=$1 AND request_id=$2",
                    owner,
                    request_id,
                )
                params = spec.model_dump(mode="json")
                if previous:
                    if decode(previous["parameters"]) != params:
                        raise ValueError("Request ID already used with different parameters")
                    return {"id": str(previous["id"]), **decode(previous["result"])}
                result = await forecast_report(conn, spec)
                run_id = uuid.uuid4()
                await conn.execute(
                    """INSERT INTO sales_analysis_runs
                    (id,owner_id,request_id,engine_version,as_of,horizon,parameters,result)
                    VALUES($1,$2,$3,$4,$5,$6,$7::jsonb,$8::jsonb)""",
                    run_id,
                    owner,
                    request_id,
                    ENGINE_VERSION,
                    spec.as_of,
                    spec.horizon,
                    json.dumps(params, allow_nan=False),
                    json.dumps(result, allow_nan=False),
                )
                return {"id": str(run_id), **result}
        finally:
            await conn.execute("SELECT pg_advisory_unlock(hashtextextended($1,0))", lock)


async def list_reports(conn: asyncpg.Connection, email: str, limit: int = 20, offset: int = 0) -> dict:
    rows = await conn.fetch(
        """SELECT r.id,r.as_of,r.horizon,r.created_at,r.parameters,r.engine_version,
        r.result->'summary' AS summary FROM sales_analysis_runs r JOIN users u ON u.id=r.owner_id
        WHERE u.email=$1 ORDER BY r.created_at DESC,r.id LIMIT $2 OFFSET $3""",
        email,
        limit,
        offset,
    )
    total = await conn.fetchval(
        "SELECT COUNT(*) FROM sales_analysis_runs r JOIN users u ON u.id=r.owner_id WHERE u.email=$1",
        email,
    )
    return {
        "runs": [
            {**serialize(r), "parameters": decode(r["parameters"]), "summary": decode(r["summary"])} for r in rows
        ],
        "total": total,
        "offset": offset,
        "limit": limit,
    }


async def get_report(conn: asyncpg.Connection, email: str, run_id: uuid.UUID) -> dict:
    row = await conn.fetchrow(
        """SELECT r.id,r.result FROM sales_analysis_runs r JOIN users u ON u.id=r.owner_id
        WHERE r.id=$1 AND u.email=$2""",
        run_id,
        email,
    )
    if row is None:
        raise LookupError("Saved analysis not found")
    return {"id": str(row["id"]), **decode(row["result"])}
