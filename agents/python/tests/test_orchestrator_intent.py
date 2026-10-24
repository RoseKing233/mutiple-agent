"""Track D4 — orchestrator header construction and identity propagation.

Verifies that call_specialist_agent forwards the correct HTTP headers
(x-agent-secret, x-user-email, x-user-role, x-session-id) when calling a
specialist agent via A2A. No live LLM, no DB, no real HTTP.
"""

from __future__ import annotations

import contextlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import orchestrator.agent as orch_mod
from orchestrator.agent import call_specialist_agent
from shared.config import settings
from shared.context import current_session_id, current_user_email, current_user_role

# ─────────────────────── Helpers ────────────────────────────────────────────


@contextlib.contextmanager
def _noop_span(*args, **kwargs):
    yield


def _capture_client():
    """Build a mock AsyncClient that records the post() call args."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"response": "ok"}
    mock_resp.raise_for_status = MagicMock()

    captured: dict = {}

    async def _post(url, *, json=None, headers=None, **_kw):
        captured["url"] = url
        captured["headers"] = headers or {}
        captured["json"] = json
        return mock_resp

    mock_instance = AsyncMock()
    mock_instance.__aenter__.return_value = mock_instance
    mock_instance.__aexit__.return_value = None
    mock_instance.post = _post

    mock_class = MagicMock(return_value=mock_instance)
    return mock_class, captured


# ─────────────────────── Tests ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_agent_secret_header_is_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orch_mod, "AGENT_REGISTRY", {"product-discovery": "http://pd:8081"})
    monkeypatch.setattr(settings, "AGENT_SHARED_SECRET", "supersecretkey", raising=False)
    current_user_email.set("alice@example.com")
    current_user_role.set("customer")
    current_session_id.set("")

    mock_class, captured = _capture_client()
    with patch.object(orch_mod, "a2a_call_span", _noop_span), patch("orchestrator.agent.httpx.AsyncClient", mock_class):
        await call_specialist_agent(agent_name="product-discovery", message="find speakers")

    assert captured["headers"]["x-agent-secret"] == "supersecretkey"


@pytest.mark.asyncio
async def test_user_identity_forwarded_in_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orch_mod, "AGENT_REGISTRY", {"order-management": "http://om:8082"})
    monkeypatch.setattr(settings, "AGENT_SHARED_SECRET", "test-secret", raising=False)
    current_user_email.set("bob@example.com")
    current_user_role.set("seller")
    current_session_id.set("")

    mock_class, captured = _capture_client()
    with patch.object(orch_mod, "a2a_call_span", _noop_span), patch("orchestrator.agent.httpx.AsyncClient", mock_class):
        await call_specialist_agent(agent_name="order-management", message="list my orders")

    assert captured["headers"]["x-user-email"] == "bob@example.com"
    assert captured["headers"]["x-user-role"] == "seller"


@pytest.mark.asyncio
async def test_session_id_forwarded_in_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orch_mod, "AGENT_REGISTRY", {"pricing-promotions": "http://pp:8083"})
    monkeypatch.setattr(settings, "AGENT_SHARED_SECRET", "test-secret", raising=False)
    current_user_email.set("carol@example.com")
    current_user_role.set("customer")
    current_session_id.set("session-abc-123")

    mock_class, captured = _capture_client()
    with patch.object(orch_mod, "a2a_call_span", _noop_span), patch("orchestrator.agent.httpx.AsyncClient", mock_class):
        await call_specialist_agent(agent_name="pricing-promotions", message="any deals?")

    assert captured["headers"]["x-session-id"] == "session-abc-123"


@pytest.mark.asyncio
async def test_post_targets_message_send_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orch_mod, "AGENT_REGISTRY", {"review-sentiment": "http://rs:8084"})
    monkeypatch.setattr(settings, "AGENT_SHARED_SECRET", "test-secret", raising=False)
    current_user_email.set("dave@example.com")
    current_user_role.set("customer")
    current_session_id.set("")

    mock_class, captured = _capture_client()
    with patch.object(orch_mod, "a2a_call_span", _noop_span), patch("orchestrator.agent.httpx.AsyncClient", mock_class):
        await call_specialist_agent(agent_name="review-sentiment", message="reviews for product-xyz")

    assert captured["url"] == "http://rs:8084/message:send"


@pytest.mark.asyncio
async def test_message_body_forwarded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orch_mod, "AGENT_REGISTRY", {"inventory-fulfillment": "http://inv:8085"})
    monkeypatch.setattr(settings, "AGENT_SHARED_SECRET", "test-secret", raising=False)
    current_user_email.set("eve@example.com")
    current_user_role.set("customer")
    current_session_id.set("")

    mock_class, captured = _capture_client()
    with patch.object(orch_mod, "a2a_call_span", _noop_span), patch("orchestrator.agent.httpx.AsyncClient", mock_class):
        await call_specialist_agent(agent_name="inventory-fulfillment", message="is SKU-999 in stock?")

    assert captured["json"] == {"message": "is SKU-999 in stock?"}
