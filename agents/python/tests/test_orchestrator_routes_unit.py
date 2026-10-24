"""Track D4 — orchestrator call_specialist_agent error-branch coverage.

Tests every non-happy-path branch in call_specialist_agent without a live LLM
or real HTTP. httpx.AsyncClient is replaced by an AsyncMock; a2a_call_span is
replaced by a no-op context manager.

No DB required. No live LLM required.
"""

from __future__ import annotations

import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

import orchestrator.agent as orch_mod
from orchestrator.agent import call_specialist_agent
from shared.config import settings
from shared.context import current_session_id, current_user_email, current_user_role

# ─────────────────────── Helpers ────────────────────────────────────────────


@contextlib.contextmanager
def _noop_span(*args, **kwargs):
    """Drop-in replacement for a2a_call_span in tests."""
    yield


def _mock_client(response_json: dict | None = None, *, raise_exc: Exception | None = None):
    """Build a mock httpx.AsyncClient context manager.

    Returns (mock_class, mock_instance) so tests can inspect the call args.
    """
    mock_resp = MagicMock()
    if response_json is not None:
        mock_resp.json.return_value = response_json
    mock_resp.raise_for_status = MagicMock()  # no-op for success

    mock_instance = AsyncMock()
    mock_instance.__aenter__.return_value = mock_instance
    mock_instance.__aexit__.return_value = None

    if raise_exc is not None:
        mock_instance.post = AsyncMock(side_effect=raise_exc)
    else:
        mock_instance.post = AsyncMock(return_value=mock_resp)

    mock_class = MagicMock(return_value=mock_instance)
    return mock_class, mock_instance


# ─────────────────────── Tests ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_agent_returns_available_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orch_mod, "AGENT_REGISTRY", {"product-discovery": "http://pd:8081"})
    current_user_email.set("u@example.com")
    current_user_role.set("customer")

    result = await call_specialist_agent(
        agent_name="nonexistent-agent",
        message="hello",
    )
    assert "Unknown agent" in result
    assert "product-discovery" in result


@pytest.mark.asyncio
async def test_empty_registry_returns_none_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orch_mod, "AGENT_REGISTRY", {})
    current_user_email.set("u@example.com")
    current_user_role.set("customer")

    result = await call_specialist_agent(agent_name="anything", message="hello")
    assert "none configured" in result


@pytest.mark.asyncio
async def test_success_returns_response_field(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orch_mod, "AGENT_REGISTRY", {"product-discovery": "http://pd:8081"})
    monkeypatch.setattr(settings, "AGENT_SHARED_SECRET", "test-secret", raising=False)
    current_user_email.set("u@example.com")
    current_user_role.set("customer")
    current_session_id.set("sess-1")

    mock_class, _ = _mock_client(response_json={"response": "Here are the headphones."})
    with patch.object(orch_mod, "a2a_call_span", _noop_span), patch("orchestrator.agent.httpx.AsyncClient", mock_class):
        result = await call_specialist_agent(agent_name="product-discovery", message="find headphones")

    assert result == "Here are the headphones."


@pytest.mark.asyncio
async def test_timeout_returns_timeout_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orch_mod, "AGENT_REGISTRY", {"order-management": "http://om:8082"})
    current_user_email.set("u@example.com")
    current_user_role.set("customer")

    mock_class, _ = _mock_client(raise_exc=httpx.TimeoutException("timed out"))
    with patch.object(orch_mod, "a2a_call_span", _noop_span), patch("orchestrator.agent.httpx.AsyncClient", mock_class):
        result = await call_specialist_agent(agent_name="order-management", message="track order")

    assert "took too long" in result
    assert "order-management" in result


@pytest.mark.asyncio
async def test_http_status_error_returns_status_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orch_mod, "AGENT_REGISTRY", {"review-sentiment": "http://rs:8084"})
    current_user_email.set("u@example.com")
    current_user_role.set("customer")

    bad_resp = MagicMock()
    bad_resp.status_code = 503
    exc = httpx.HTTPStatusError("server error", request=MagicMock(), response=bad_resp)

    mock_class, _ = _mock_client(raise_exc=exc)
    with patch.object(orch_mod, "a2a_call_span", _noop_span), patch("orchestrator.agent.httpx.AsyncClient", mock_class):
        result = await call_specialist_agent(agent_name="review-sentiment", message="sentiment please")

    assert "503" in result
    assert "review-sentiment" in result


@pytest.mark.asyncio
async def test_general_exception_returns_failure_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orch_mod, "AGENT_REGISTRY", {"inventory-fulfillment": "http://inv:8085"})
    current_user_email.set("u@example.com")
    current_user_role.set("customer")

    mock_class, _ = _mock_client(raise_exc=RuntimeError("connection refused"))
    with patch.object(orch_mod, "a2a_call_span", _noop_span), patch("orchestrator.agent.httpx.AsyncClient", mock_class):
        result = await call_specialist_agent(agent_name="inventory-fulfillment", message="check stock")

    assert "Failed to reach" in result
    assert "inventory-fulfillment" in result
