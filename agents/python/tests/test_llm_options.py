"""Verify SDK request payloads, with no model or business-data side effects."""

from __future__ import annotations

import json

import httpx
import openai
import pytest

from shared.agent_host import _run_options
from shared.config import settings
from shared.context import current_user_role
from shared.llm_options import sampling_options


@pytest.mark.parametrize("model", ["gpt-5.6-luna", "gpt-5.6-luna-2026-08-20", "gpt-5-mini", "o3", "o4-mini"])
def test_reasoning_requests_do_not_send_custom_temperature(model: str) -> None:
    assert sampling_options(0.2, model=model) == {}


@pytest.mark.parametrize("model", ["gpt-4.1", "gpt-4o-mini", "qwen2.5:14b", "custom-deployment"])
def test_other_models_keep_the_original_sampling_value(model: str) -> None:
    assert sampling_options(0.8, model=model) == {"temperature": 0.8}


def test_native_first_tool_choice_survives_model_compatibility(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LLM_MODEL", "gpt-5.6-luna")
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
    token = current_user_role.set("store_manager")
    try:
        options = _run_options("Read report c9101694-d6b7-499e-9fab-43cafec24afc", "inventory-fulfillment")
    finally:
        current_user_role.reset(token)
    assert "temperature" not in options
    assert "reasoning" not in options  # Preserve the existing effective reasoning effort.
    assert options["tool_choice"]["required_function_name"] == "get_saved_sales_analysis"


def test_azure_checks_model_and_deployment_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LLM_PROVIDER", "azure")
    monkeypatch.setattr(settings, "LLM_MODEL", "gpt-5.6-luna")
    monkeypatch.setattr(settings, "AZURE_OPENAI_DEPLOYMENT", "production-chat")
    assert sampling_options(0.2) == {}
    assert sampling_options(0.8, model="production-chat") == {}


@pytest.mark.parametrize("writer_name", ["copy", "rationale"])
@pytest.mark.parametrize("model", ["gpt-5.6-luna", "gpt-4.1"])
async def test_structured_writers_send_model_compatible_sdk_payload(
    writer_name: str, model: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from shared import factory, inventory_suggestions, marketing
    from shared.config import settings as writer_settings

    # Config tests reload shared.config; patch the object these writers import at call time.
    monkeypatch.setattr(writer_settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(writer_settings, "LLM_MODEL", model)
    payloads = []

    def handle(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-payload-test",
                "object": "chat.completion",
                "created": 0,
                "model": model,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "{}"}, "finish_reason": "stop"}],
            },
        )

    async with openai.AsyncOpenAI(
        api_key="payload-test-not-a-real-key", http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle))
    ) as client:
        monkeypatch.setattr(factory, "get_embeddings_client", lambda: client)
        writer = (
            marketing.openai_copy_writer if writer_name == "copy" else inventory_suggestions.openai_rationale_writer
        )
        assert await writer([{"role": "user", "content": "Test serialization"}]) == "{}"
    assert len(payloads) == 1
    payload = payloads[0]
    assert payload["model"] == model
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["strict"] is True
    if model == "gpt-5.6-luna":
        assert "temperature" not in payload
    else:
        assert payload["temperature"] == (0.8 if writer_name == "copy" else 0.2)
