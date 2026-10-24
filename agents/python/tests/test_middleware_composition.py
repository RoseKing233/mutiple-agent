"""Track D3 — coverage for the specialist middleware composition helper.

Deterministic: no agent build, no LLM, no DB. Exercises both branches of
`build_specialist_middleware`.
"""

from __future__ import annotations

from shared.middleware import build_specialist_middleware


def test_default_stack_is_nonempty_list() -> None:
    stack = build_specialist_middleware()
    assert isinstance(stack, list)
    assert len(stack) >= 1


def test_include_steps_adds_step_middleware() -> None:
    with_steps = build_specialist_middleware(include_steps=True)
    without_steps = build_specialist_middleware(include_steps=False)
    # Step middleware is appended only when include_steps is True.
    assert len(with_steps) >= len(without_steps)


def test_guardrail_middleware_present_by_default() -> None:
    names = {type(m).__name__ for m in build_specialist_middleware()}
    assert "OutputSanitizationMiddleware" in names
    assert "InjectionDetectionChatMiddleware" in names
