"""Marketing assist for new listings (manager) and public serving of generated images."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Response

from shared import marketing
from shared.db import get_pool

from .manager import Manager

router = APIRouter(tags=["marketing"])


@router.post("/api/manager/marketing/copy")
async def generate_copy(body: marketing.CopyRequest, user: Manager) -> dict:
    try:
        return await marketing.generate_copy(get_pool(), user["sub"], body)
    except marketing.MarketingUnavailableError as exc:
        raise HTTPException(503, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc


@router.post("/api/manager/marketing/images")
async def generate_images(body: marketing.ImageRequest, user: Manager) -> dict:
    try:
        return await marketing.generate_images(get_pool(), user["sub"], body)
    except marketing.MarketingUnavailableError as exc:
        raise HTTPException(503, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc


@router.get("/api/media/{image_id}")
async def media(image_id: uuid.UUID) -> Response:
    """Public: adopted images appear on customer pages. IDs are unguessable and content never changes."""
    try:
        async with get_pool().acquire() as conn:
            data, mime = await marketing.read_image(conn, image_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    return Response(data, media_type=mime, headers={"Cache-Control": "public, max-age=31536000, immutable"})
