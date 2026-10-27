"""Pure contract tests; no model calls or database substitutes."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from product_discovery.agent import create_product_discovery_agent
from shared.recommendations import (
    RecommendationDraft,
    RecommendationRequest,
    RecommendationUnavailableError,
    validate_recommendation,
)

EVIDENCE = {"sources": [{"id": "p:1", "kind": "catalogue"}, {"id": "r:1", "kind": "review"}]}


def draft(**overrides: list[dict]) -> RecommendationDraft:
    fields = {
        "product_summary": [],
        "review_summary": [],
        "reasons": [{"text": "Catalogue lists ANC.", "source_ids": ["p:1"]}],
        "cautions": [],
    }
    return RecommendationDraft.model_validate(fields | overrides)


@pytest.mark.parametrize("preferences", ["", "   ", "x" * 1501])
def test_invalid_preferences_rejected(preferences: str) -> None:
    with pytest.raises(ValidationError):
        RecommendationRequest(preferences=preferences)


@pytest.mark.parametrize("budget", [-1, float("nan"), float("inf"), 1000001])
def test_invalid_budget_rejected(budget: float) -> None:
    with pytest.raises(ValidationError):
        RecommendationRequest(preferences="commuting", max_budget=budget)


def test_zero_budget_is_not_discarded() -> None:
    assert RecommendationRequest(preferences="commuting", max_budget=0).max_budget == 0


def test_grounded_points_accepted() -> None:
    validate_recommendation(draft(review_summary=[{"text": "Sampled opinion.", "source_ids": ["r:1"]}]), EVIDENCE)


@pytest.mark.parametrize(
    "section,source", [("reasons", "unknown"), ("review_summary", "p:1"), ("product_summary", "r:1")]
)
def test_unsupported_citations_rejected(section: str, source: str) -> None:
    with pytest.raises(RecommendationUnavailableError):
        validate_recommendation(draft(**{section: [{"text": "Unsupported", "source_ids": [source]}]}), EVIDENCE)


def test_no_reviews_cannot_produce_review_summary() -> None:
    with pytest.raises(RecommendationUnavailableError):
        validate_recommendation(
            draft(review_summary=[{"text": "Invented review", "source_ids": ["r:1"]}]),
            {"sources": EVIDENCE["sources"][:1]},
        )


def test_empty_citation_list_rejected() -> None:
    with pytest.raises(ValidationError):
        draft(reasons=[{"text": "Unsupported", "source_ids": []}])


@pytest.mark.parametrize("mcp", [False, True])
def test_tools_available_in_both_discovery_modes(monkeypatch: pytest.MonkeyPatch, mcp: bool) -> None:
    from product_discovery import agent as discovery
    from shared import factory

    # Configuration tests reload shared.config/factory, so patch each consumer's
    # current settings instead of a stale object imported during collection.
    monkeypatch.setattr(factory.settings, "OPENAI_API_KEY", "test-only-no-network")
    monkeypatch.setattr(factory.settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(discovery.settings, "MCP_ENABLED", mcp)
    monkeypatch.setattr(discovery.settings, "MCP_AUTH_ENABLED", False)
    agent = create_product_discovery_agent()
    names = {t.name for t in agent.default_options["tools"]}
    assert {"get_recommendation_evidence", "generate_recommendation_reasons"} <= names
