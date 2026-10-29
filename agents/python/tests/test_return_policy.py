from __future__ import annotations

from datetime import UTC, datetime, timedelta

from shared.return_policy import (
    can_transition_return,
    evaluate_return_window,
)


def test_return_window_includes_exactly_thirty_days_after_delivery() -> None:
    delivered_at = datetime(2026, 1, 1, tzinfo=UTC)
    result = evaluate_return_window(
        order_created_at=delivered_at - timedelta(days=10),
        delivered_at=delivered_at,
        now=delivered_at + timedelta(days=30),
    )

    assert result["eligible"] is True
    assert result["days_remaining"] == 0
    assert result["used_order_date_fallback"] is False


def test_return_window_expires_after_thirty_days_and_uses_order_date_fallback() -> None:
    created_at = datetime(2025, 12, 1, tzinfo=UTC)
    result = evaluate_return_window(
        order_created_at=created_at,
        delivered_at=None,
        now=created_at + timedelta(days=31),
    )

    assert result["eligible"] is False
    assert result["days_since"] == 31
    assert result["used_order_date_fallback"] is True


def test_return_state_machine_rejects_skipped_or_repeated_transitions() -> None:
    assert can_transition_return("requested", "approved")
    assert can_transition_return("requested", "denied")
    assert can_transition_return("approved", "shipped_back")
    assert can_transition_return("shipped_back", "received")
    assert can_transition_return("received", "refunded")
    assert not can_transition_return("requested", "refunded")
    assert not can_transition_return("approved", "received")
    assert not can_transition_return("refunded", "refunded")
    assert not can_transition_return("denied", "approved")
