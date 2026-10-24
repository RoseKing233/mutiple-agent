"""Tests for orchestrator routing eval (Track B2). No LLM/DB.

Unit-tests the pure routing scorer and validates the routing dataset shape +
that every expected_route names a registered specialist.
"""

from __future__ import annotations

from pathlib import Path

from evals.evaluator import AgentEvaluator, load_dataset
from evals.run_evals import AGENT_FACTORIES

ROUTING_DATASET = Path(__file__).resolve().parent.parent / "evals" / "datasets" / "orchestrator_routing.json"


def test_score_routing_correct() -> None:
    assert AgentEvaluator._score_routing(["product-discovery"], "product-discovery") == 1.0


def test_score_routing_wrong_specialist() -> None:
    assert AgentEvaluator._score_routing(["pricing-promotions"], "order-management") == 0.5


def test_score_routing_no_route() -> None:
    assert AgentEvaluator._score_routing([], "order-management") == 0.0


def test_orchestrator_registered() -> None:
    assert "orchestrator" in AGENT_FACTORIES


def test_routing_dataset_targets_known_specialists() -> None:
    specialists = set(AGENT_FACTORIES) - {"orchestrator"}
    cases = load_dataset(ROUTING_DATASET)
    assert cases
    for case in cases:
        assert case.expected_route in specialists, f"unknown route {case.expected_route!r}"
        assert case.expected_tools == ["call_specialist_agent"]
