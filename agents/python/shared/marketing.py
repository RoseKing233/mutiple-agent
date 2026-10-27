"""AI marketing assist for new listings: candidate titles/copy and product images.

Nothing here writes to ``products``; the manager picks candidates in the form and saves the
product through the inventory module. Every generation is logged in ``marketing_generations``.
Copy is JSON-schema constrained and number-checked against the manager's own input, so the
model cannot add prices, specs or ratings that were never provided (Stage 1 NFR).
"""

from __future__ import annotations

import base64
import json
import logging
import math
import os
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Literal

import asyncpg
from pydantic import BaseModel, ConfigDict, Field

from shared.inventory_management import manager_id

logger = logging.getLogger(__name__)

CopyWriter = Callable[[list[dict[str, str]]], Awaitable[str]]
ImageGenerator = Callable[[str, int], Awaitable[list[bytes]]]

COPY_VARIANTS = 3
IMAGE_COUNT = 2

COPY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "variants": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "angle": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "highlights": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["angle", "title", "description", "highlights"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["variants"],
    "additionalProperties": False,
}


class MarketingUnavailableError(Exception):
    """The generation service failed or returned nothing usable; the form stays as it was."""


class CopyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    category: str = Field(min_length=1, max_length=100)
    brand: str | None = Field(default=None, max_length=100)
    price: float | None = Field(default=None, gt=0, le=1_000_000)
    description: str = Field(default="", max_length=2000)
    keywords: list[str] = Field(default_factory=list, max_length=10)
    audience: str = Field(default="", max_length=200)
    tone: Literal["friendly", "professional", "premium", "playful"] = "friendly"


class ImageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    category: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)
    style: Literal["studio", "lifestyle", "minimal", "festive"] = "studio"
    background: str = Field(default="", max_length=200)


# ── Copy ────────────────────────────────────────────────────────────────────

_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def _numbers(text: str) -> set[float]:
    return {float(n.replace(",", "")) for n in _NUMBER.findall(text)}


def copy_messages(body: CopyRequest) -> list[dict[str, str]]:
    facts = body.model_dump(exclude={"tone"}, exclude_none=True)
    return [
        {
            "role": "system",
            "content": (
                "You write e-commerce listing copy for a store manager. Produce exactly 3 variants, each with a "
                "different angle (for example benefit-led, story-led, concise). Each variant: a title under 80 "
                "characters, a description of 2-4 sentences, and exactly 3 short highlights. Use ONLY facts in the "
                "input. Never invent specifications, measurements, prices, discounts, ratings, awards, warranties or "
                "certifications, and do not use any number that is not in the input. Tone: " + body.tone + "."
            ),
        },
        {"role": "user", "content": json.dumps(facts, ensure_ascii=False)},
    ]


def valid_variants(raw: str, body: CopyRequest) -> list[dict[str, Any]]:
    """Keep well-formed variants whose numbers all come from the manager's input."""
    try:
        variants = json.loads(raw).get("variants", [])
    except (json.JSONDecodeError, AttributeError):
        return []
    # Names are stripped from the copy below, so their digits ("Lamp 2") must not license
    # the same digit elsewhere ("2-year warranty").
    source = " ".join([body.category, body.description, body.audience, *body.keywords])
    allowed = _numbers(source) | ({body.price} if body.price else set())
    kept = []
    for v in variants:
        if not isinstance(v, dict):
            continue
        title, description = str(v.get("title", "")).strip(), str(v.get("description", "")).strip()
        highlights = [str(h).strip() for h in v.get("highlights", []) if str(h).strip()][:3]
        if not title or not description or len(title) > 120 or len(description) > 1500:
            continue
        text = " ".join([title, description, *highlights])
        for name in (body.name, body.brand):
            if name:
                text = re.sub(re.escape(name), " ", text, flags=re.IGNORECASE)
        if any(not any(math.isclose(n, a, rel_tol=1e-6) for a in allowed) for n in _numbers(text)):
            logger.info("marketing.copy_variant_dropped reason=ungrounded_number")
            continue
        kept.append(
            {
                "angle": str(v.get("angle", "")).strip(),
                "title": title,
                "description": description,
                "highlights": highlights,
            }
        )
    return kept[:COPY_VARIANTS]


async def openai_copy_writer(messages: list[dict[str, str]]) -> str:
    from shared.config import settings
    from shared.factory import get_embeddings_client

    if settings.LLM_PROVIDER.lower() not in {"openai", "azure"}:
        raise MarketingUnavailableError("Copy generation requires the openai or azure provider")
    # get_embeddings_client returns the plain OpenAI/Azure SDK client for the active provider.
    client = get_embeddings_client()
    model = settings.AZURE_OPENAI_DEPLOYMENT if settings.LLM_PROVIDER.lower() == "azure" else settings.LLM_MODEL
    response = await client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.8,
        timeout=60,
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "listing_copy", "strict": True, "schema": COPY_SCHEMA},
        },
    )
    return response.choices[0].message.content or ""


# ── Images ──────────────────────────────────────────────────────────────────

STYLE_HINTS = {
    "studio": "clean studio product photography, soft even lighting",
    "lifestyle": "lifestyle scene showing the product in natural everyday use",
    "minimal": "minimalist composition with generous negative space",
    "festive": "festive seasonal promotional mood with warm accents",
}


def image_prompt(body: ImageRequest) -> str:
    parts = [
        f"Professional e-commerce product image of {body.name} (category: {body.category}).",
        body.description[:400],
        f"Style: {STYLE_HINTS[body.style]}.",
        f"Background: {body.background}." if body.background else "",
        "The product is the clear focal point. No text, no captions, no logos, no watermarks, no people's faces.",
    ]
    return " ".join(p for p in parts if p)


def image_model() -> str:
    return os.environ.get("MARKETING_IMAGE_MODEL", "gpt-image-1-mini")


async def openai_image_generator(prompt: str, count: int) -> list[bytes]:
    from shared.config import settings
    from shared.factory import get_embeddings_client

    if settings.LLM_PROVIDER.lower() != "openai":
        raise MarketingUnavailableError("Image generation requires the openai provider")
    response = await get_embeddings_client().images.generate(
        model=image_model(),
        prompt=prompt,
        n=count,
        size="1024x1024",
        quality=os.environ.get("MARKETING_IMAGE_QUALITY", "low"),
        output_format="webp",
        output_compression=80,
        timeout=120,
    )
    return [base64.b64decode(item.b64_json) for item in response.data if item.b64_json]


# ── Orchestration and logging ───────────────────────────────────────────────


async def _log(
    conn: asyncpg.Connection,
    owner: uuid.UUID,
    kind: str,
    request: dict,
    output: Any,
    error: str,
    model: str,
    started: float,
) -> uuid.UUID:
    return await conn.fetchval(
        """INSERT INTO marketing_generations(owner_id, kind, request, output, status, error, model, duration_ms)
           VALUES($1,$2,$3::jsonb,$4::jsonb,$5,$6,$7,$8) RETURNING id""",
        owner,
        kind,
        json.dumps(request, ensure_ascii=False),
        json.dumps(output, ensure_ascii=False) if output is not None else None,
        "failed" if error else "succeeded",
        error,
        model,
        int((time.monotonic() - started) * 1000),
    )


async def generate_copy(pool: asyncpg.Pool, email: str, body: CopyRequest, writer: CopyWriter | None = None) -> dict:
    from shared.config import settings

    writer = writer or openai_copy_writer
    async with pool.acquire() as conn:
        owner = await manager_id(conn, email)
    started = time.monotonic()
    variants, error = [], ""
    try:
        variants = valid_variants(await writer(copy_messages(body)), body)
        if not variants:
            error = "The AI returned no usable variant (unsupported facts or invalid format)"
    except MarketingUnavailableError as exc:
        error = str(exc)
    except Exception as exc:  # noqa: BLE001 - any provider failure must degrade to a retryable 503
        logger.warning("marketing.copy_unavailable error=%s", type(exc).__name__)
        error = f"Copy generation service unavailable ({type(exc).__name__})"
    async with pool.acquire() as conn:
        generation = await _log(
            conn, owner, "copy", body.model_dump(), {"variants": variants}, error, settings.LLM_MODEL, started
        )
    if error:
        raise MarketingUnavailableError(f"{error}. Your form is unchanged; retry or write it manually.")
    return {"generation_id": str(generation), "variants": variants}


async def generate_images(
    pool: asyncpg.Pool, email: str, body: ImageRequest, generator: ImageGenerator | None = None
) -> dict:
    generator = generator or openai_image_generator
    async with pool.acquire() as conn:
        owner = await manager_id(conn, email)
    prompt, model, started = image_prompt(body), image_model(), time.monotonic()
    images, error = [], ""
    try:
        images = [data for data in await generator(prompt, IMAGE_COUNT) if data][:IMAGE_COUNT]
        if not images:
            error = "The image service returned no image"
    except MarketingUnavailableError as exc:
        error = str(exc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("marketing.image_unavailable error=%s", type(exc).__name__)
        error = f"Image generation service unavailable ({type(exc).__name__})"
    async with pool.acquire() as conn:
        async with conn.transaction():
            generation = await _log(
                conn, owner, "image", body.model_dump() | {"prompt": prompt}, None, error, model, started
            )
            ids = [
                await conn.fetchval(
                    """INSERT INTO generated_images(owner_id, generation_id, prompt, model, mime_type, data)
                       VALUES($1,$2,$3,$4,'image/webp',$5) RETURNING id""",
                    owner,
                    generation,
                    prompt,
                    model,
                    data,
                )
                for data in images
            ]
            await conn.execute(
                "UPDATE marketing_generations SET output=$2::jsonb WHERE id=$1",
                generation,
                json.dumps({"image_ids": [str(i) for i in ids]}),
            )
    if error:
        raise MarketingUnavailableError(f"{error}. Your form is unchanged; retry or set an image URL manually.")
    return {
        "generation_id": str(generation),
        "prompt": prompt,
        "images": [{"id": str(i), "url": f"/api/media/{i}"} for i in ids],
    }


async def read_image(conn: asyncpg.Connection, image_id: uuid.UUID) -> tuple[bytes, str]:
    row = await conn.fetchrow("SELECT data, mime_type FROM generated_images WHERE id=$1", image_id)
    if row is None:
        raise LookupError("Image not found")
    return bytes(row["data"]), row["mime_type"]
