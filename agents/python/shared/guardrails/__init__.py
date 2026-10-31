"""Code-layer guardrails for the multi-agent platform (Track A — security).

Defense-in-depth on top of the prompt-layer rules in
``config/prompts/_shared/grounding-rules.yaml``:

- :mod:`shared.guardrails.sanitize` — neutralize stored / indirect prompt
  injection in untrusted text (reviews, descriptions, order notes).
- :class:`shared.guardrails.output_middleware.OutputSanitizationMiddleware` —
  apply that neutralization to tool *outputs* before they re-enter the model.
- :class:`shared.guardrails.injection_middleware.InjectionDetectionChatMiddleware`
  — observe (and optionally block) injection attempts in inbound messages.
- :func:`shared.guardrails.roles.requires_role` — tool-level authorization that
  runs in front of the existing ``approval_mode`` human-approval gates.

Content-safety checks are flag-gated via ``shared.config.settings`` (``GUARDRAILS_*``) and
default to fail-open so they can be rolled out observe-only first. Role
authorization is always enforced and is not controlled by those flags.
"""

from __future__ import annotations

from shared.guardrails.sanitize import (
    contains_injection_markers,
    neutralize_text,
    neutralize_value,
)

__all__ = [
    "contains_injection_markers",
    "neutralize_text",
    "neutralize_value",
]
