"""OAuth client registry — fixed, seeded, in-memory cached.

This is offline-first with a known, static set of first-party clients (no
dynamic client registration), so the registry is loaded once from
``oauth_clients`` at startup and served from memory. That also sidesteps
authlib's ``query_client`` being called synchronously (see ``_bridge.py``)
for the hot path: client lookups never touch the database per-request.
"""

from __future__ import annotations

import logging

import asyncpg
import bcrypt
from authlib.oauth2.rfc6749 import ClientMixin
from authlib.oauth2.rfc6749.util import list_to_scope, scope_to_list

logger = logging.getLogger(__name__)


class Client(ClientMixin):
    def __init__(
        self,
        client_id: str,
        client_secret_hash: str,
        allowed_grant_types: list[str],
        allowed_scopes: list[str],
        allowed_audiences: list[str],
        token_endpoint_auth_method: str,
    ):
        self.client_id = client_id
        self.client_secret_hash = client_secret_hash
        self.allowed_grant_types = set(allowed_grant_types)
        self.allowed_scopes = set(allowed_scopes)
        self.allowed_audiences = list(allowed_audiences)
        self.token_endpoint_auth_method = token_endpoint_auth_method

    # ── ClientMixin ────────────────────────────────────────────────

    def get_client_id(self) -> str:
        return self.client_id

    def get_default_redirect_uri(self):
        return None  # no authorization-code/redirect flow in this AS

    def get_allowed_scope(self, scope: str | None) -> str:
        if not scope:
            return ""
        requested = set(scope_to_list(scope))
        return list_to_scope(sorted(requested & self.allowed_scopes))

    def check_redirect_uri(self, redirect_uri: str) -> bool:
        return False  # no authorization-code/redirect flow in this AS

    def check_client_secret(self, client_secret: str) -> bool:
        try:
            return bcrypt.checkpw(client_secret.encode(), self.client_secret_hash.encode())
        except (ValueError, TypeError):
            return False

    def check_endpoint_auth_method(self, method: str, endpoint: str) -> bool:
        if endpoint != "token":
            return True
        return self.token_endpoint_auth_method == method

    def check_response_type(self, response_type: str) -> bool:
        return False  # no authorization-code/implicit flow in this AS

    def check_grant_type(self, grant_type: str) -> bool:
        return grant_type in self.allowed_grant_types


class ClientStore:
    """In-memory client registry, warmed once from ``oauth_clients``."""

    def __init__(self) -> None:
        self._clients: dict[str, Client] = {}

    async def load(self, pool: asyncpg.Pool) -> None:
        rows = await pool.fetch(
            """SELECT client_id, client_secret_hash, allowed_grant_types,
                      allowed_scopes, allowed_audiences, token_endpoint_auth_method
               FROM oauth_clients"""
        )
        clients = {
            row["client_id"]: Client(
                client_id=row["client_id"],
                client_secret_hash=row["client_secret_hash"],
                allowed_grant_types=list(row["allowed_grant_types"]),
                allowed_scopes=list(row["allowed_scopes"]),
                allowed_audiences=list(row["allowed_audiences"]),
                token_endpoint_auth_method=row["token_endpoint_auth_method"],
            )
            for row in rows
        }
        self._clients = clients
        logger.info("auth_server.clients_loaded count=%d", len(clients))

    def get(self, client_id: str) -> Client | None:
        return self._clients.get(client_id)
