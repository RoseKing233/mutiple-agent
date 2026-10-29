from __future__ import annotations

from types import SimpleNamespace

import pytest

from shared.context import current_user_role
from shared.order_management.chat_policy import required_order_tool

ORDER_ID = "f9486a6e-d489-5750-8f0f-11b7769e2a2c"


@pytest.mark.parametrize(
    "message",
    [
        f"Please cancel my order {ORDER_ID}.",
        f"The user wants to cancel order {ORDER_ID}.",
        f"用户明确要求取消订单 {ORDER_ID}。",
        f"查看订单 {ORDER_ID} 是否已取消；如果还没取消，请取消。",
    ],
)
def test_explicit_cancellation_with_order_id_requires_cancel_tool(message: str) -> None:
    assert required_order_tool(message, "order-management", "customer") == "cancel_order"


@pytest.mark.parametrize(
    "message",
    [
        f"Has order {ORDER_ID} been cancelled?",
        f"查看订单 {ORDER_ID} 是否已取消？",
        f"Do not cancel order {ORDER_ID}.",
        f"不要取消订单 {ORDER_ID}。",
        "Please cancel my order.",
    ],
)
def test_status_checks_negations_or_missing_order_id_do_not_force_cancellation(message: str) -> None:
    assert required_order_tool(message, "order-management", "customer") is None


@pytest.mark.parametrize("role", ["anonymous", "power_user", "store_manager"])
def test_unsupported_role_does_not_force_customer_cancellation(role: str) -> None:
    assert required_order_tool(f"Please cancel order {ORDER_ID}.", "order-management", role) is None


@pytest.mark.parametrize("streaming", [False, True])
async def test_native_host_requires_cancel_tool_for_explicit_request(streaming: bool) -> None:
    from shared.agent_host import _run_agent_native, _run_agent_native_stream

    class RecordingAgent:
        name = "order-management"

        def run(self, messages: list, **kwargs: object) -> object:
            self.options = kwargs["options"]

            async def result() -> SimpleNamespace:
                return SimpleNamespace(text="Cancellation processed.")

            async def chunks():
                yield SimpleNamespace(text="Cancellation processed.")

            return chunks() if kwargs.get("stream") else result()

    agent = RecordingAgent()
    role_token = current_user_role.set("customer")
    try:
        message = f"Please cancel my order {ORDER_ID}."
        if streaming:
            response = "".join([chunk async for chunk in _run_agent_native_stream(agent, message)])
        else:
            response = await _run_agent_native(agent, message)
    finally:
        current_user_role.reset(role_token)

    assert agent.options["tool_choice"] == {
        "mode": "required",
        "required_function_name": "cancel_order",
    }
    assert response == "Cancellation processed."
