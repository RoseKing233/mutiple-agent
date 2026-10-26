"""SSE text framing shared by specialist and orchestrator transports."""

from collections.abc import AsyncIterable, AsyncIterator


def text_event(text: str, event: str | None = None) -> str:
    """Prefix EVERY data line, including blank/trailing lines, per the SSE spec.

    A raw ``data: {chunk}`` loses embedded newlines because an unprefixed line
    is not data. Normalise CR/CRLF to LF, as SSE readers do for line endings.
    """
    normalised = text.replace("\r\n", "\n").replace("\r", "\n")
    header = f"event: {event}\n" if event else ""
    return header + "".join(f"data: {line}\n" for line in normalised.split("\n")) + "\n"


async def read_events(lines: AsyncIterable[str]) -> AsyncIterator[tuple[str, str]]:
    """Read complete frames, joining their data lines with LF (one optional space).

    Comments/unknown fields are ignored; an unfinished event at EOF is not
    dispatched. Empty data strings are valid and distinct from no data field.
    """
    event = ""
    data: list[str] = []
    async for line in lines:
        if line == "":
            if data:
                yield event, "\n".join(data)
            event, data = "", []
            continue
        if line.startswith(":"):
            continue
        name, separator, value = line.partition(":")
        if separator and value.startswith(" "):
            value = value[1:]
        if name == "data":
            data.append(value)
        elif name == "event":
            event = value
