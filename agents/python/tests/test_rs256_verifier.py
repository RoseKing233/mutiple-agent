"""RS256Verifier — validates AS-issued tokens against a real RSA keypair.

Per-test RSA keypair + an in-process JWKS stub: ``PyJWKClient.fetch_data``
(the third-party HTTP-fetch plumbing, not our own logic) is monkeypatched to
return the test keypair's public JWK directly instead of making a real
network call. Signature/claim verification below is genuine. No DB, no LLM.
"""

from __future__ import annotations

import time

import jwt as pyjwt
import pytest
from joserfc.jwk import RSAKey

from shared.config import settings
from shared.oauth.verifier import RS256Verifier

ISSUER = "http://test-auth-server"
AUDIENCE = "ecommerce-orchestrator"


@pytest.fixture
def keypair():
    key = RSAKey.generate_key(2048, private=True)
    key.ensure_kid()
    return key


@pytest.fixture
def verifier(keypair, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_SERVER_ISSUER", ISSUER)
    monkeypatch.setattr(settings, "AUTH_SERVER_JWKS_URL", f"{ISSUER}/.well-known/jwks.json")
    v = RS256Verifier()
    public_jwks = {"keys": [keypair.as_dict(private=False)]}
    monkeypatch.setattr(v._jwks_client, "fetch_data", lambda: public_jwks)
    return v


def _make_token(keypair, *, aud=AUDIENCE, iss=ISSUER, scope="api:chat", exp_delta=3600, **extra):
    now = int(time.time())
    payload = {
        "iss": iss,
        "aud": aud,
        "exp": now + exp_delta,
        "iat": now,
        "sub": "alice@example.com",
        "scope": scope,
        **extra,
    }
    return pyjwt.encode(payload, keypair.as_pem(private=True), algorithm="RS256", headers={"kid": keypair.kid})


def test_accepts_valid_token(keypair, verifier):
    token = _make_token(keypair)
    payload = verifier.decode(token, audience=AUDIENCE, required_scope="api:chat")
    assert payload["sub"] == "alice@example.com"
    assert payload["aud"] == AUDIENCE


def test_accepts_token_with_list_audience(keypair, verifier):
    """authlib issues aud as a list when a token spans multiple audiences."""
    token = _make_token(keypair, aud=["ecommerce-agents", AUDIENCE])
    payload = verifier.decode(token, audience=AUDIENCE)
    assert AUDIENCE in payload["aud"]


def test_rejects_wrong_audience(keypair, verifier):
    token = _make_token(keypair, aud="some-other-audience")
    with pytest.raises(pyjwt.InvalidAudienceError):
        verifier.decode(token, audience=AUDIENCE)


def test_rejects_wrong_issuer(keypair, verifier):
    token = _make_token(keypair, iss="http://not-the-real-as")
    with pytest.raises(pyjwt.InvalidIssuerError):
        verifier.decode(token, audience=AUDIENCE)


def test_rejects_expired_token(keypair, verifier):
    token = _make_token(keypair, exp_delta=-10)
    with pytest.raises(pyjwt.ExpiredSignatureError):
        verifier.decode(token, audience=AUDIENCE)


def test_rejects_tampered_token(keypair, verifier):
    token = _make_token(keypair)
    with pytest.raises(pyjwt.InvalidTokenError):
        verifier.decode(token + "tampered", audience=AUDIENCE)


def test_rejects_token_signed_by_unknown_key(verifier):
    other_key = RSAKey.generate_key(2048, private=True)
    other_key.ensure_kid()
    token = _make_token(other_key)
    with pytest.raises(pyjwt.PyJWKClientError):
        verifier.decode(token, audience=AUDIENCE)


def test_rejects_missing_required_scope(keypair, verifier):
    token = _make_token(keypair, scope="agent:invoke")
    with pytest.raises(pyjwt.InvalidTokenError, match="missing required scope"):
        verifier.decode(token, audience=AUDIENCE, required_scope="api:chat")


def test_accepts_when_required_scope_present_among_several(keypair, verifier):
    token = _make_token(keypair, scope="agent:invoke api:chat")
    payload = verifier.decode(token, audience=AUDIENCE, required_scope="api:chat")
    assert payload["scope"] == "agent:invoke api:chat"
