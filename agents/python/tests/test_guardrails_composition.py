"""Tests for build_specialist_middleware composition (Track A3). No LLM/DB."""

from __future__ import annotations

from shared.agent_observability import StepRecorderMiddleware
from shared.config import settings
from shared.guardrails.injection_middleware import InjectionDetectionChatMiddleware
from shared.guardrails.output_middleware import OutputSanitizationMiddleware
from shared.middleware import (
    AgentRunLogger,
    PiiRedactionMiddleware,
    ToolAuditMiddleware,
    build_specialist_middleware,
)


def _types(stack):
    return [type(m) for m in stack]


def test_full_stack_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "GUARDRAILS_ENABLED", True)
    types = _types(build_specialist_middleware())
    for expected in (
        AgentRunLogger,
        ToolAuditMiddleware,
        InjectionDetectionChatMiddleware,
        PiiRedactionMiddleware,
        OutputSanitizationMiddleware,
        StepRecorderMiddleware,
    ):
        assert expected in types, f"{expected.__name__} missing from composed stack"


def test_guardrails_disabled_drops_security_layers(monkeypatch):
    monkeypatch.setattr(settings, "GUARDRAILS_ENABLED", False)
    types = _types(build_specialist_middleware())
    assert InjectionDetectionChatMiddleware not in types
    assert OutputSanitizationMiddleware not in types
    # PII redaction + observability stay on regardless of the guardrail flag.
    assert PiiRedactionMiddleware in types
    assert StepRecorderMiddleware in types


def test_include_steps_false_omits_recorder(monkeypatch):
    monkeypatch.setattr(settings, "GUARDRAILS_ENABLED", True)
    stack = build_specialist_middleware(include_steps=False)
    assert not any(isinstance(m, StepRecorderMiddleware) for m in stack)
