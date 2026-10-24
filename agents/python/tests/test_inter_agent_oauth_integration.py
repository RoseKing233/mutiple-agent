"""Phase C integration: a real AS-issued service token authenticating a
real ``AgentAuthMiddleware`` inter-agent request.

Uses the same ``OAuthAuthorizationServer`` direct-construction harness as
``test_auth_server_integration.py`` (real testcontainers Postgres via
``clean_db``, real authlib grant machinery) to mint genuine RS256 tokens,
then feeds them through the real ``RS256Verifier`` (JWKS fetch monkeypatched
to the in-process AS's own signing key, not a real network call — same
convention as ``test_rs256_verifier.py``) and the real
``AgentAuthMiddleware``. No stubbed verifier here — this is the thing the
stubbed tests in ``test_auth_identity_validation.py`` assume works.
"""

from __future__ import annotations

import asyncio

import asyncpg
import httpx
import pytest
import pytest_asyncio
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

import shared.db as shared_db
from auth_server import _bridge, keys
from auth_server.clients import ClientStore
from auth_server.server import OAuthAuthorizationServer
from shared.auth import AgentAuthMiddleware
from shared.config import settings
from shared.context import current_session_id, current_user_email, current_user_role
from shared.oauth.verifier import RS256Verifier

pytestmark = pytest.mark.integration

ISSUER = "http://test-auth-server"


@pytest_asyncio.fixture(autouse=True)
async def _db_pool(clean_db: asyncpg.Pool, monkeypatch: pytest.MonkeyPatch) -> asyncpg.Pool:
    monkeypatch.setattr(shared_db, "_pool", clean_db)
    return clean_db


@pytest.fixture(autouse=True)
async def _bind_loop():
    _bridge.bind_main_loop()


async def _seed_client(pool, client_id, secret, grants, scopes, audiences):
    from shared.jwt_utils import hash_password

    await pool.execute(
        """INSERT INTO oauth_clients
               (client_id, client_secret_hash, client_name, allowed_grant_types, allowed_scopes, allowed_audiences)
           VALUES ($1, $2, $3, $4, $5, $6)""",
        client_id,
        hash_password(secret),
        client_id,
        grants,
        scopes,
        audiences,
    )


def _basic_auth_header(client_id: str, secret: str) -> httpx.Headers:
    import base64

    token = base64.b64encode(f"{client_id}:{secret}".encode()).decode()
    return httpx.Headers({"Authorization": f"Basic {token}"})


@pytest.fixture
async def server(clean_db):
    kid, signing_key = await keys.ensure_active_key(clean_db)
    store = ClientStore()
    await store.load(clean_db)
    srv = OAuthAuthorizationServer(client_store=store, pool=clean_db, issuer=ISSUER, kid=kid, signing_key=signing_key)
    return srv, signing_key


@pytest.fixture
def verifier(server, monkeypatch):
    """A real ``RS256Verifier`` whose JWKS fetch is pointed at the in-process
    AS's own signing key — no real network call, matching
    ``test_rs256_verifier.py``'s established convention."""
    _srv, signing_key = server
    monkeypatch.setattr(settings, "AUTH_SERVER_ISSUER", ISSUER)
    monkeypatch.setattr(settings, "AUTH_AGENT_AUDIENCE", "ecommerce-agents")
    monkeypatch.setattr(settings, "AUTH_ORCH_AUDIENCE", "ecommerce-orchestrator")
    v = RS256Verifier()
    public_jwks = {"keys": [signing_key.as_dict(private=False)]}
    monkeypatch.setattr(v._jwks_client, "fetch_data", lambda: public_jwks)
    monkeypatch.setattr(settings, "AUTH_MODE", "oauth")
    monkeypatch.setattr("shared.factory.get_token_verifier", lambda: v)
    return v


async def _ok(request):
    return JSONResponse(
        {
            "email": current_user_email.get(),
            "role": current_user_role.get(),
            "session_id": current_session_id.get(),
        }
    )


def _client() -> TestClient:
    app = Starlette(routes=[Route("/x", _ok, methods=["POST"])])
    app.add_middleware(AgentAuthMiddleware, agent_name="product-discovery")
    return TestClient(app)


async def _issue_token(clean_db, srv, client_id, secret, grants, scopes, audiences, scope):
    await _seed_client(clean_db, client_id, secret, grants, scopes, audiences)
    await srv.client_store.load(clean_db)
    status, body, _headers = await asyncio.to_thread(
        srv.handle_token_request,
        {"grant_type": "client_credentials", "scope": scope},
        _basic_auth_header(client_id, secret),
    )
    assert status == 200, body
    return body["access_token"]


async def test_real_service_token_authenticates_inter_agent_call(clean_db, server, verifier):
    srv, _signing_key = server
    token = await _issue_token(
        clean_db,
        srv,
        "product-discovery",
        "topsecret",
        ["client_credentials"],
        ["agent:invoke"],
        ["ecommerce-agents"],
        "agent:invoke",
    )

    resp = _client().post(
        "/x",
        headers={
            "Authorization": f"Bearer {token}",
            "x-user-email": "alice@example.com",
            "x-user-role": "admin",
            "x-session-id": "sess-1",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "alice@example.com"
    assert body["role"] == "admin"
    assert body["session_id"] == "sess-1"


async def test_real_service_token_with_no_user_headers_defaults_to_system(clean_db, server, verifier):
    srv, _signing_key = server
    token = await _issue_token(
        clean_db,
        srv,
        "product-discovery",
        "topsecret",
        ["client_credentials"],
        ["agent:invoke"],
        ["ecommerce-agents"],
        "agent:invoke",
    )

    resp = _client().post("/x", headers={"Authorization": f"Bearer {token}"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == "system"
    assert body["role"] == "system"


async def test_wrong_audience_token_rejected(clean_db, server, verifier):
    """A real, validly-signed token issued for the orchestrator's own
    api:chat scope (aud=ecommerce-orchestrator) must not authenticate an
    inter-agent call expecting agent:invoke/ecommerce-agents."""
    srv, _signing_key = server
    token = await _issue_token(
        clean_db,
        srv,
        "orchestrator",
        "orch-secret",
        ["client_credentials"],
        ["api:chat"],
        ["ecommerce-orchestrator"],
        "api:chat",
    )

    resp = _client().post("/x", headers={"Authorization": f"Bearer {token}", "x-user-email": "alice@example.com"})
    assert resp.status_code == 401


async def test_spoofed_role_rejected_under_strict_identity(clean_db, server, verifier, monkeypatch):
    srv, _signing_key = server
    monkeypatch.setattr(settings, "GUARDRAILS_STRICT_IDENTITY", True)
    token = await _issue_token(
        clean_db,
        srv,
        "product-discovery",
        "topsecret",
        ["client_credentials"],
        ["agent:invoke"],
        ["ecommerce-agents"],
        "agent:invoke",
    )

    resp = _client().post(
        "/x",
        headers={
            "Authorization": f"Bearer {token}",
            "x-user-email": "alice@example.com",
            "x-user-role": "superadmin",
        },
    )
    assert resp.status_code == 401


async def test_agent_secret_rejected_when_oauth_mode_active(clean_db, server, verifier):
    """Retirement guard: even a correct shared secret is refused once
    AUTH_MODE=oauth — the acquirer/service-token path is the only door."""
    resp = _client().post("/x", headers={"x-agent-secret": settings.AGENT_SHARED_SECRET})
    assert resp.status_code == 401
