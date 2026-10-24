"""Unit tests for shared.jwt_utils (Track D). Pure crypto — no DB/LLM."""

from __future__ import annotations

import datetime as dt

import jwt
import pytest

from shared.config import settings
from shared.jwt_utils import (
    ALGORITHM,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_access_token_roundtrip() -> None:
    payload = decode_token(create_access_token("a@b.com", "admin", "u1"))
    assert payload["sub"] == "a@b.com"
    assert payload["role"] == "admin"
    assert payload["user_id"] == "u1"
    assert payload["type"] == "access"
    assert "exp" in payload


def test_refresh_token_roundtrip() -> None:
    payload = decode_token(create_refresh_token("a@b.com"))
    assert payload["sub"] == "a@b.com"
    assert payload["type"] == "refresh"
    assert "role" not in payload
    assert "user_id" not in payload


def test_access_token_honors_custom_expiry() -> None:
    token = create_access_token("a@b.com", "customer", "u1", expires_delta=dt.timedelta(seconds=1))
    payload = decode_token(token)
    assert payload["type"] == "access"


def test_decode_rejects_tampered_token() -> None:
    token = create_access_token("a@b.com", "customer", "u1")
    with pytest.raises(jwt.InvalidTokenError):
        decode_token(token + "tampered")


def test_decode_rejects_wrong_secret() -> None:
    token = jwt.encode(
        {"sub": "x", "type": "access", "exp": dt.datetime.now(dt.UTC) + dt.timedelta(minutes=5)},
        "a-totally-different-secret-key-0123456789",
        algorithm=ALGORITHM,
    )
    with pytest.raises(jwt.InvalidTokenError):
        decode_token(token)


def test_decode_rejects_expired_token() -> None:
    past = dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1)
    token = jwt.encode(
        {"sub": "x", "type": "access", "exp": past},
        settings.JWT_SECRET,
        algorithm=ALGORITHM,
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_token(token)


def test_password_hash_roundtrip() -> None:
    hashed = hash_password("s3cret-pw!")
    assert hashed != "s3cret-pw!"
    assert verify_password("s3cret-pw!", hashed) is True
    assert verify_password("wrong-pw", hashed) is False
