"""Narrow first-tool policy for explicit, order-specific cancellation requests."""

from __future__ import annotations

import re

_ORDER_ID = re.compile(r"\b[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}\b", re.IGNORECASE)
_CANCEL_REQUEST = re.compile(
    r"\b(?:please\s+)?cancel\b"
    r"|\b(?:want|would like|need|request(?:ing)?)\s+to\s+cancel\b"
    r"|(?:请|帮我|为.{1,24}?)(?:尽快)?(?:取消|撤销)"
    r"|(?:想要|希望|要求|需要)(?:帮忙)?(?:取消|撤销)"
    r"|(?:没|未|没有)取消.{0,30}(?:就|请|帮我)?取消",
    re.IGNORECASE,
)
_CANCEL_NEGATION = re.compile(
    r"\b(?:do not|don't|never|should not|shouldn't)\s+cancel\b"
    r"|(?:不要|无需|不需要|不用|别)(?:帮我)?(?:取消|撤销)",
    re.IGNORECASE,
)
_STATUS_ONLY = re.compile(
    r"\b(?:is|was|has|have)\b.{0,45}\b(?:cancelled|canceled)\??"
    r"|.{0,20}(?:订单)?(?:有没有|是否|是不是)(?:已经)?(?:取消|撤销)(?:了)?(?:吗|没有)?",
    re.IGNORECASE,
)


def required_order_tool(message: str, agent_name: str, role: str) -> str | None:
    """Require cancel_order only for an authorized role and explicit order UUID."""
    if agent_name != "order-management" or role not in {"customer", "seller", "admin"}:
        return None
    if not _ORDER_ID.search(message):
        return None

    actionable = _CANCEL_NEGATION.sub("", message)
    actionable = _STATUS_ONLY.sub("", actionable)
    if _CANCEL_REQUEST.search(actionable):
        return "cancel_order"
    return None
