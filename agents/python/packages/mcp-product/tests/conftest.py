"""
Shared pytest fixtures for ecommerce-mcp-product tests.

Policy:
- Never mock the database. DB tests use `postgres_pool` which provisions a
  real Postgres container via testcontainers.
- Uses the same production schema (docker/postgres/init.sql) as the main test suite.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Generator
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio
from testcontainers.postgres import PostgresContainer

REPO_ROOT = Path(__file__).resolve().parents[5]  # agents/python/packages/mcp-product/tests -> repo root
INIT_SQL = REPO_ROOT / "docker" / "postgres" / "init.sql"


@pytest.fixture(scope="session")
def postgres_container() -> Generator[PostgresContainer, None, None]:
    container = PostgresContainer("pgvector/pgvector:pg16", dbname="ecommerce_test")
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def database_url(postgres_container: PostgresContainer) -> str:
    url = postgres_container.get_connection_url()
    return url.replace("postgresql+psycopg2://", "postgresql://")


@pytest_asyncio.fixture(scope="session")
async def _schema_applied(database_url: str) -> None:
    sql = INIT_SQL.read_text()
    conn = await asyncpg.connect(database_url)
    try:
        await conn.execute(sql)
    finally:
        await conn.close()


@pytest_asyncio.fixture
async def postgres_pool(
    database_url: str,
    _schema_applied: None,
) -> AsyncGenerator[asyncpg.Pool, None]:
    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=5)
    try:
        yield pool
    finally:
        await pool.close()
