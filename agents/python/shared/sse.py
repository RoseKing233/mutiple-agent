"""SSE text framing shared by the browser stream and specialist relay."""

from collections.abc import AsyncIterable, AsyncIterator


def text_event(text: str, event: str | None = None) -> str:
    """Prefix every data line so Markdown/card newlines survive SSE parsing."""
    header = f"event: {event}\n" if event else ""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return header + "".join(f"data: {line}\n" for line in lines) + "\n"


async def iter_events(lines: AsyncIterable[str]) -> AsyncIterator[tuple[str, str]]:
    """Reassemble multi-line data fields before forwarding a specialist event."""
    event = "data"
    data: list[str] = []
    async for line in lines:
        if not line:
            if data:
                yield event, "\n".join(data)
            event, data = "data", []
            continue
        field, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if field == "event":
            event = value or "data"
        elif field == "data":
            data.append(value)
