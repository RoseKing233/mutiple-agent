"""Assert which order actions execute after policy checks and which need admin review."""

from __future__ import annotations

import pytest

# ─────────────────────── Tool inventory ──────────────────────────


def _always_approval_tools():
    """Lazy import so collection doesn't trip the prod-fail-fast guard."""
    from inventory_fulfillment.tools import place_backorder
    from order_management.tools import modify_order

    return [
        ("modify_order", modify_order),
        ("place_backorder", place_backorder),
    ]


def _customer_order_tools():
    from order_management.tools import cancel_order
    from shared.tools.return_tools import initiate_return, process_refund

    return [
        ("cancel_order", cancel_order),
        ("initiate_return", initiate_return),
        ("process_refund", process_refund),
    ]


def _read_only_tools():
    from order_management.tools import get_order_details, get_user_orders
    from shared.tools.return_tools import check_return_eligibility, get_return_status

    return [
        ("get_user_orders", get_user_orders),
        ("get_order_details", get_order_details),
        ("check_return_eligibility", check_return_eligibility),
        ("get_return_status", get_return_status),
    ]


# ─────────────────────── Assertions ───────────────────────────────


@pytest.mark.parametrize("name,tool", _always_approval_tools())
def test_admin_sensitive_tool_requires_approval(name: str, tool) -> None:
    assert tool.approval_mode == "always_require", (
        f"{name} must remain gated because it requires admin review."
    )


@pytest.mark.parametrize("name,tool", _customer_order_tools())
def test_eligible_customer_order_actions_can_execute_without_global_approval(name: str, tool) -> None:
    assert tool.approval_mode == "never_require", (
        f"{name} performs its own ownership and eligibility checks; "
        "eligible refunds submit a separate admin approval request."
    )


def test_customer_order_actions_are_not_in_the_unconditional_hitl_gate() -> None:
    from shared.hitl import HITL_GATED_TOOLS

    assert {"cancel_order", "initiate_return", "process_refund"}.isdisjoint(HITL_GATED_TOOLS)


@pytest.mark.parametrize("name,tool", _read_only_tools())
def test_read_only_tool_does_not_require_approval(name: str, tool) -> None:
    assert tool.approval_mode == "never_require", (
        f"{name} is a lookup tool; gating it behind approval would make the "
        "chat UX unbearable. If you need to escalate it, do so via the "
        "ECommerceContextProvider, not approval_mode."
    )
