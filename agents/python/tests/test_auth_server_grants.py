"""Grant classes — happy/sad paths against real Postgres.

Exercises the callbacks the way authlib actually calls them: synchronously,
from a worker thread, bridged back to the event loop via ``_bridge`` (see
its module docstring). Never mocks the DB or an LLM.
"""

from __future__ import annotations

import asyncio

import asyncpg
import pytest
import pytest_asyncio

import shared.db as shared_db
from auth_server import _bridge
from auth_server.clients import Client, ClientStore
from auth_server.grants import RefreshTokenGrant, ResourceOwnerPasswordCredentialsGrant, hash_token
from shared.jwt_utils import hash_password

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture(autouse=True)
async def _db_pool(clean_db: asyncpg.Pool, monkeypatch: pytest.MonkeyPatch) -> asyncpg.Pool:
    """Inject clean_db into shared.db so the grants' get_pool() calls work
    (they use the repo-standard global pool, same as every other tool)."""
    monkeypatch.setattr(shared_db, "_pool", clean_db)
    return clean_db


async def _seed_user(pool, email="alice@example.com", password="correct-horse", role="customer", is_active=True):
    await pool.execute(
        """INSERT INTO users (email, password_hash, name, role, is_active)
           VALUES ($1, $2, $3, $4, $5)
           ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash""",
        email,
        hash_password(password),
        "Alice Test",
        role,
        is_active,
    )
    return email


async def _seed_client(pool, client_id="test-client", secret="s3cr3t", scopes=None, grants=None, audiences=None):
    scopes = scopes or ["agent:invoke"]
    grants = grants or ["client_credentials", "password", "refresh_token"]
    audiences = audiences or ["ecommerce-agents"]
    secret_hash = hash_password(secret)
    await pool.execute(
        """INSERT INTO oauth_clients
               (client_id, client_secret_hash, client_name, allowed_grant_types, allowed_scopes, allowed_audiences)
           VALUES ($1, $2, $3, $4, $5, $6)
           ON CONFLICT (client_id) DO UPDATE SET client_secret_hash = EXCLUDED.client_secret_hash""",
        client_id,
        secret_hash,
        client_id,
        grants,
        scopes,
        audiences,
    )
    return Client(client_id, secret_hash, grants, scopes, audiences, "client_secret_basic")


@pytest.fixture(autouse=True)
async def _bind_loop():
    """authlib's callbacks run in a worker thread and bridge back here.

    Must be async so it runs inside pytest-asyncio's active event loop —
    a plain sync fixture executes before that loop exists.
    """
    _bridge.bind_main_loop()


class TestClientStore:
    async def test_load_and_get(self, clean_db):
        await _seed_client(clean_db, client_id="product-discovery")
        store = ClientStore()
        await store.load(clean_db)

        client = store.get("product-discovery")
        assert client is not None
        assert client.get_client_id() == "product-discovery"
        assert store.get("does-not-exist") is None

    async def test_check_client_secret(self, clean_db):
        await _seed_client(clean_db, client_id="c1", secret="right-secret")
        store = ClientStore()
        await store.load(clean_db)
        client = store.get("c1")

        assert client.check_client_secret("right-secret") is True
        assert client.check_client_secret("wrong-secret") is False

    async def test_get_allowed_scope_intersects_requested_and_allowed(self, clean_db):
        await _seed_client(clean_db, client_id="c2", scopes=["agent:invoke", "mcp:product"])
        store = ClientStore()
        await store.load(clean_db)
        client = store.get("c2")

        assert client.get_allowed_scope("agent:invoke mcp:inventory") == "agent:invoke"
        assert client.get_allowed_scope("") == ""

    async def test_check_grant_type(self, clean_db):
        await _seed_client(clean_db, client_id="c3", grants=["client_credentials"])
        store = ClientStore()
        await store.load(clean_db)
        client = store.get("c3")

        assert client.check_grant_type("client_credentials") is True
        assert client.check_grant_type("password") is False


class TestResourceOwnerPasswordCredentialsGrant:
    async def test_authenticate_user_success(self, clean_db):
        await _seed_user(clean_db, email="bob@example.com", password="hunter2", role="customer")
        grant = ResourceOwnerPasswordCredentialsGrant.__new__(ResourceOwnerPasswordCredentialsGrant)

        user = await asyncio.to_thread(grant.authenticate_user, "bob@example.com", "hunter2")

        assert user is not None
        assert user.get_user_id() == "bob@example.com"
        assert user.role == "customer"

    async def test_authenticate_user_wrong_password(self, clean_db):
        await _seed_user(clean_db, email="carol@example.com", password="hunter2")
        grant = ResourceOwnerPasswordCredentialsGrant.__new__(ResourceOwnerPasswordCredentialsGrant)

        user = await asyncio.to_thread(grant.authenticate_user, "carol@example.com", "wrong-password")
        assert user is None

    async def test_authenticate_user_unknown_email(self, clean_db):
        grant = ResourceOwnerPasswordCredentialsGrant.__new__(ResourceOwnerPasswordCredentialsGrant)
        user = await asyncio.to_thread(grant.authenticate_user, "nobody@example.com", "irrelevant")
        assert user is None

    async def test_authenticate_user_inactive_account_rejected(self, clean_db):
        await _seed_user(clean_db, email="dave@example.com", password="hunter2", is_active=False)
        grant = ResourceOwnerPasswordCredentialsGrant.__new__(ResourceOwnerPasswordCredentialsGrant)
        user = await asyncio.to_thread(grant.authenticate_user, "dave@example.com", "hunter2")
        assert user is None


class TestRefreshTokenGrant:
    async def test_authenticate_refresh_token_success(self, clean_db):
        await _seed_client(clean_db, client_id="c-refresh")
        raw_token = "a-real-refresh-token-value"
        await clean_db.execute(
            """INSERT INTO oauth_tokens (client_id, subject, token_type, token_hash, scope, expires_at)
               VALUES ($1, $2, 'refresh_token', $3, $4, NOW() + INTERVAL '7 days')""",
            "c-refresh",
            "erin@example.com",
            hash_token(raw_token),
            "api:chat",
        )
        grant = RefreshTokenGrant.__new__(RefreshTokenGrant)

        record = await asyncio.to_thread(grant.authenticate_refresh_token, raw_token)
        assert record is not None
        assert record.client_id == "c-refresh"
        assert record.get_scope() == "api:chat"

    async def test_authenticate_refresh_token_expired_rejected(self, clean_db):
        raw_token = "an-expired-refresh-token"
        await _seed_client(clean_db, client_id="c-expired")
        await clean_db.execute(
            """INSERT INTO oauth_tokens (client_id, subject, token_type, token_hash, scope, expires_at)
               VALUES ($1, $2, 'refresh_token', $3, $4, NOW() - INTERVAL '1 hour')""",
            "c-expired",
            "frank@example.com",
            hash_token(raw_token),
            "api:chat",
        )
        grant = RefreshTokenGrant.__new__(RefreshTokenGrant)

        record = await asyncio.to_thread(grant.authenticate_refresh_token, raw_token)
        assert record is None

    async def test_authenticate_refresh_token_revoked_rejected(self, clean_db):
        raw_token = "a-revoked-refresh-token"
        await _seed_client(clean_db, client_id="c-revoked")
        await clean_db.execute(
            """INSERT INTO oauth_tokens (client_id, subject, token_type, token_hash, scope, expires_at, revoked)
               VALUES ($1, $2, 'refresh_token', $3, $4, NOW() + INTERVAL '7 days', TRUE)""",
            "c-revoked",
            "grace@example.com",
            hash_token(raw_token),
            "api:chat",
        )
        grant = RefreshTokenGrant.__new__(RefreshTokenGrant)

        record = await asyncio.to_thread(grant.authenticate_refresh_token, raw_token)
        assert record is None

    async def test_authenticate_refresh_token_unknown_value_rejected(self, clean_db):
        grant = RefreshTokenGrant.__new__(RefreshTokenGrant)
        record = await asyncio.to_thread(grant.authenticate_refresh_token, "never-issued")
        assert record is None

    async def test_authenticate_user_for_client_credentials_refresh_is_none(self, clean_db):
        """A refresh record with no subject (shouldn't exist in practice —
        client_credentials never issues refresh tokens — but must not
        explode if it ever did) maps to no user, not an error."""
        from auth_server.grants import RefreshTokenRecord

        grant = RefreshTokenGrant.__new__(RefreshTokenGrant)
        record = RefreshTokenRecord(client_id="svc", subject=None, scope="agent:invoke")
        user = await asyncio.to_thread(grant.authenticate_user, record)
        assert user is None

    async def test_revoke_old_credential_is_a_noop(self):
        """Non-rotating grant: the existing refresh token must stay valid."""
        from auth_server.grants import RefreshTokenRecord

        grant = RefreshTokenGrant.__new__(RefreshTokenGrant)
        record = RefreshTokenRecord(client_id="c", subject="x@example.com", scope="api:chat")
        assert grant.revoke_old_credential(record) is None
