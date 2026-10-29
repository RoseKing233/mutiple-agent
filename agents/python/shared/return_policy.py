"""Return-window and state-transition rules shared by return entry points."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any

RETURN_WINDOW = timedelta(days=30)

RETURN_TRANSITIONS: dict[str, frozenset[str]] = {
    "requested": frozenset({"approved", "denied"}),
    "approved": frozenset({"shipped_back"}),
    "shipped_back": frozenset({"received"}),
    "received": frozenset({"refunded"}),
    "refunded": frozenset(),
    "denied": frozenset(),
}


def evaluate_return_window(
    *,
    order_created_at: datetime,
    delivered_at: datetime | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    return _evaluate_window(
        window=RETURN_WINDOW,
        order_created_at=order_created_at,
        delivered_at=delivered_at,
        now=now,
    )


def _evaluate_window(
    *,
    window: timedelta,
    order_created_at: datetime,
    delivered_at: datetime | None,
    now: datetime | None,
) -> dict[str, Any]:
    reference_time = delivered_at or order_created_at
    current_time = now or datetime.now(UTC)
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=UTC)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=UTC)

    deadline = reference_time + window
    seconds_remaining = (deadline - current_time).total_seconds()
    days_since = max(0, (current_time - reference_time).days)
    return {
        "eligible": seconds_remaining >= 0,
        "days_since": days_since,
        "days_remaining": max(0, math.ceil(seconds_remaining / 86400)),
        "reference_time": reference_time,
        "deadline": deadline,
        "used_order_date_fallback": delivered_at is None,
    }


def can_transition_return(current_status: str, next_status: str) -> bool:
    return next_status in RETURN_TRANSITIONS.get(current_status, frozenset())
