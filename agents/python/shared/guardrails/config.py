"""Static guardrail policy: which tool outputs carry untrusted content.

Only tools whose results include user-generated / stored text are sanitized;
everything else passes through untouched so structured/numeric results are
never mangled. Tool names match the ``@tool(name=...)`` registrations.

Mapping value is the set of free-text field names to neutralize (at any nesting
depth). Use ``None`` to neutralize *every* string in that tool's result.
"""

from __future__ import annotations

# tool name -> field-name allowlist (None = sanitize all strings)
SANITIZE_TOOLS: dict[str, set[str] | None] = {
    # review-sentiment: review bodies/titles are the top stored-injection vector
    "get_product_reviews": {"title", "body", "review", "comment", "reviewer", "reviewer_name"},
    "analyze_sentiment": {"title", "body", "summary", "quote", "quotes", "theme", "themes", "comment"},
    "compare_reviews": {"title", "body", "summary", "comment"},
    "detect_fake_reviews": {"title", "body", "comment", "reviewer", "reviewer_name"},
    "get_review_trends": {"title", "body", "summary"},
    # product-discovery: descriptions/specs are seller-editable free text
    "search_products": {"name", "description", "specs", "features"},
    "get_product_details": {"name", "description", "specs", "features"},
    "find_similar_products": {"name", "description"},
    "semantic_search": {"name", "description"},
    "get_trending_products": {"name", "description"},
    # order-management: free-text order notes / status history
    "get_order_details": {"note", "notes", "reason", "comment", "description"},
    "get_user_orders": {"note", "notes", "reason"},
}
