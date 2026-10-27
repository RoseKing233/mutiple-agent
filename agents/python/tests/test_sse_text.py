"""Wire round-trips for blank lines, Markdown and A2A relay, without model calls."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from shared.sse import read_events, text_event


async def test_a2a_stream_fallback_reuses_request_id(monkeypatch: pytest.MonkeyPatch) -> None:
    import orchestrator.agent as agent
    from shared.context import current_stream_queue

    calls = []

    async def respond(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, request.headers.get("x-agent-request-id")))
        if request.url.path.endswith("stream"):
            raise httpx.ReadError("stream disconnected after tool commit", request=request)
        return httpx.Response(200, json={"response": "stored report", "steps": []}, request=request)

    original = httpx.AsyncClient

    def client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        return original(*args, **(kwargs | {"transport": httpx.MockTransport(respond)}))

    monkeypatch.setattr(agent.httpx, "AsyncClient", client)
    monkeypatch.setattr(agent, "AGENT_REGISTRY", {"inventory-fulfillment": "http://inventory"})
    token = current_stream_queue.set(asyncio.Queue())
    try:
        assert (
            await agent.call_specialist_agent(agent_name="inventory-fulfillment", message="forecast") == "stored report"
        )
        assert [path for path, _ in calls] == ["/message:stream", "/message:send"]
        assert calls[0][1] and calls[0][1] == calls[1][1]
    finally:
        current_stream_queue.reset(token)


async def lines(text: str) -> AsyncIterator[str]:
    for line in text.splitlines():
        yield line


@pytest.mark.parametrize(
    "text", ["", "\n", "\n\n", "one\n", "one\n\ntwo", "  indented\n- item\n\n```inventory\n{}\n```"]
)
async def test_text_event_round_trip(text: str) -> None:
    assert [e async for e in read_events(lines(text_event(text)))] == [("", text)]
    assert [e async for e in read_events(lines(text_event(text, "delta")))] == [("delta", text)]


async def test_reader_ignores_comments_and_does_not_dispatch_incomplete_frame() -> None:
    stream = ': heartbeat\nevent: step\ndata: {\ndata:  "a": 1\ndata: }\n\ndata: incomplete'
    assert [e async for e in read_events(lines(stream))] == [("step", '{\n "a": 1\n}')]


async def test_specialist_host_encodes_embedded_newlines(monkeypatch: pytest.MonkeyPatch) -> None:
    import shared.agent_host as host

    text = "## Sales\n\n- Units: 518\n- Orders: 331\n"

    async def stream(*_args: object, **_kwargs: object) -> AsyncIterator[str]:
        yield text

    monkeypatch.setattr(host, "_run_agent_native_stream", stream)
    app = host.create_agent_app(agent=object(), agent_name="test", port=8085)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/message:stream", json={"message": "history"})
    events = [event async for event in read_events(lines(response.text))]
    assert events == [("", text), ("", "[DONE]")]


async def test_a2a_relay_joins_each_multiline_event_before_forwarding(monkeypatch: pytest.MonkeyPatch) -> None:
    import orchestrator.agent as agent
    from shared.context import current_steps, current_stream_queue

    text = "## Sales\n\n- Units: 518\n\n```inventory\n{}\n```\n"
    body = 'event: step\ndata: {"tool_name":"get_sales_history"}\n\n' + text_event(text) + "data: [DONE]\n\n"

    async def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body.encode(), request=request)

    original = httpx.AsyncClient

    def client(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(respond)
        return original(*args, **kwargs)

    monkeypatch.setattr(agent.httpx, "AsyncClient", client)
    monkeypatch.setattr(agent, "AGENT_REGISTRY", {"inventory-fulfillment": "http://inventory"})
    queue: asyncio.Queue = asyncio.Queue()
    queue_token = current_stream_queue.set(queue)
    steps_token = current_steps.set([])
    try:
        result = await agent.call_specialist_agent(agent_name="inventory-fulfillment", message="history")
        assert result == text
        frame = queue.get_nowait()
        assert frame[:2] == ("frame", "step")
        assert queue.get_nowait() == ("delta", "inventory-fulfillment", text)
        assert len(current_steps.get()) == 1
    finally:
        current_steps.reset(steps_token)
        current_stream_queue.reset(queue_token)
