import { describe, expect, it } from "vitest";
import { presentRecommendationEvidence } from "./recommendation-presentation";
import type { RecommendationEvidence } from "./recommendation-types";

describe("storefront evidence presentation", () => {
  it("retains source identities and raw provenance without displaying seed labels", () => {
    const evidence: RecommendationEvidence = {
      sources: [{
        id: "demo-options:p1", kind: "catalogue", title: "Bottle demo catalogue options",
        text: "Synthetic demo catalogue options (not verified manufacturer offerings).\nColours: Red, Black\nStock per colour is unknown.",
        origin: "Synthetic classroom options", is_synthetic: true,
      }],
      warnings: ["Includes AI-authored demo material. Synthetic reviews are not real customer feedback.", "This product is currently out of stock."],
      review_statistics: { count: 0, sample_size: 0, synthetic_count: 0, average_rating: null },
    };
    const before = structuredClone(evidence);
    const displayed = presentRecommendationEvidence(evidence);
    expect(evidence).toEqual(before);
    expect(displayed.sources[0]).toMatchObject({ id: "demo-options:p1", title: "Bottle product options", origin: "Product catalogue", is_synthetic: true });
    expect(displayed.sources[0].text).toContain("Colours: Red, Black");
    expect(displayed.sources[0].text).toContain("Stock per colour is unknown.");
    expect(displayed.sources[0].text).not.toMatch(/synthetic|demo/i);
    expect(displayed.warnings).toEqual(["This product is currently out of stock."]);
  });
  it("does not rewrite ordinary source text that happens to mention a demo", () => {
    const evidence: RecommendationEvidence = {
      sources: [{ id: "review:1", kind: "review", title: "Shop demo", text: "I tried the demo in store.", origin: "Stored review", is_synthetic: false }],
      warnings: [], review_statistics: { count: 1, sample_size: 1, synthetic_count: 0, average_rating: 4 },
    };
    expect(presentRecommendationEvidence(evidence).sources[0]).toEqual(evidence.sources[0]);
  });
});
