"""Service-token acquirer (Phase C: inter-agent client-credentials).

``request_token`` (the AS HTTP call) is monkeypatched throughout — these
tests exercise the acquirer's caching/refresh-skew logic and the
``build_a2a_headers`` mode branch, not the network call itself (that's
covered by ``test_auth_server_integration.py``'s real client-credentials
grant tests). No DB, no LLM.
"""

from __future__ import annotations

import pytest

import shared.oauth.service_client as service_client
from shared.config import settings
from shared.oauth.service_client import acquire_service_token, build_a2a_headers


@pytest.fixture(autouse=True)
def _reset_cache():
    service_client.reset_service_token_cache_for_tests()
    yield
    service_client.reset_service_token_cache_for_tests()


async def test_acquires_and_caches_token(monkeypatch) -> None:
    calls = []

    async def fake_request_token(grant_type, **form):
        calls.append((grant_type, form))
        return {"access_token": "tok-1", "expires_in": 3600}

    monkeypatch.setattr(service_client, "request_token", fake_request_token)

    first = await acquire_service_token("agent:invoke", "ecommerce-agents")
    second = await acquire_service_token("agent:invoke", "ecommerce-agents")

    assert first == "tok-1"
    assert second == "tok-1"
    assert len(calls) == 1  # second call served from cache
    assert calls[0] == ("client_credentials", {"scope": "agent:invoke"})


async def test_distinct_scope_audience_pairs_cached_independently(monkeypatch) -> None:
    issued = iter(["tok-agent", "tok-mcp"])

    async def fake_request_token(grant_type, **form):
        return {"access_token": next(issued), "expires_in": 3600}

    monkeypatch.setattr(service_client, "request_token", fake_request_token)

    agent_token = await acquire_service_token("agent:invoke", "ecommerce-agents")
    mcp_token = await acquire_service_token("mcp:product", "mcp-product")

    assert agent_token == "tok-agent"
    assert mcp_token == "tok-mcp"


async def test_refreshes_after_expiry(monkeypatch) -> None:
    calls = 0

    async def fake_request_token(grant_type, **form):
        nonlocal calls
        calls += 1
        return {"access_token": f"tok-{calls}", "expires_in": 1}

    monkeypatch.setattr(service_client, "request_token", fake_request_token)
    monkeypatch.setattr(service_client, "_REFRESH_SKEW_SECONDS", 0)

    first = await acquire_service_token("agent:invoke", "ecommerce-agents")
    assert first == "tok-1"

    # Force the cached entry to look expired without sleeping in a test.
    cache_key = ("agent:invoke", "ecommerce-agents")
    token, _expires_at = service_client._service_token_cache[cache_key]
    service_client._service_token_cache[cache_key] = (token, 0.0)

    second = await acquire_service_token("agent:invoke", "ecommerce-agents")
    assert second == "tok-2"
    assert calls == 2


async def test_refresh_skew_triggers_early_refresh(monkeypatch) -> None:
    """A token that hasn't technically expired yet, but is within the skew
    window, is refreshed anyway — a concurrent in-flight request must never
    receive a token that expires mid-call."""
    calls = 0

    async def fake_request_token(grant_type, **form):
        nonlocal calls
        calls += 1
        return {"access_token": f"tok-{calls}", "expires_in": 3600}

    monkeypatch.setattr(service_client, "request_token", fake_request_token)

    await acquire_service_token("agent:invoke", "ecommerce-agents")
    cache_key = ("agent:invoke", "ecommerce-agents")
    token, expires_at = service_client._service_token_cache[cache_key]
    # Simulate time passing to just inside the refresh-skew window.
    import time

    service_client._service_token_cache[cache_key] = (
        token,
        time.monotonic() + service_client._REFRESH_SKEW_SECONDS - 1,
    )

    second = await acquire_service_token("agent:invoke", "ecommerce-agents")
    assert second == "tok-2"
    assert calls == 2


async def test_defaults_expires_in_when_as_omits_it(monkeypatch) -> None:
    async def fake_request_token(grant_type, **form):
        return {"access_token": "tok-no-ttl"}  # no expires_in field

    monkeypatch.setattr(service_client, "request_token", fake_request_token)

    token = await acquire_service_token("agent:invoke", "ecommerce-agents")
    assert token == "tok-no-ttl"


# ─────────────────────── build_a2a_headers ───────────────────────


async def test_build_a2a_headers_local_mode_uses_shared_secret(monkeypatch) -> None:
    monkeypatch.setattr(settings, "AUTH_MODE", "local")
    headers = await build_a2a_headers()
    assert headers["x-agent-secret"] == settings.AGENT_SHARED_SECRET
    assert "authorization" not in headers


async def test_build_a2a_headers_oauth_mode_uses_bearer_token(monkeypatch) -> None:
    monkeypatch.setattr(settings, "AUTH_MODE", "oauth")

    async def fake_request_token(grant_type, **form):
        return {"access_token": "svc-tok", "expires_in": 3600}

    monkeypatch.setattr(service_client, "request_token", fake_request_token)

    headers = await build_a2a_headers()
    assert headers["authorization"] == "Bearer svc-tok"
    assert "x-agent-secret" not in headers


async def test_build_a2a_headers_forwards_identity_in_both_modes(monkeypatch) -> None:
    from shared.context import current_session_id, current_user_email, current_user_role

    current_user_email.set("alice@example.com")
    current_user_role.set("admin")
    current_session_id.set("sess-123")
    try:
        monkeypatch.setattr(settings, "AUTH_MODE", "local")
        headers = await build_a2a_headers()
        assert headers["x-user-email"] == "alice@example.com"
        assert headers["x-user-role"] == "admin"
        assert headers["x-session-id"] == "sess-123"
    finally:
        current_user_email.set("")
        current_user_role.set("")
        current_session_id.set("")
