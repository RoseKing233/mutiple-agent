"""RSA signing-key bootstrap and JWKS serving for the self-hosted auth-server.

On first boot (no active row in ``oauth_signing_keys``) a new RSA keypair is
generated and persisted — the public JWK plus a private PEM, encrypted at
rest when ``AUTH_SIGNING_KEY_ENCRYPTION_KEY`` is set (required outside
development, see ``docs/security-guide.md``). Every later boot reuses the
existing active key so already-issued tokens keep validating. Rotation
(inserting a new active key while retaining the old one in the JWKS until
its longest-lived token expires) is a documented follow-up, not implemented
here — there is always exactly one active key today.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging

import asyncpg
from cryptography.fernet import Fernet, InvalidToken
from joserfc.jwk import RSAKey

from shared.config import settings

logger = logging.getLogger(__name__)

_active_kid: str | None = None
_active_key: RSAKey | None = None


def _fernet_key_from(secret: str) -> bytes:
    """Stretch an arbitrary-length secret into a 32-byte urlsafe-base64 Fernet key."""
    digest = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def _encrypt_private_pem(pem: bytes) -> bytes:
    key_material = settings.AUTH_SIGNING_KEY_ENCRYPTION_KEY
    if not key_material:
        logger.warning(
            "auth_server.unencrypted_key_at_rest — AUTH_SIGNING_KEY_ENCRYPTION_KEY is "
            "unset; the RSA private key is being stored in plaintext. Set it before "
            "running this service outside development (see docs/security-guide.md)."
        )
        return pem
    return Fernet(_fernet_key_from(key_material)).encrypt(pem)


def _decrypt_private_pem(blob: bytes) -> bytes:
    key_material = settings.AUTH_SIGNING_KEY_ENCRYPTION_KEY
    if not key_material:
        return blob
    try:
        return Fernet(_fernet_key_from(key_material)).decrypt(blob)
    except InvalidToken:
        # Stored plaintext because the encryption key was unset when this
        # row was created (e.g. a dev DB later given a real key). Treat the
        # blob as the raw PEM rather than failing startup.
        return blob


def reset_cache_for_tests() -> None:
    """Clear the in-process key cache. Test-only."""
    global _active_kid, _active_key
    _active_kid, _active_key = None, None


async def ensure_active_key(pool: asyncpg.Pool) -> tuple[str, RSAKey]:
    """Return the ``(kid, private_key)`` pair, bootstrapping one on first boot.

    Idempotent and process-cached: repeated calls after the first return the
    same cached key without hitting the database.
    """
    global _active_kid, _active_key
    if _active_key is not None and _active_kid is not None:
        return _active_kid, _active_key

    row = await pool.fetchrow("SELECT kid, private_pem_enc FROM oauth_signing_keys WHERE is_active = TRUE LIMIT 1")
    if row is not None:
        pem = _decrypt_private_pem(bytes(row["private_pem_enc"]))
        key = RSAKey.import_key(pem)
        key.ensure_kid()
        _active_kid, _active_key = row["kid"], key
        logger.info("auth_server.signing_key_loaded kid=%s", _active_kid)
        return _active_kid, _active_key

    key = RSAKey.generate_key(settings.AUTH_RSA_KEY_SIZE, private=True)
    key.ensure_kid()
    kid = key.kid
    pem = key.as_pem(private=True)
    public_jwk = key.as_dict(private=False)

    await pool.execute(
        """INSERT INTO oauth_signing_keys (kid, alg, public_jwk, private_pem_enc, is_active)
           VALUES ($1, 'RS256', $2::jsonb, $3, TRUE)
           ON CONFLICT (kid) DO NOTHING""",
        kid,
        json.dumps(public_jwk),
        _encrypt_private_pem(pem),
    )
    _active_kid, _active_key = kid, key
    logger.info("auth_server.signing_key_generated kid=%s", kid)
    return _active_kid, _active_key


async def get_jwks(pool: asyncpg.Pool) -> dict:
    """Return the public JWKS document: active plus any not-yet-expired retired keys."""
    rows = await pool.fetch("SELECT public_jwk FROM oauth_signing_keys WHERE is_active = TRUE OR retired_at IS NULL")

    def _as_dict(value):
        return json.loads(value) if isinstance(value, str) else value

    return {"keys": [_as_dict(row["public_jwk"]) for row in rows]}
