"""SQL migrations shared by developer commands and the seeder; never reset data."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import asyncpg


def migration_directory() -> Path:
    override = os.environ.get("MIGRATIONS_DIR")
    if override:
        return Path(override)
    source = Path(__file__).resolve()
    if source.parent.parent.joinpath("migrations").is_dir():
        return source.parent.parent / "migrations"
    return source.parents[3] / "docker" / "postgres" / "migrations"


async def apply_migrations(conn: asyncpg.Connection, directory: Path | None = None) -> list[str]:
    """Serialize runners, verify checksums, and apply each version exactly once."""
    directory = directory or migration_directory()
    files = sorted(directory.glob("[0-9]*.sql"))
    if not files:
        raise RuntimeError(f"No SQL migrations found in {directory}")
    applied = []
    async with conn.transaction():
        await conn.execute("SELECT pg_advisory_xact_lock(5620001)")
        await conn.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY, checksum TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""")
        for path in files:
            sql = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(sql.encode()).hexdigest()
            previous = await conn.fetchval("SELECT checksum FROM schema_migrations WHERE version = $1", path.name)
            if previous:
                if previous != checksum:
                    raise RuntimeError(f"Applied migration changed: {path.name}; add a new migration instead")
                continue
            await conn.execute(sql)
            await conn.execute(
                "INSERT INTO schema_migrations(version, checksum) VALUES ($1, $2)",
                path.name,
                checksum,
            )
            applied.append(path.name)
    return applied
