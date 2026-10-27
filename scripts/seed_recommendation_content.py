"""Add recommendation demo evidence without resetting the existing database.

Run from repo root with the agents/python environment. A dry run is the default;
pass --apply to migrate and insert. Stable IDs make repeated imports idempotent.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import Any

import asyncpg

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "agents" / "python"))

from shared.config import settings
from shared.db_migrations import apply_migrations

NAMESPACE = uuid.UUID("7f8d012c-6599-4cdd-8d75-940d60312426")
CONTENT = Path(__file__).parent / "data" / "recommendation_content.json"


def demo_id(kind: str, product_id: uuid.UUID, suffix: str = "") -> uuid.UUID:
    return uuid.uuid5(NAMESPACE, f"{kind}:{product_id}:{suffix}")


async def seed_content(
    conn: asyncpg.Connection, *, apply: bool = False
) -> dict[str, Any]:
    data = json.loads(CONTENT.read_text(encoding="utf-8"))
    profiles = {p["name"]: p for p in data["products"]}
    products = await conn.fetch(
        "SELECT id, name, description, specs FROM products WHERE is_active = TRUE ORDER BY id"
    )
    if not products:
        raise ValueError(
            "No products exist. Initialise the demo catalogue before importing recommendation content."
        )
    planned_reviews = sum(
        len(profiles.get(p["name"], {}).get("reviews", [])) for p in products
    )
    result = {
        "apply": apply,
        "products": len(products),
        "introductions": len(products),
        "guides": sum(p["name"] in profiles for p in products),
        "synthetic_reviews": planned_reviews,
        "unmatched_profiles": sorted(set(profiles) - {p["name"] for p in products}),
    }
    if not apply:
        return result
    async with conn.transaction():
        await apply_migrations(conn)
        reviewer_id = uuid.uuid5(NAMESPACE, "synthetic-reviewer")
        await conn.execute(
            """INSERT INTO users (id, email, name, password_hash, is_active)
               VALUES ($1, 'recommendation-demo@example.invalid', 'Synthetic demo reviewer', 'disabled', FALSE)
               ON CONFLICT (id) DO NOTHING""",
            reviewer_id,
        )
        for product in products:
            specs = product["specs"]
            if isinstance(specs, str):
                specs = json.loads(specs)
            specification_lines = [
                f"{key.replace('_', ' ').capitalize()}: {value}"
                for key, value in (specs or {}).items()
            ]
            introduction = "\n".join(
                [product["description"] or "", *specification_lines]
            )
            docs = [("introduction", f"{product['name']} introduction", introduction)]
            profile = profiles.get(product["name"], {})
            if profile:
                docs.append(
                    ("guide", f"{product['name']} buying notes", profile["guide"])
                )
            for kind, title, content in docs:
                await conn.execute(
                    """INSERT INTO product_documents (id, product_id, title, content, source, is_synthetic)
                       VALUES ($1, $2, $3, $4, $5, TRUE)
                       ON CONFLICT (id) DO UPDATE SET title = EXCLUDED.title, content = EXCLUDED.content,
                       source = EXCLUDED.source WHERE product_documents.is_synthetic = TRUE""",
                    demo_id(kind, product["id"]),
                    product["id"],
                    title,
                    content,
                    data["source"],
                )
            for index, review in enumerate(profile.get("reviews", [])):
                await conn.execute(
                    """INSERT INTO reviews
                       (id, product_id, rating, title, body, verified_purchase, is_flagged, is_synthetic, user_id)
                       VALUES ($1, $2, $3, $4, $5, FALSE, FALSE, TRUE, $6)
                       ON CONFLICT (id) DO UPDATE SET rating = EXCLUDED.rating, title = EXCLUDED.title,
                       body = EXCLUDED.body WHERE reviews.is_synthetic = TRUE""",
                    demo_id("review", product["id"], str(index)),
                    product["id"],
                    review["rating"],
                    review["title"],
                    "[SYNTHETIC DEMO REVIEW] " + review["body"],
                    reviewer_id,
                )
            # Keep the storefront count/rating consistent with its stored review rows.
            if profile.get("reviews"):
                await conn.execute(
                    """UPDATE products SET
                       review_count = (SELECT COUNT(*) FROM reviews WHERE product_id = $1),
                       rating = COALESCE((SELECT AVG(rating) FROM reviews WHERE product_id = $1), 0)
                       WHERE id = $1""",
                    product["id"],
                )
    return result


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply the additive migration and demo content",
    )
    args = parser.parse_args()
    conn = await asyncpg.connect(settings.DATABASE_URL)
    try:
        print(json.dumps(await seed_content(conn, apply=args.apply), indent=2))
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
