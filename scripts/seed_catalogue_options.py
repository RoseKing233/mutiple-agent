"""Add labelled classroom colour/size options without resetting catalogue or stock.

Dry run by default. --apply saves the original/updated specs in .claude/ before
writing. Existing options and specifications are preserved on repeated imports.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents" / "python"))

from shared.config import settings  # noqa: E402

CONTENT = Path(__file__).parent / "data" / "catalogue_options.json"
ALIASES = {
    "colours": {"colour", "colours", "color", "colors", "available_colors", "available_colours"},
    "sizes": {"size", "sizes", "available_sizes"},
    "language": {"language", "languages"},
    "finish": {"finish", "finishes", "colour", "colours", "color", "colors"},
}


async def seed_options(
    conn: asyncpg.Connection, *, apply: bool = False, backup_path: Path | None = None
) -> dict[str, Any]:
    data = json.loads(CONTENT.read_text(encoding="utf-8"))
    profiles = {p["name"]: p["options"] for p in data["products"]}
    changes: list[dict[str, Any]] = []
    skipped: list[str] = []
    async with conn.transaction():
        products = await conn.fetch(
            "SELECT id, name, specs FROM products WHERE is_active = TRUE ORDER BY id" + (" FOR UPDATE" if apply else "")
        )
        if not products:
            raise ValueError("No active products exist. Initialise a demo catalogue first.")
        for product in products:
            profile = profiles.get(product["name"])
            if profile is None:
                continue
            specs = product["specs"] or {}
            if isinstance(specs, str):
                specs = json.loads(specs)
            if not isinstance(specs, dict) or "demo_options" in specs:
                skipped.append(product["name"])
                continue
            present = {key.lower() for key in specs}
            attributes = {
                key: value for key, value in profile.items() if not present.intersection(ALIASES.get(key, {key}))
            }
            if "colours" not in attributes:
                attributes.pop("colour_note", None)
            if not attributes:
                skipped.append(product["name"])
                continue
            updated = specs | {
                "demo_options": {"is_synthetic": True, "source": data["source"], "attributes": attributes}
            }
            changes.append({"id": str(product["id"]), "name": product["name"], "before": specs, "after": updated})
        if apply and changes:
            if backup_path is None:
                raise ValueError("A backup path is required before updating catalogue options.")
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive creation prevents an accidental overwrite of an earlier backup.
            with backup_path.open("x", encoding="utf-8") as backup:
                json.dump({"created_at": datetime.now(UTC).isoformat(), "changes": changes}, backup, indent=2)
            for change in changes:
                await conn.execute(
                    "UPDATE products SET specs = $2::jsonb WHERE id = $1::uuid",
                    change["id"],
                    json.dumps(change["after"]),
                )
    return {
        "apply": apply,
        "planned_updates": len(changes),
        "updated": len(changes) if apply else 0,
        "skipped_existing": skipped,
        "unmatched_profiles": sorted(set(profiles) - {p["name"] for p in products}),
        "backup": str(backup_path) if apply and changes else None,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Back up and add missing demo options")
    args = parser.parse_args()
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = ROOT / ".claude" / "recommendation-checks" / f"catalogue-options-backup-{timestamp}.json"
    conn = await asyncpg.connect(settings.DATABASE_URL)
    try:
        print(json.dumps(await seed_options(conn, apply=args.apply, backup_path=backup_path), indent=2))
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
