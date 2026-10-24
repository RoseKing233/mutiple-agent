"""Tests for forwarded-identity validation on the inter-agent path (Track A5).

Pure helper tests plus a Starlette integration test exercising the
observe-vs-strict behavior. No LLM; no DB.
"""

from __future__ import annotations

import jwt
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

import shared.factory as factory_module
from shared.auth import AgentAuthMiddleware, _identity_anomaly
from shared.config import settings


def test_identity_anomaly_accepts_valid() -> None:
    assert _identity_anomaly("alice@example.com", "customer") is None
    assert _identity_anomaly("alice@example.com", "seller") is None
    assert _identity_anomaly("alice@example.com", "admin") is None
    assert _identity_anomaly("system", "system") is None


def test_identity_anomaly_flags_unknown_role() -> None:
    assert _identity_anomaly("alice@example.com", "superadmin") == "unknown_role:superadmin"


def test_identity_anomaly_flags_malformed_email() -> None:
    assert _identity_anomaly("not-an-email", "customer") == "malformed_email"


async def _ok(request):
    return JSONResponse({"ok": True})


def _client() -> TestClient:
    app = Starlette(routes=[Route("/x", _ok, methods=["POST"])])
    app.add_middleware(AgentAuthMiddleware, agent_name="test")
    return TestClient(app)


def _headers(role: str = "customer", email: str = "alice@example.com") -> dict:
    return {
        "x-agent-secret": settings.AGENT_SHARED_SECRET,
        "x-user-email": email,
        "x-user-role": role,
    }


def test_valid_forwarded_identity_passes() -> None:
    assert _client().post("/x", headers=_headers()).status_code == 200


def test_spoofed_role_allowed_when_not_strict(monkeypatch) -> None:
    monkeypatch.setattr(settings, "GUARDRAILS_STRICT_IDENTITY", False)
    resp = _client().post("/x", headers=_headers(role="superadmin"))
    assert resp.status_code == 200  # observe-only: logged, not blocked


def test_spoofed_role_rejected_when_strict(monkeypatch) -> None:
    monkeypatch.setattr(settings, "GUARDRAILS_STRICT_IDENTITY", True)
    resp = _client().post("/x", headers=_headers(role="superadmin"))
    assert resp.status_code == 401


def test_wrong_agent_secret_rejected() -> None:
    resp = _client().post("/x", headers={"x-agent-secret": "wrong-secret"})
    assert resp.status_code == 401


class _StubVerifier:
    """Stand-in for RS256Verifier — these exercise the middleware's oauth-mode
    branch, not the verifier itself (see test_rs256_verifier.py). Records the
    audience/scope it was asked to validate so tests can lock in exactly what
    the inter-agent path requests."""

    def __init__(self, payload=None, error=None):
        self._payload = payload
        self._error = error
        self.calls: list[tuple[str, str | None]] = []

    def decode(self, token, *, audience, required_scope=None):
        self.calls.append((audience, required_scope))
        if self._error is not None:
            raise self._error
        return self._payload


def test_oauth_mode_agent_secret_rejected_outright(monkeypatch) -> None:
    """oauth mode retires the shared secret — bearing it is a hard 401, not
    a silent fall-through to the service-token path."""
    monkeypatch.setattr(settings, "AUTH_MODE", "oauth")
    resp = _client().post("/x", headers={"x-agent-secret": settings.AGENT_SHARED_SECRET})
    assert resp.status_code == 401


def test_oauth_mode_accepts_valid_service_token(monkeypatch) -> None:
    """Inter-agent oauth path: service token proves the caller, but identity
    comes from forwarded x-user-* headers — not from the token payload."""
    monkeypatch.setattr(settings, "AUTH_MODE", "oauth")
    stub = _StubVerifier(payload={"scope": "agent:invoke"})
    monkeypatch.setattr(factory_module, "get_token_verifier", lambda: stub)

    resp = _client().post(
        "/x",
        headers={
            "Authorization": "Bearer service-token",
            "x-user-email": "alice@example.com",
            "x-user-role": "admin",
        },
    )
    assert resp.status_code == 200
    assert stub.calls == [(settings.AUTH_AGENT_AUDIENCE, "agent:invoke")]


def test_oauth_mode_no_forwarded_headers_defaults_to_system(monkeypatch) -> None:
    """System/health flows carry a service token with no x-user-* headers."""
    monkeypatch.setattr(settings, "AUTH_MODE", "oauth")
    stub = _StubVerifier(payload={"scope": "agent:invoke"})
    monkeypatch.setattr(factory_module, "get_token_verifier", lambda: stub)

    resp = _client().post("/x", headers={"Authorization": "Bearer service-token"})
    assert resp.status_code == 200


def test_oauth_mode_spoofed_role_rejected_when_strict(monkeypatch) -> None:
    monkeypatch.setattr(settings, "AUTH_MODE", "oauth")
    monkeypatch.setattr(settings, "GUARDRAILS_STRICT_IDENTITY", True)
    stub = _StubVerifier(payload={"scope": "agent:invoke"})
    monkeypatch.setattr(factory_module, "get_token_verifier", lambda: stub)

    resp = _client().post(
        "/x",
        headers={
            "Authorization": "Bearer service-token",
            "x-user-email": "alice@example.com",
            "x-user-role": "superadmin",
        },
    )
    assert resp.status_code == 401


def test_oauth_mode_rejects_invalid_token(monkeypatch) -> None:
    monkeypatch.setattr(settings, "AUTH_MODE", "oauth")
    monkeypatch.setattr(factory_module, "get_token_verifier", lambda: _StubVerifier(error=jwt.InvalidTokenError("bad")))
    resp = _client().post("/x", headers={"Authorization": "Bearer whatever"})
    assert resp.status_code == 401


def test_oauth_mode_rejects_expired_token(monkeypatch) -> None:
    monkeypatch.setattr(settings, "AUTH_MODE", "oauth")
    monkeypatch.setattr(
        factory_module,
        "get_token_verifier",
        lambda: _StubVerifier(error=jwt.ExpiredSignatureError("expired")),
    )
    resp = _client().post("/x", headers={"Authorization": "Bearer whatever"})
    assert resp.status_code == 401
