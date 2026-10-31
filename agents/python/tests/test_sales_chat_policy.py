"""Native first-tool policy and compact report contract; no model requests."""

from collections.abc import AsyncGenerator
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from shared.agent_host import _run_agent_native, _run_agent_native_stream
from shared.context import current_agent_request_id, current_user_role
from shared.forecasting.chat_policy import required_report_tool
from shared.tools.sales_analysis_tools import compact_report


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Read the report you just saved; do not generate another forecast.", "get_saved_sales_analysis"),
        ("Retrieve my saved analysis report", "get_saved_sales_analysis"),
        ("List my three most recently saved sales analysis reports", "list_saved_sales_analyses"),
        ("Read the latest saved forecast", "list_saved_sales_analyses"),
        ("Read report c9101694-d6b7-499e-9fab-43cafec24afc", "get_saved_sales_analysis"),
        ("请读取刚才保存的报告，不要重新预测", "get_saved_sales_analysis"),
        ("请列出我最近保存的报告", "list_saved_sales_analyses"),
        ("Do not read a saved report. Create a 7-day forecast.", None),
        ("不要读取报告，请预测未来7天销量", None),
        ("Forecast sales and save a report", None),
        ("Show inventory for Atomic Habits", None),
        ("Hello", None),
    ],
)
def test_required_report_tool(message: str, expected: str | None) -> None:
    assert required_report_tool(message, "inventory-fulfillment", "store_manager") == expected
    assert required_report_tool(message, "orchestrator", "store_manager") == (
        "call_specialist_agent" if expected else None
    )
    assert required_report_tool(message, "inventory-fulfillment", "customer") is None
    assert required_report_tool(message, "inventory-fulfillment", "admin") is None
    assert required_report_tool(message, "order-management", "admin") is None


@pytest.mark.parametrize("streaming", [False, True])
async def test_native_host_forwards_required_choice_only_for_this_turn(streaming: bool) -> None:
    # This is a host adapter, not a replacement/fake LLM client.
    class RecordingAgent:
        name = "inventory-fulfillment"

        def run(self, messages: list, **kwargs: object) -> object:
            self.options = kwargs["options"]

            async def result() -> SimpleNamespace:
                return SimpleNamespace(text="ok")

            async def chunks() -> AsyncGenerator[SimpleNamespace, None]:
                yield SimpleNamespace(text="ok")

            return chunks() if kwargs.get("stream") else result()

    agent = RecordingAgent()
    token = current_user_role.set("store_manager")
    try:
        for message in ["Read the report you just saved", "Hello"]:
            if streaming:
                assert [text async for text in _run_agent_native_stream(agent, message)] == ["ok"]
            else:
                assert await _run_agent_native(agent, message) == "ok"
            assert agent.options.get("tool_choice") == (
                {"mode": "required", "required_function_name": "get_saved_sales_analysis"}
                if message.startswith("Read")
                else None
            )
    finally:
        current_user_role.reset(token)


@pytest.mark.parametrize("available,folds", [(False, 0), (True, 1), (True, 3)])
def test_compact_report_carries_explicit_forecast_and_operation(available: bool, folds: int) -> None:
    forecast = {
        "available": available,
        "model": "recent_mean_28" if folds < 2 else "tsb_0.1",
        "series": [{"date": "2026-10-26", "units": 0.5, "stock": 37.5}] if available else [],
        "backtest": {"folds": [{}] * folds, "scores": []},
    }
    full = {
        "id": "c9101694-d6b7-499e-9fab-43cafec24afc",
        "products": [{"product_id": "p", "name": "Book", "performance": {"stock_at_cutoff": 38}, "forecast": forecast}],
    }
    compact = compact_report(full)
    product = compact["products"][0]
    assert compact["operation"] == "read_saved_report"
    assert compact["dashboard_url"] == f"/analysis?run_id={full['id']}"
    assert product["forecast_units"] == (0.5 if available else None)
    assert product["projected_ending_stock"] == (37.5 if available else None)
    assert product["starting_stock_at_cutoff"] == 38
    if available:
        assert ("fallback" in product["model_selection"]) == (folds < 2)
    else:
        assert product["model_selection"] is None
    assert "series" in full["products"][0]["forecast"]  # Compacting never changes the saved snapshot.


@pytest.mark.parametrize("streaming", [False, True])
async def test_agent_host_binds_invocation_for_both_a2a_paths(streaming: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    import shared.agent_host as host

    request_id = "c9101694-d6b7-499e-9fab-43cafec24afc"

    async def run(*args: object, **kwargs: object) -> str:
        return current_agent_request_id.get()

    async def chunks(*args: object, **kwargs: object) -> AsyncGenerator[str, None]:
        yield current_agent_request_id.get()

    monkeypatch.setattr(host, "_run_agent_native", run)
    monkeypatch.setattr(host, "_run_agent_native_stream", chunks)
    app = host.create_agent_app(agent=object(), agent_name="test", port=8085)
    previous = current_agent_request_id.get()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/message:stream" if streaming else "/message:send",
            json={"message": "test"},
            headers={"x-agent-request-id": request_id},
        )
    assert response.status_code == 200
    assert request_id in response.text
    assert current_agent_request_id.get() == previous
