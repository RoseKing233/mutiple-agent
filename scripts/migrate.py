"""From repo root: python -m scripts.migrate (requires asyncpg). Preserves data."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents" / "python"))

from shared.db_migrations import apply_migrations  # noqa: E402


async def main() -> None:
    url = os.environ.get("DATABASE_URL", "postgresql://ecommerce:ecommerce_secret@localhost:5432/ecommerce_agents")
    conn = await asyncpg.connect(url)
    try:
        versions = await apply_migrations(conn)
        print("Applied: " + (", ".join(versions) or "already up to date"))
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
