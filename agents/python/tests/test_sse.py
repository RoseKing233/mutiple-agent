from collections.abc import AsyncIterator

import pytest

from shared.sse import iter_events, text_event


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ["", "\n", "\n\n", '推荐：\n\n```product\n{"name":"Sony"}\n```\n', " plain text "])
async def test_multiline_text_round_trip(text: str) -> None:
    async def lines() -> AsyncIterator[str]:
        for line in text_event(text, "delta").split("\n"):
            yield line

    assert [event async for event in iter_events(lines())] == [("delta", text)]


@pytest.mark.asyncio
async def test_events_reset_type_and_ignore_comments() -> None:
    async def lines() -> AsyncIterator[str]:
        for line in [
            ": heartbeat",
            "event: step",
            'data:{"ok":true}',
            "",
            "data: first",
            "data: second",
            "",
            "data: incomplete",
        ]:
            yield line

    assert [event async for event in iter_events(lines())] == [("step", '{"ok":true}'), ("data", "first\nsecond")]
