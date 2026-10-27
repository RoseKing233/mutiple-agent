"""Pure contract tests; no model calls or database substitutes."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from product_discovery.agent import create_product_discovery_agent
from shared.recommendations import (
    RecommendationDraft,
    RecommendationRequest,
    RecommendationUnavailableError,
    recommendation_response_format,
    validate_recommendation,
)

EVIDENCE = {"sources": [{"id": "p:1", "kind": "catalogue"}, {"id": "r:1", "kind": "review"}]}


def draft(**overrides: object) -> RecommendationDraft:
    fields = {
        "needs_assessment": {"status": "meets_needs", "text": "ANC is listed.", "source_ids": ["p:1"]},
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


def test_direct_answer_is_required_even_when_summaries_are_present() -> None:
    fields = draft().model_dump()
    del fields["needs_assessment"]
    with pytest.raises(ValidationError):
        RecommendationDraft.model_validate(fields)


@pytest.mark.parametrize("source_ids", [["unknown"], ["p:1", "unknown"]])
def test_direct_answer_cannot_cite_invented_variant_evidence(source_ids: list[str]) -> None:
    with pytest.raises(RecommendationUnavailableError):
        validate_recommendation(
            draft(needs_assessment={"status": "meets_needs", "text": "Red is in stock.", "source_ids": source_ids}),
            EVIDENCE,
        )


def test_uncertainty_answer_can_reference_the_catalogue_checked() -> None:
    validate_recommendation(
        draft(
            needs_assessment={
                "status": "cannot_confirm",
                "text": "The catalogue does not specify colours, so a red version cannot be confirmed.",
                "source_ids": ["p:1"],
            }
        ),
        EVIDENCE,
    )


def test_generation_schema_enumerates_only_current_evidence_ids() -> None:
    response_format = recommendation_response_format(EVIDENCE)
    schema = response_format.model_json_schema()
    ids_schema = schema["$defs"]["EvidencePoint"]["properties"]["source_ids"]["items"]
    assert ids_schema["enum"] == ["p:1", "r:1"]
    result = response_format.model_validate(draft().model_dump())
    assert isinstance(result, RecommendationDraft)
    assert result.model_dump() == draft().model_dump()


@pytest.mark.parametrize(
    "section,source", [("reasons", "unknown"), ("review_summary", "p:1"), ("product_summary", "r:1")]
)
def test_generation_schema_prevents_unknown_or_wrong_kind_citations(section: str, source: str) -> None:
    fields = draft(**{section: [{"text": "A claim.", "source_ids": [source]}]}).model_dump()
    with pytest.raises(ValidationError):
        recommendation_response_format(EVIDENCE).model_validate(fields)


def test_generation_schema_prevents_the_observed_document_id_typo() -> None:
    valid_id = "document:6773526a-5933-50e8-bb7f-fbbf2628423e"
    mistyped_id = "document:6773526a-5933-50e8-bbf-fbbf2628423e"
    evidence = {"sources": [*EVIDENCE["sources"], {"id": valid_id, "kind": "document"}]}
    fields = draft(product_summary=[{"text": "32oz insulated bottle.", "source_ids": [mistyped_id]}]).model_dump()
    response_format = recommendation_response_format(evidence)
    with pytest.raises(ValidationError):
        response_format.model_validate(fields)
    fields["product_summary"][0]["source_ids"] = [valid_id]
    response_format.model_validate(fields)


def test_no_review_evidence_requires_an_empty_generated_review_summary() -> None:
    response_format = recommendation_response_format({"sources": EVIDENCE["sources"][:1]})
    assert response_format.model_json_schema()["properties"]["review_summary"]["maxItems"] == 0
    response_format.model_validate(draft().model_dump())
    with pytest.raises(ValidationError):
        response_format.model_validate(
            draft(review_summary=[{"text": "An unsupported opinion.", "source_ids": ["p:1"]}]).model_dump()
        )


def test_generation_schemas_do_not_leak_citations_between_products() -> None:
    first_format = recommendation_response_format(EVIDENCE)
    second_format = recommendation_response_format({"sources": [{"id": "p:2", "kind": "catalogue"}]})
    with pytest.raises(ValidationError):
        second_format.model_validate(draft().model_dump())
    first_format.model_validate(draft().model_dump())


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
