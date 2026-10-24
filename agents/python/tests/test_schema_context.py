"""Unit tests for shared.schema_context (Track D). Pure module constants."""

from __future__ import annotations

import pytest

import shared.schema_context as sc

SCHEMA_CONSTANTS = [
    "USER_SCHEMA_CONTEXT",
    "ORDER_SCHEMA_CONTEXT",
    "PRODUCT_SCHEMA_CONTEXT",
    "INVENTORY_SCHEMA_CONTEXT",
    "PRICING_SCHEMA_CONTEXT",
    "REVIEW_SCHEMA_CONTEXT",
]


@pytest.mark.parametrize("name", SCHEMA_CONSTANTS)
def test_schema_constant_is_nonempty_string(name: str) -> None:
    value = getattr(sc, name)
    assert isinstance(value, str)
    assert value.strip(), f"{name} is empty"
    assert "Database:" in value
