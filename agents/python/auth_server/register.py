"""RFC 7591 dynamic client registration — the business logic (validation +
persistence), separate from the HTTP route wiring in ``main.py``.

Gated behind ``settings.AUTH_ALLOW_DYNAMIC_REGISTRATION`` (off by default —
this app's client registry is otherwise fixed/seeded, see ``clients.py``'s
own module docstring). When enabled, a caller must still present a bearer
token scoped ``client:register`` (verified in ``main.py`` before this module
is ever reached); this module only handles what happens after that check
passes.

Deliberately narrow: registered clients get ``client_credentials`` only (no
``password``/``refresh_token`` — this AS's interactive-login clients are
first-party and fixed) and are capped to the two MCP read scopes. Nothing
here can mint a client that could ever request ``agent:invoke``, ``api:chat``,
or ``client:register`` itself.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass

import asyncpg
from authlib.common.security import generate_token

from auth_server.token import _scope_audience_map
from shared.config import settings
from shared.jwt_utils import hash_password

REGISTRABLE_SCOPES = frozenset(
    {
        settings.MCP_PRODUCT_REQUIRED_SCOPE,
        settings.MCP_INVENTORY_REQUIRED_SCOPE,
    }
)


@dataclass
class RegistrationError(Exception):
    """Carries an RFC 7591-shaped error: ``{"error": ..., "error_description": ...}``."""

    status: int
    error: str
    description: str

    def to_body(self) -> dict:
        return {"error": self.error, "error_description": self.description}


def validate_registration_request(body: dict) -> tuple[str, list[str]]:
    """Validate a registration request body.

    Returns ``(client_name, scopes)`` on success. Raises
    ``RegistrationError`` (400, ``invalid_client_metadata``) on any
    violation — unknown scope, missing name, an unsupported grant type, or
    a redirect-based flow this AS doesn't support.
    """
    client_name = body.get("client_name")
    if not isinstance(client_name, str) or not client_name.strip():
        raise RegistrationError(400, "invalid_client_metadata", "client_name is required")

    raw_scope = body.get("scope")
    if not isinstance(raw_scope, str) or not raw_scope.strip():
        raise RegistrationError(400, "invalid_client_metadata", "scope is required")
    requested = raw_scope.split()
    unknown = [s for s in requested if s not in REGISTRABLE_SCOPES]
    if unknown:
        raise RegistrationError(
            400,
            "invalid_client_metadata",
            f"scope(s) not registrable via this endpoint: {', '.join(unknown)}",
        )

    grant_types = body.get("grant_types")
    if grant_types is not None and list(grant_types) != ["client_credentials"]:
        raise RegistrationError(
            400,
            "invalid_client_metadata",
            "grant_types must be exactly ['client_credentials'] — this AS supports no redirect flow",
        )

    if body.get("redirect_uris"):
        raise RegistrationError(
            400,
            "invalid_client_metadata",
            "redirect_uris is not supported — this AS has no authorization-code/redirect flow",
        )

    return client_name.strip(), sorted(requested)


async def create_client(pool: asyncpg.Pool, client_name: str, scopes: list[str]) -> tuple[str, str]:
    """Generate, hash, and persist a new client. Returns ``(client_id, plaintext_secret)``.

    The plaintext secret is returned exactly once — only the bcrypt hash is
    stored, matching every other client in ``oauth_clients``.
    """
    client_id = f"ext-{secrets.token_hex(8)}"
    client_secret = generate_token(48)
    secret_hash = hash_password(client_secret)

    audience_map = _scope_audience_map()
    audiences = sorted({aud for s in scopes if (aud := audience_map.get(s))})

    await pool.execute(
        """INSERT INTO oauth_clients
               (client_id, client_secret_hash, client_name, allowed_grant_types,
                allowed_scopes, allowed_audiences, token_endpoint_auth_method)
           VALUES ($1, $2, $3, $4, $5, $6, $7)""",
        client_id,
        secret_hash,
        client_name,
        ["client_credentials"],
        scopes,
        audiences,
        "client_secret_basic",
    )
    return client_id, client_secret
