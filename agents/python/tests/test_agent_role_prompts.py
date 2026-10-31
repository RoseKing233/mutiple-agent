"""A reused specialist must follow the current role, never a startup customer role."""

from __future__ import annotations

import importlib

import pytest

from shared.config import settings
from shared.context import current_user_role
from shared.context_providers import RoleInstructionsProvider


@pytest.mark.parametrize("module", ["product_discovery", "order_management", "pricing_promotions", "review_sentiment"])
async def test_reused_specialist_switches_role_instructions(module: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(settings, "MCP_ENABLED", False)
    current_user_role.set("customer")
    agent = getattr(importlib.import_module(f"{module}.agent"), f"create_{module}_agent")()
    assert "This user is a customer" not in agent.default_options["instructions"]
    providers = [p for p in agent.context_providers if isinstance(p, RoleInstructionsProvider)]
    assert len(providers) == 1

    class Context:
        instructions = ""

        def extend_instructions(self, source_id: str, instructions: str) -> None:
            self.instructions = instructions

    context = Context()
    for role, expected in [("store_manager", "store manager"), ("admin", "an admin"), ("customer", "a customer")]:
        current_user_role.set(role)
        await providers[0].before_run(agent=agent, session=None, context=context, state={})
        assert expected in context.instructions
        if role == "store_manager":
            assert "This user is a customer" not in context.instructions
