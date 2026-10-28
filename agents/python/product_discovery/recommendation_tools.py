"""Recommendation tools shared by direct and MCP-backed discovery agents."""

from __future__ import annotations

from typing import Annotated, Any

from agent_framework import tool
from pydantic import Field

from shared.recommendations import (
    ProductNotFoundError,
    RecommendationRequest,
    RecommendationUnavailableError,
    generate_recommendation,
    get_recommendation_evidence,
)


@tool(
    name="get_recommendation_evidence",
    description=(
        "Read product introduction, documents, review samples and stock before explaining a recommendation. "
        "Includes source IDs and demo-data labels."
    ),
)
async def recommendation_evidence_tool(
    product_id: Annotated[str, Field(description="Product UUID returned by a catalogue search")],
) -> dict[str, Any]:
    try:
        return await get_recommendation_evidence(product_id)
    except (ProductNotFoundError, ValueError):
        return {"error": "Product not found or invalid product ID."}
    except Exception:
        return {"error": "Product evidence is temporarily unavailable. Do not invent recommendation reasons."}


@tool(
    name="generate_recommendation_reasons",
    description=(
        "Generate cited recommendation reasons and document/review summaries for one product "
        "and the customer's stated preferences. Makes one additional AI call."
    ),
)
async def recommendation_reasons_tool(
    product_id: Annotated[str, Field(description="Product UUID returned by a catalogue search")],
    preferences: Annotated[str, Field(description="Customer's stated needs, not inferred private information")],
    max_budget: Annotated[float | None, Field(description="Customer's maximum budget in catalogue currency")] = None,
    language: Annotated[str, Field(description="en or zh")] = "en",
) -> dict[str, Any]:
    try:
        return await generate_recommendation(
            product_id,
            RecommendationRequest(preferences=preferences, max_budget=max_budget, language=language),
        )
    except ProductNotFoundError:
        return {"error": "Product not found or unavailable."}
    except ValueError:
        return {"error": "Invalid product ID, preferences, budget or language."}
    except RecommendationUnavailableError as exc:
        return {"error": str(exc)}
    except Exception:
        return {"error": "Product evidence is temporarily unavailable. Do not invent recommendation reasons."}
