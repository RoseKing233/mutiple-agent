"""Role instructions for each request, including long-lived A2A/MCP agents."""

from typing import Any

from agent_framework import ContextProvider

from shared.context import current_user_role
from shared.prompt_loader import load_role_instructions


class InventoryRoleProvider(ContextProvider):
    def __init__(self) -> None:
        super().__init__(source_id="inventory-role")

    async def before_run(self, *, agent: Any, session: Any, context: Any, state: dict[str, Any]) -> None:
        context.extend_instructions(
            self.source_id, load_role_instructions("inventory-fulfillment", current_user_role.get() or "customer")
        )

    async def after_run(self, *, agent: Any, session: Any, context: Any, state: dict[str, Any]) -> None:
        pass
