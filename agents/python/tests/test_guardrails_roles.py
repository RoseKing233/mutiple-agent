"""Unit tests for tool-level role enforcement (Track A4). No LLM/DB.

Covers the decorator + guard-clause behavior AND that the decorator composes
under MAF's ``@tool`` without losing the function signature (plan Risk #1).
"""

from __future__ import annotations

import inspect

import pytest
from agent_framework import tool

from shared.config import settings
from shared.context import current_user_role
from shared.guardrails.roles import ensure_role, requires_role


@requires_role("seller", "admin")
async def _sample(x: int) -> dict:
    return {"ok": x}


@pytest.fixture(autouse=True)
def _enable(monkeypatch):
    monkeypatch.setattr(settings, "GUARDRAILS_ENABLED", True)


async def test_allows_listed_role() -> None:
    current_user_role.set("seller")
    assert await _sample(1) == {"ok": 1}


async def test_admin_always_allowed() -> None:
    current_user_role.set("admin")
    assert await _sample(2) == {"ok": 2}


async def test_denies_customer() -> None:
    current_user_role.set("customer")
    out = await _sample(3)
    assert out["error"] == "permission_denied"
    assert "seller" in out["required_roles"]


async def test_denies_missing_role() -> None:
    current_user_role.set("")
    out = await _sample(4)
    assert out["error"] == "permission_denied"


async def test_disabled_bypasses(monkeypatch) -> None:
    monkeypatch.setattr(settings, "GUARDRAILS_ENABLED", False)
    current_user_role.set("customer")
    assert await _sample(5) == {"ok": 5}


def test_decorator_preserves_signature() -> None:
    # functools.wraps keeps name + signature so MAF @tool can introspect.
    assert _sample.__name__ == "_sample"
    assert "x" in inspect.signature(_sample).parameters


def test_composes_under_tool_decorator() -> None:
    @tool(name="sample_tool", description="A sample tool.")
    @requires_role("seller", "admin")
    async def sample_tool(
        x: int,
    ) -> dict:
        return {"ok": x}

    # MAF wraps it into a tool object that still advertises its name and an 'x'
    # parameter in its schema (i.e. the role decorator did not erase the sig).
    assert getattr(sample_tool, "name", None) == "sample_tool"
    blob = repr(getattr(sample_tool, "parameters", sample_tool))
    assert "x" in blob


# ── guard-clause helper ──────────────────────────────────────────────


async def test_ensure_role_allows() -> None:
    current_user_role.set("seller")
    assert ensure_role("seller", "admin", tool="t") is None


async def test_ensure_role_denies() -> None:
    current_user_role.set("customer")
    denied = ensure_role("seller", "admin", tool="t")
    assert denied and denied["error"] == "permission_denied"


async def test_ensure_role_disabled(monkeypatch) -> None:
    monkeypatch.setattr(settings, "GUARDRAILS_ENABLED", False)
    current_user_role.set("customer")
    assert ensure_role("seller", "admin", tool="t") is None
