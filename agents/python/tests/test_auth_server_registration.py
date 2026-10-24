"""RFC 7591 dynamic client registration (`POST /oauth/register`) — gated,
scoped, off by default.

Uses the same ``OAuthAuthorizationServer`` direct-construction harness as
``test_auth_server_integration.py``/``test_mcp_oauth_integration.py`` (real
testcontainers Postgres via ``clean_db``, real authlib grant machinery) to
mint a genuine ``client:register``-scoped token, then drives the real
Starlette route in ``auth_server.main`` via ``httpx.AsyncClient`` +
``ASGITransport`` (bypassing the app's own ``lifespan`` — same reasoning as
the other auth-server integration tests: it reads the process-wide
``shared.config.settings`` singleton, so the module-level globals
(``main._server``, ``shared.db._pool``) are wired directly instead).
"""

from __future__ import annotations

import asyncio

import asyncpg
import bcrypt
import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import auth_server.main as main
import shared.db as shared_db
from auth_server import _bridge, keys
from auth_server.clients import ClientStore
from auth_server.server import OAuthAuthorizationServer
from shared.config import settings
from shared.jwt_utils import hash_password

pytestmark = pytest.mark.integration

ISSUER = "http://test-auth-server"


@pytest_asyncio.fixture(autouse=True)
async def _db_pool(clean_db: asyncpg.Pool, monkeypatch: pytest.MonkeyPatch) -> asyncpg.Pool:
    monkeypatch.setattr(shared_db, "_pool", clean_db)
    return clean_db


@pytest.fixture(autouse=True)
async def _bind_loop():
    _bridge.bind_main_loop()


@pytest.fixture(autouse=True)
def _issuer(monkeypatch: pytest.MonkeyPatch) -> None:
    # RS256Verifier.decode() checks settings.AUTH_SERVER_ISSUER against the
    # token's real `iss` claim, which comes from the `server` fixture's own
    # issuer= param below — keep them in sync.
    monkeypatch.setattr(settings, "AUTH_SERVER_ISSUER", ISSUER)


async def _seed_client(pool, client_id, secret, grants, scopes, audiences):
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
async def server(clean_db, monkeypatch: pytest.MonkeyPatch):
    """Real OAuthAuthorizationServer, wired into the real Starlette app's
    module-level globals (bypassing lifespan)."""
    kid, signing_key = await keys.ensure_active_key(clean_db)
    store = ClientStore()
    await store.load(clean_db)
    srv = OAuthAuthorizationServer(client_store=store, pool=clean_db, issuer=ISSUER, kid=kid, signing_key=signing_key)
    monkeypatch.setattr(main, "_server", srv)
    # Registration-token verification is entirely in-process against this
    # signing key (see main.py's _verify_registration_token) — no JWKS/HTTP
    # fetch to stub, unlike every other resource server's verifier.
    monkeypatch.setattr(main, "_signing_key", signing_key)

    return srv, signing_key


async def _mint_token(srv, client_id: str, secret: str, scope: str) -> str:
    status, body, _headers = await asyncio.to_thread(
        srv.handle_token_request,
        {"grant_type": "client_credentials", "scope": scope},
        _basic_auth_header(client_id, secret),
    )
    assert status == 200, body
    return body["access_token"]


@pytest_asyncio.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as c:
        yield c


async def test_disabled_by_default(client, server) -> None:
    resp = await client.post("/oauth/register", json={"client_name": "x", "scope": "mcp:product"})
    assert resp.status_code == 403


async def test_missing_token_rejected(client, server, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "AUTH_ALLOW_DYNAMIC_REGISTRATION", True)
    resp = await client.post("/oauth/register", json={"client_name": "x", "scope": "mcp:product"})
    assert resp.status_code == 401
    assert "WWW-Authenticate" in resp.headers


async def test_wrong_scope_token_rejected(client, server, clean_db, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "AUTH_ALLOW_DYNAMIC_REGISTRATION", True)
    srv, _ = server
    await _seed_client(
        clean_db, "product-discovery", "topsecret", ["client_credentials"], ["agent:invoke"], ["ecommerce-agents"]
    )
    await srv.client_store.load(clean_db)
    token = await _mint_token(srv, "product-discovery", "topsecret", "agent:invoke")

    resp = await client.post(
        "/oauth/register",
        json={"client_name": "x", "scope": "mcp:product"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 401


async def test_valid_registration_full_round_trip(client, server, clean_db, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "AUTH_ALLOW_DYNAMIC_REGISTRATION", True)
    srv, _ = server
    await _seed_client(
        clean_db,
        "auth-admin",
        "admin-secret",
        ["client_credentials"],
        ["client:register"],
        ["ecommerce-auth-server"],
    )
    await srv.client_store.load(clean_db)
    reg_token = await _mint_token(srv, "auth-admin", "admin-secret", "client:register")

    resp = await client.post(
        "/oauth/register",
        json={"client_name": "Third-Party MCP Client", "scope": "mcp:product"},
        headers={"Authorization": f"Bearer {reg_token}"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["client_id"].startswith("ext-")
    assert body["scope"] == "mcp:product"
    assert body["grant_types"] == ["client_credentials"]
    assert body["client_secret_expires_at"] == 0

    # The stored hash matches the returned plaintext secret.
    row = await clean_db.fetchrow(
        "SELECT client_secret_hash, allowed_audiences FROM oauth_clients WHERE client_id = $1", body["client_id"]
    )
    assert row is not None
    assert bcrypt.checkpw(body["client_secret"].encode(), row["client_secret_hash"].encode())
    assert list(row["allowed_audiences"]) == ["mcp-product"]

    # Full round trip: the newly-registered client can immediately acquire a
    # real, correctly-scoped token from the same live AS.
    await srv.client_store.load(clean_db)
    new_token = await _mint_token(srv, body["client_id"], body["client_secret"], "mcp:product")
    assert new_token


async def test_non_registrable_scope_rejected(client, server, clean_db, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "AUTH_ALLOW_DYNAMIC_REGISTRATION", True)
    srv, _ = server
    await _seed_client(
        clean_db,
        "auth-admin",
        "admin-secret",
        ["client_credentials"],
        ["client:register"],
        ["ecommerce-auth-server"],
    )
    await srv.client_store.load(clean_db)
    reg_token = await _mint_token(srv, "auth-admin", "admin-secret", "client:register")

    resp = await client.post(
        "/oauth/register",
        json={"client_name": "x", "scope": "agent:invoke"},
        headers={"Authorization": f"Bearer {reg_token}"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_client_metadata"


async def test_missing_client_name_rejected(client, server, clean_db, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "AUTH_ALLOW_DYNAMIC_REGISTRATION", True)
    srv, _ = server
    await _seed_client(
        clean_db,
        "auth-admin",
        "admin-secret",
        ["client_credentials"],
        ["client:register"],
        ["ecommerce-auth-server"],
    )
    await srv.client_store.load(clean_db)
    reg_token = await _mint_token(srv, "auth-admin", "admin-secret", "client:register")

    resp = await client.post(
        "/oauth/register",
        json={"scope": "mcp:product"},
        headers={"Authorization": f"Bearer {reg_token}"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_client_metadata"


async def test_bad_grant_types_rejected(client, server, clean_db, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "AUTH_ALLOW_DYNAMIC_REGISTRATION", True)
    srv, _ = server
    await _seed_client(
        clean_db,
        "auth-admin",
        "admin-secret",
        ["client_credentials"],
        ["client:register"],
        ["ecommerce-auth-server"],
    )
    await srv.client_store.load(clean_db)
    reg_token = await _mint_token(srv, "auth-admin", "admin-secret", "client:register")

    resp = await client.post(
        "/oauth/register",
        json={"client_name": "x", "scope": "mcp:product", "grant_types": ["authorization_code"]},
        headers={"Authorization": f"Bearer {reg_token}"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_client_metadata"
