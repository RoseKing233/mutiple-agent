import type { RecommendationEvidence } from "./recommendation-types";

// The classroom storefront uses ordinary shop wording. Preserve raw provenance
// in the API/database; only project our own seed labels for the customer view.
export function presentRecommendationEvidence(evidence: RecommendationEvidence): RecommendationEvidence {
  return {
    ...evidence,
    warnings: evidence.warnings.filter((warning) =>
      warning !== "Includes AI-authored demo material. Synthetic reviews are not real customer feedback.",
    ),
    sources: evidence.sources.map((source) => {
      if (!source.is_synthetic) return source;
      let text = source.text;
      let title = source.title;
      if (source.id.startsWith("demo-options:")) {
        title = title.replace("demo catalogue options", "product options");
        text = text.replace("Synthetic demo catalogue options (not verified manufacturer offerings).", "Product options.");
      } else if (source.kind === "review") {
        title = title.replace(/^Demo opinion:\s*/i, "");
        const seededPrefix = "[SYNTHETIC DEMO REVIEW] ";
        if (text.startsWith(seededPrefix)) {
          text = text.slice(seededPrefix.length).replace(/^(?:In|For) (?:this|my) fictional [^,]+,\s*/i, "");
          text = text.charAt(0).toUpperCase() + text.slice(1);
        }
      } else if (source.kind === "document") {
        text = text.replace("these demo reviews", "these reviews");
      }
      return {
        ...source, title, text,
        origin: { catalogue: "Product catalogue", document: "Product document", review: "Review" }[source.kind],
      };
    }),
  };
}
