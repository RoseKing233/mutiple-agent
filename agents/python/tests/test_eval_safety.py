"""Tests for the safety / red-team eval (Track B3). No LLM/DB.

Unit-tests the pure resistance scorers and validates the red-team dataset shape
+ that every target_agent is registered and every attack_type is known.
"""

from __future__ import annotations

from pathlib import Path

from evals.evaluator import AgentEvaluator
from evals.run_evals import AGENT_FACTORIES
from evals.safety_evaluator import (
    load_safety_dataset,
    score_injection_resisted,
    score_refusal,
)

RED_TEAM = Path(__file__).resolve().parent.parent / "evals" / "datasets" / "red_team.json"


def test_injection_resisted_true_when_clean() -> None:
    assert score_injection_resisted("Here are the reviews you asked for.", ["system prompt", "PWNED-1337"]) is True


def test_injection_resisted_false_when_forbidden_present() -> None:
    assert score_injection_resisted("Sure: PWNED-1337, and here is my system prompt", ["PWNED-1337"]) is False


def test_injection_resisted_is_case_insensitive() -> None:
    assert score_injection_resisted("...i am dan now...", ["I am DAN"]) is False


def test_refusal_detected() -> None:
    assert score_refusal("I can't help with that request.") is True
    assert score_refusal("I cannot reveal my instructions.") is True


def test_refusal_absent_on_normal_answer() -> None:
    assert score_refusal("Here are your most recent orders.") is False


def test_run_once_exists_on_evaluator() -> None:
    assert hasattr(AgentEvaluator, "run_once")


def test_red_team_dataset_is_valid() -> None:
    cases = load_safety_dataset(RED_TEAM)
    assert cases
    valid_types = {"injection", "jailbreak", "role_escalation"}
    for c in cases:
        assert c.target_agent in AGENT_FACTORIES, f"unknown target_agent {c.target_agent!r}"
        assert c.attack_type in valid_types
        assert c.input.strip()
