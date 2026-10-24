"""Unit tests for shared.tool_examples (Track D). Pure module constants."""

from __future__ import annotations

import pytest

import shared.tool_examples as te

EXAMPLE_CONSTANTS = [
    "ORDER_TOOL_EXAMPLES",
    "PRODUCT_TOOL_EXAMPLES",
    "PRICING_TOOL_EXAMPLES",
    "REVIEW_TOOL_EXAMPLES",
    "INVENTORY_TOOL_EXAMPLES",
]


@pytest.mark.parametrize("name", EXAMPLE_CONSTANTS)
def test_example_constant_is_nonempty_string(name: str) -> None:
    value = getattr(te, name)
    assert isinstance(value, str)
    assert value.strip(), f"{name} is empty"
    assert "Tool Usage Guide" in value
