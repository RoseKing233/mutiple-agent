"""Public product evidence and rate-limited recommendation generation."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from orchestrator.routes.legacy import optional_auth
from shared.rate_limit import rate_limit_chat
from shared.recommendations import (
    ProductNotFoundError,
    RecommendationRequest,
    RecommendationUnavailableError,
    generate_recommendation,
    get_recommendation_evidence,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/products", tags=["recommendations"])


@router.get("/{product_id}/recommendation-evidence")
async def recommendation_evidence(
    product_id: UUID,
    user: dict[str, Any] = Depends(optional_auth),
) -> dict[str, Any]:
    try:
        return await get_recommendation_evidence(product_id)
    except ProductNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except Exception as exc:
        logger.warning("Recommendation evidence unavailable (%s)", type(exc).__name__)
        raise HTTPException(503, "Product evidence is temporarily unavailable.") from exc


@router.post("/{product_id}/recommendation-reasons")
async def recommendation_reasons(
    product_id: UUID,
    body: RecommendationRequest,
    user: dict[str, Any] = Depends(optional_auth),
    _rate_limit: None = Depends(rate_limit_chat),
) -> dict[str, Any]:
    try:
        return await generate_recommendation(product_id, body, user_id=user.get("user_id") or None)
    except ProductNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RecommendationUnavailableError as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:
        logger.warning("Recommendation evidence unavailable (%s)", type(exc).__name__)
        raise HTTPException(503, "Product evidence is temporarily unavailable.") from exc
