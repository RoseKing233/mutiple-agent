"""Create a manager without resetting data: python -m scripts.create_manager."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "agents" / "python"))

from shared.db_migrations import apply_migrations
from shared.manager_accounts import MANAGER_EMAIL, MANAGER_PASSWORD, ensure_manager


async def run(args: argparse.Namespace) -> None:
    conn = await asyncpg.connect(
        os.environ.get(
            "DATABASE_URL",
            "postgresql://ecommerce:ecommerce_secret@localhost:5432/ecommerce_agents",
        )
    )
    try:
        await apply_migrations(conn)
        async with conn.transaction():
            await ensure_manager(conn, args.email, args.password, args.name)
        print(f"Manager ready: {args.email}. Existing accounts/passwords were preserved.")
    finally:
        await conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", default=MANAGER_EMAIL)
    parser.add_argument("--password", default=MANAGER_PASSWORD)
    parser.add_argument("--name", default="Store Manager")
    asyncio.run(run(parser.parse_args()))
