"""Pure contract tests; no model calls or database substitutes."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from product_discovery.agent import create_product_discovery_agent
from shared.recommendations import (
    RecommendationDraft,
    RecommendationRequest,
    RecommendationUnavailableError,
    listed_colour_assessment,
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


@pytest.mark.parametrize("budget_fit,stock", [(False, 10), (None, 0), (True, 0), (True, -1)])
def test_known_budget_or_stock_mismatch_cannot_be_presented_as_a_match(budget_fit: bool | None, stock: int) -> None:
    evidence = {**EVIDENCE, "product": {"available_quantity": stock}}
    response_format = recommendation_response_format(evidence, budget_fit=budget_fit)
    fields = draft().model_dump()
    for status in ("meets_needs", "cannot_confirm"):
        fields["needs_assessment"]["status"] = status
        with pytest.raises(ValidationError):
            response_format.model_validate(fields)
    fields["needs_assessment"]["status"] = "does_not_meet"
    response_format.model_validate(fields)


def test_unknown_stock_is_not_treated_as_zero_stock() -> None:
    response_format = recommendation_response_format({**EVIDENCE, "product": {"available_quantity": None}})
    fields = draft().model_dump()
    fields["needs_assessment"]["status"] = "cannot_confirm"
    response_format.model_validate(fields)


def colour_evidence() -> dict:
    return {
        "product": {
            "id": "1",
            "available_quantity": 12,
            "specs": {"demo_options": {"attributes": {"colours": ["Black", "Red", "Rose Gold"]}}},
        },
        "sources": [*EVIDENCE["sources"], {"id": "demo-options:1", "kind": "catalogue"}],
    }


@pytest.mark.parametrize(
    "preferences,language,colour",
    [
        ("I want a Black one", "en", "Black"),
        ("I'd like a rose gold version.", "en", "Rose Gold"),
        ("I prefer a red option of this model", "zh", "红色"),
        ("我想要一个黑色的", "zh", "黑色"),
    ],
)
def test_simple_listed_colour_has_a_stable_cited_answer(preferences: str, language: str, colour: str) -> None:
    evidence = colour_evidence()
    request = RecommendationRequest(preferences=preferences, language=language)
    assessment = listed_colour_assessment(evidence, request)
    assert assessment is not None
    assert colour in assessment.text
    assert assessment.source_ids == ["demo-options:1"]
    fields = draft(needs_assessment=assessment.model_dump()).model_dump()
    response_format = recommendation_response_format(evidence, budget_fit=True, request=request)
    response_format.model_validate(fields)
    validate_recommendation(response_format.model_validate(fields), evidence)
    for field, incorrect in [
        ("status", "cannot_confirm"),
        ("text", "Black is unavailable."),
        ("source_ids", ["r:1"]),
    ]:
        with pytest.raises(ValidationError):
            response_format.model_validate(fields | {"needs_assessment": assessment.model_dump() | {field: incorrect}})


@pytest.mark.parametrize(
    "preferences",
    [
        "I want a green one",
        "I don't want a black one",
        "I want a black one in stock",
        "I want a red one in size M",
        "I want a black one and waterproofing",
        "How many black ones can ship today?",
        "我想要黑色的，但必须防水",
        "我想要一个绿色的",
    ],
)
def test_complex_or_unlisted_colour_requests_are_not_forced_to_match(preferences: str) -> None:
    assert listed_colour_assessment(colour_evidence(), RecommendationRequest(preferences=preferences)) is None


@pytest.mark.parametrize(
    "budget_fit,stock,expected",
    [(False, 12, "does_not_meet"), (True, 0, "does_not_meet"), (True, None, "cannot_confirm")],
)
def test_listed_colour_does_not_override_budget_or_unknown_or_zero_stock(
    budget_fit: bool,
    stock: int | None,
    expected: str,
) -> None:
    evidence = colour_evidence()
    evidence["product"]["available_quantity"] = stock
    request = RecommendationRequest(preferences="I want a black one")
    response_format = recommendation_response_format(evidence, budget_fit=budget_fit, request=request)
    fields = draft(
        needs_assessment={"status": expected, "text": "Other constraint.", "source_ids": ["p:1"]}
    ).model_dump()
    response_format.model_validate(fields)
    if stock is not None:
        fields["needs_assessment"]["status"] = "meets_needs"
        with pytest.raises(ValidationError):
            response_format.model_validate(fields)


@pytest.mark.parametrize("missing", ["source", "colours", "attributes", "specs"])
def test_colour_confirmation_requires_structured_options_and_the_matching_source(missing: str) -> None:
    evidence = colour_evidence()
    if missing == "source":
        evidence["sources"].pop()
    elif missing == "specs":
        evidence["product"]["specs"] = None
    elif missing == "attributes":
        evidence["product"]["specs"]["demo_options"]["attributes"] = None
    else:
        evidence["product"]["specs"]["demo_options"]["attributes"]["colours"] = "Black, Red"
    assert listed_colour_assessment(evidence, RecommendationRequest(preferences="I want a black one")) is None


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
