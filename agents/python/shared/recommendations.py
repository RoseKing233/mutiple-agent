"""Evidence retrieval and one bounded MAF call for product recommendation reasons."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Literal
from uuid import UUID

import yaml
from agent_framework import Agent
from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from shared.db import get_pool
from shared.factory import get_chat_client
from shared.prompt_loader import PROMPTS_DIR
from shared.usage_db import log_agent_usage

logger = logging.getLogger(__name__)


class ProductNotFoundError(LookupError):
    """The requested product does not exist or is inactive."""


class RecommendationUnavailableError(RuntimeError):
    """No trustworthy generated response is available."""


class RecommendationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    preferences: str = Field(min_length=1, max_length=1500)
    max_budget: float | None = Field(default=None, ge=0, le=1_000_000, allow_inf_nan=False)
    language: str = Field(default="en", pattern="^(en|zh)$")


class CitedPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=1000)
    source_ids: list[str] = Field(min_length=1, max_length=8)


class NeedsAssessment(CitedPoint):
    status: Literal["meets_needs", "does_not_meet", "cannot_confirm"]


class RecommendationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    needs_assessment: NeedsAssessment
    product_summary: list[CitedPoint] = Field(max_length=4)
    review_summary: list[CitedPoint] = Field(max_length=4)
    reasons: list[CitedPoint] = Field(min_length=1, max_length=5)
    cautions: list[CitedPoint] = Field(max_length=5)


def recommendation_response_format(
    evidence: dict[str, Any], *, budget_fit: bool | None = None
) -> type[RecommendationDraft]:
    """Constrain generated citations to this request's evidence and section kinds.

    Free-form UUID strings can be mistyped even in an otherwise correct answer.
    Enumerating the allowed IDs prevents this at generation time; the existing
    provenance validator remains a second check for providers ignoring the schema.
    """
    sources = evidence["sources"]

    def cited_type(name: str, base: type[CitedPoint], kinds: set[str]) -> Any:
        ids = tuple(dict.fromkeys(source["id"] for source in sources if source["kind"] in kinds))
        if not ids:
            raise ValueError("Cannot create a citation schema without sources")
        return create_model(
            name,
            __base__=base,
            source_ids=(list[Literal[ids]], Field(min_length=1, max_length=8)),
        )

    all_kinds = {"catalogue", "document", "review"}
    point = cited_type("EvidencePoint", CitedPoint, all_kinds)
    assessment = cited_type("EvidenceAssessment", NeedsAssessment, all_kinds)
    stock = evidence.get("product", {}).get("available_quantity")
    if budget_fit is False or (stock is not None and stock <= 0):
        # These are known constraints, not judgements left to the model.
        assessment = create_model("UnavailableAssessment", __base__=assessment, status=(Literal["does_not_meet"], ...))
    product_point = cited_type("ProductEvidencePoint", CitedPoint, {"catalogue", "document"})
    has_reviews = any(source["kind"] == "review" for source in sources)
    review_point = cited_type("ReviewEvidencePoint", CitedPoint, {"review"}) if has_reviews else CitedPoint
    return create_model(
        "EvidenceRecommendationDraft",
        __base__=RecommendationDraft,
        needs_assessment=(assessment, ...),
        product_summary=(list[product_point], Field(max_length=4)),
        review_summary=(list[review_point], Field(max_length=4 if has_reviews else 0)),
        reasons=(list[point], Field(min_length=1, max_length=5)),
        cautions=(list[point], Field(max_length=5)),
    )


async def get_recommendation_evidence(product_id: str | UUID) -> dict[str, Any]:
    """Return bounded, public product evidence without customer identities.

    Review statistics use unflagged rows, not the catalogue's cached rating.
    A stratified sample includes low and high ratings when both exist.
    """
    pid = UUID(str(product_id))
    async with get_pool().acquire() as conn:
        async with conn.transaction(isolation="repeatable_read", readonly=True):
            product = await conn.fetchrow(
                """SELECT id, name, description, category, brand, price, original_price, image_url, specs
                   FROM products WHERE id = $1 AND is_active = TRUE""",
                pid,
            )
            if product is None:
                raise ProductNotFoundError("Product not found or unavailable.")
            documents = await conn.fetch(
                """SELECT id, title, content, source, is_synthetic FROM product_documents
                   WHERE product_id = $1 ORDER BY created_at DESC, id LIMIT 4""",
                pid,
            )
            stats = await conn.fetchrow(
                """SELECT COUNT(*) AS count, AVG(rating) AS average_rating,
                          COUNT(*) FILTER (WHERE is_synthetic) AS synthetic_count
                   FROM reviews WHERE product_id = $1 AND is_flagged = FALSE""",
                pid,
            )
            reviews = await conn.fetch(
                """SELECT id, title, body, rating, is_synthetic FROM (
                       SELECT id, title, body, rating, is_synthetic, created_at,
                              ROW_NUMBER() OVER (
                                  PARTITION BY rating ORDER BY helpful_count DESC, created_at DESC, id
                              ) AS sample_rank
                       FROM reviews WHERE product_id = $1 AND is_flagged = FALSE
                   ) sampled ORDER BY sample_rank, rating, created_at DESC, id LIMIT 8""",
                pid,
            )
            stock = await conn.fetchval(
                "SELECT SUM(quantity) FROM warehouse_inventory WHERE product_id = $1",
                pid,
            )

    specs = product["specs"]
    if isinstance(specs, str):
        specs = json.loads(specs)
    catalogue = {
        "id": str(pid),
        "name": product["name"],
        "category": product["category"],
        "brand": product["brand"],
        "price": float(product["price"]),
        "original_price": float(product["original_price"]) if product["original_price"] is not None else None,
        "rating": round(float(stats["average_rating"]), 2) if stats["average_rating"] is not None else None,
        "review_count": stats["count"],
        "description": (product["description"] or "")[:2500],
        "specs": specs or {},
        "image_url": product["image_url"],
        "available_quantity": int(stock) if stock is not None else None,
    }
    specification_lines = [
        f"{key.replace('_', ' ').capitalize()}: "
        + (json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value))
        for key, value in (specs or {}).items()
        if key != "demo_options"
    ]
    catalogue_text = "\n".join(
        [
            product["name"],
            f"Price (USD): {catalogue['price']:.2f}",
            f"Brand: {product['brand'] or 'Not specified'}",
            f"Category: {product['category']}",
            catalogue["description"],
            *specification_lines,
            f"Available quantity: {catalogue['available_quantity'] if stock is not None else 'Unknown'}",
        ]
    )
    sources = [
        {
            "id": f"product:{pid}",
            "kind": "catalogue",
            "title": product["name"],
            "text": catalogue_text,
            "origin": "Stored product catalogue",
            "is_synthetic": False,
        }
    ]
    demo_options = (specs or {}).get("demo_options")
    if isinstance(demo_options, dict) and demo_options.get("is_synthetic") is True:
        attributes = demo_options.get("attributes", {})
        if isinstance(attributes, dict) and attributes:
            sources.append(
                {
                    "id": f"demo-options:{pid}",
                    "kind": "catalogue",
                    "title": f"{product['name']} demo catalogue options",
                    "text": "Synthetic demo catalogue options (not verified manufacturer offerings).\n"
                    + "\n".join(f"{key.replace('_', ' ').capitalize()}: {value}" for key, value in attributes.items())
                    + "\nOption structure: independent attribute lists, not purchasable variants. "
                    "Colour/size combinations: not recorded. A listed colour and listed size "
                    "do not establish that their combination exists."
                    + "\nThese are listed options, not colour/size stock records. "
                    "Stock totals do not establish availability of a particular colour or size.",
                    "origin": str(demo_options.get("source", "Synthetic classroom catalogue options")),
                    "is_synthetic": True,
                }
            )
    sources.extend(
        {
            "id": f"document:{d['id']}",
            "kind": "document",
            "title": d["title"],
            "text": d["content"][:2000],
            "origin": d["source"],
            "is_synthetic": d["is_synthetic"],
        }
        for d in documents
    )
    sources.extend(
        {
            "id": f"review:{r['id']}",
            "kind": "review",
            "title": r["title"] or "Review",
            "text": r["body"][:800],
            "rating": r["rating"],
            "origin": "Synthetic demo review" if r["is_synthetic"] else "Stored customer review",
            "is_synthetic": r["is_synthetic"],
        }
        for r in reviews
    )
    warnings: list[str] = []
    if not documents:
        warnings.append("No supporting documents are available; only catalogue information can be summarised.")
    if not reviews:
        warnings.append("No eligible reviews are available; customer opinions cannot be summarised.")
    elif stats["count"] < 3:
        warnings.append("Few reviews are available; this is insufficient to infer a general customer consensus.")
    if stats["count"] > len(reviews):
        warnings.append(f"Review text is a sample of {len(reviews)} out of {stats['count']} eligible reviews.")
    if any(s["is_synthetic"] for s in sources):
        warnings.append("Includes AI-authored demo material. Synthetic reviews are not real customer feedback.")
    if stock is None:
        warnings.append("Stock availability is unknown.")
    elif stock <= 0:
        warnings.append("This product is currently out of stock.")
    return {
        "product": catalogue,
        "sources": sources,
        "warnings": warnings,
        "review_statistics": {
            "count": stats["count"],
            "sample_size": len(reviews),
            "synthetic_count": stats["synthetic_count"],
            "average_rating": round(float(stats["average_rating"]), 2) if stats["average_rating"] is not None else None,
        },
    }


def validate_recommendation(draft: RecommendationDraft, evidence: dict[str, Any]) -> None:
    """Reject unknown citations and summary sections citing the wrong source type.

    Citation validation checks provenance, not semantic truth; the prompt and
    visible evidence allow users to assess the model's interpretation.
    """
    sources = {s["id"]: s for s in evidence["sources"]}
    for section in ("needs_assessment", "product_summary", "review_summary", "reasons", "cautions"):
        points = [draft.needs_assessment] if section == "needs_assessment" else getattr(draft, section)
        for point in points:
            if not point.text.strip() or any(s not in sources for s in point.source_ids):
                raise RecommendationUnavailableError("The AI response contained unsupported references.")
            kinds = {sources[s]["kind"] for s in point.source_ids}
            if section == "review_summary" and kinds != {"review"}:
                raise RecommendationUnavailableError("The review summary was not supported by review evidence.")
            if section == "product_summary" and not kinds <= {"catalogue", "document"}:
                raise RecommendationUnavailableError("The product summary was not supported by product evidence.")


async def generate_recommendation(
    product_id: str | UUID,
    request: RecommendationRequest,
    *,
    user_id: str | None = None,
) -> dict[str, Any]:
    """One bounded agent invocation, with no fabricated fallback recommendations."""
    evidence = await get_recommendation_evidence(product_id)
    budget_fit = None if request.max_budget is None else evidence["product"]["price"] <= request.max_budget
    if budget_fit is False:
        evidence["warnings"].append("The catalogue price exceeds the requested maximum budget.")
    started = time.monotonic()
    tokens_in = tokens_out = 0
    status = "error"
    try:
        response_format = recommendation_response_format(evidence, budget_fit=budget_fit)
        async with Agent(
            client=get_chat_client(),
            name="recommendation-reasons",
            # This tool-free assessment has its own grounding instructions.
            # The general chat fragments require tool calls and product-card
            # fences, which conflict with the structured response contract.
            instructions=yaml.safe_load((PROMPTS_DIR / "recommendation-reasons.yaml").read_text(encoding="utf-8"))[
                "system_prompt"
            ]["base"],
            tools=[],
        ) as agent:
            response = await asyncio.wait_for(
                agent.run(
                    json.dumps(
                        {"request": request.model_dump(), "budget_fit": budget_fit, "evidence": evidence},
                        ensure_ascii=False,
                        default=str,
                    ),
                    options={"response_format": response_format, "max_tokens": 1600},
                ),
                timeout=45,
            )
        usage = response.usage_details or {}
        tokens_in = int(usage.get("input_token_count", 0) or 0)
        tokens_out = int(usage.get("output_token_count", 0) or 0)
        draft = response.value
        if isinstance(draft, BaseModel):
            draft = response_format.model_validate(draft.model_dump())
        else:
            draft = response_format.model_validate_json(response.text)
        validate_recommendation(draft, evidence)
        status = "success"
        return {
            "product_id": str(product_id),
            "product_name": evidence["product"]["name"],
            "product": evidence["product"],
            "preferences": request.preferences,
            "budget_fit": budget_fit,
            **draft.model_dump(),
            "sources": evidence["sources"],
            "warnings": evidence["warnings"],
            "review_statistics": evidence["review_statistics"],
            "usage": {"input_tokens": tokens_in, "output_tokens": tokens_out},
        }
    except RecommendationUnavailableError:
        raise
    except (ValidationError, ValueError, TimeoutError) as exc:
        logger.warning("Recommendation generation unavailable (%s)", type(exc).__name__)
        raise RecommendationUnavailableError("AI recommendation is unavailable. Please try again later.") from exc
    except Exception as exc:
        # Do not return provider errors, credentials, or a guessed recommendation.
        logger.warning("Recommendation provider failed (%s)", type(exc).__name__)
        raise RecommendationUnavailableError("AI recommendation is unavailable. Please try again later.") from exc
    finally:
        await log_agent_usage(
            user_id,
            "recommendation-reasons",
            input_summary=f"product:{product_id}",
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            status=status,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
