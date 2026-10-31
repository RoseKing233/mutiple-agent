"""Tool-level role authorization (Track A — guardrails).

Adds the missing *authorization* layer: today destructive tools have an
``approval_mode="always_require"`` human-approval gate and data-layer ownership
filters (``WHERE u.email = $2``), but nothing checks the caller's *role* before
the tool runs. ``requires_role`` closes that gap — it runs first (authorize),
then MAF's approval gate runs (confirm).

Identity is read from the ``current_user_role`` ContextVar (set by the auth
middleware / route deps) — never passed as a function argument, per repo
convention. Roles are explicit: admin does not inherit customer or manager
permissions. Authorization is always enforced, independently of optional
GUARDRAILS_ENABLED content-safety controls.

Two forms are provided:

- :func:`requires_role` — decorator for new tools (placed *under* ``@tool`` so
  MAF still introspects the original signature via ``functools.wraps``).
- :func:`ensure_role` — guard-clause helper returning a denial payload (or
  ``None``) for retrofitting existing tool bodies without re-ordering decorators.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from shared.context import current_user_role

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


def _denial(allowed: set[str], tool: str, role: str) -> dict[str, Any]:
    required = sorted(allowed)
    logger.warning(
        "guardrails.role_denied tool=%s role=%s required=%s",
        tool,
        role or "<none>",
        required,
    )
    return {
        "error": "permission_denied",
        "message": (
            f"You don't have permission to perform this action. It requires one of these roles: {', '.join(required)}."
        ),
        "required_roles": required,
    }


def ensure_role(*roles: str, tool: str = "tool") -> dict[str, Any] | None:
    """Return a denial payload if the current role is not authorized, else None.

    Use as a guard clause at the top of a tool body::

        denied = ensure_role("store_manager", tool="get_store_products")
        if denied:
            return denied
    """
    allowed = {r.lower() for r in roles}
    role = (current_user_role.get() or "").lower()
    if role in allowed:
        return None
    return _denial(allowed, tool, role)


def requires_role(*roles: str) -> Callable[[F], F]:
    """Decorator: deny the call (structured payload) unless the role is allowed.

    Place directly under ``@tool`` so MAF introspects the wrapped function's
    real signature (``functools.wraps`` exposes ``__wrapped__`` /
    ``__annotations__``)::

        @tool(name="get_my_products", description="...")
        @requires_role("store_manager")
        async def get_my_products(...): ...
    """
    allowed = {r.lower() for r in roles}

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            role = (current_user_role.get() or "").lower()
            if role not in allowed:
                return _denial(allowed, getattr(fn, "__name__", "tool"), role)
            return await fn(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator
