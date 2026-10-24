"""Runnable demo for Chapter 22 — group-chat / round-table debate.

Deterministic by default (no LLM): panelists are plain callables. Run from the
backend package so the ``workflows`` import resolves:

    cd agents/python && uv run python ../../tutorials/22-group-chat-debate/python/main.py
"""

from __future__ import annotations

import asyncio

from workflows.group_chat import GroupChatWorkflow


def value_voice(question: str, transcript: list[dict[str, str]]) -> str:
    return "Strong price for the feature set; frequent discounts."


def quality_voice(question: str, transcript: list[dict[str, str]]) -> str:
    prior = len(transcript)
    return f"Considering {prior} prior point(s): reviews show excellent build quality."


def synthesize(state) -> str:
    return (
        f"Verdict on '{state.question}': both value and quality perspectives are "
        f"positive across {len(state.transcript)} turns — recommended."
    )


async def main() -> None:
    workflow = GroupChatWorkflow(
        panelists=[("value", value_voice), ("quality", quality_voice)],
        synthesizer=synthesize,
    )
    state = await workflow.execute("Is the Sony WH-1000XM5 worth it?")

    print("Transcript:")
    for turn in state.transcript:
        print(f"  {turn['speaker']:>8}: {turn['text']}")
    print("\nModerator verdict:")
    print(f"  {state.verdict}")


if __name__ == "__main__":
    asyncio.run(main())
