import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RecommendationPanel } from "./recommendation-panel";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({ api: { getRecommendationEvidence: vi.fn(), generateRecommendationReasons: vi.fn() } }));
const source = { id: "review:1", kind: "review", title: "Commuting review", text: "Fictional demo feedback", origin: "Synthetic demo review", is_synthetic: true };
const evidence = {
  sources: [source], warnings: ["Synthetic reviews are not real customer feedback."],
  review_statistics: { count: 1, sample_size: 1, synthetic_count: 1, average_rating: 4 },
};
beforeEach(() => vi.resetAllMocks());

describe("recommendation panel", () => {
  it("loads no paid content automatically and validates the request", async () => {
    render(<RecommendationPanel productId="p1" />);
    expect(api.generateRecommendationReasons).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Assess this product for me"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Describe how you plan to use this product");
    expect(api.generateRecommendationReasons).not.toHaveBeenCalled();
  });
  it("can inspect evidence without calling the AI and labels demo reviews", async () => {
    vi.mocked(api.getRecommendationEvidence).mockResolvedValue(evidence as never);
    render(<RecommendationPanel productId="p1" />);
    fireEvent.click(screen.getByText("View product info & reviews"));
    expect(await screen.findByText("Fictional demo feedback")).toBeInTheDocument();
    expect(screen.getByText("Synthetic reviews are not real customer feedback.")).toBeInTheDocument();
    expect(api.generateRecommendationReasons).not.toHaveBeenCalled();
  });
  it("passes zero budget and language, renders reasons with source links", async () => {
    vi.mocked(api.generateRecommendationReasons).mockResolvedValue({
      ...evidence, product_id: "p1", product_name: "Test", preferences: "commuting", budget_fit: false,
      product_summary: [], review_summary: [], cautions: [],
      reasons: [{ text: "This demo review describes commuting.", source_ids: ["review:1"] }],
      usage: { input_tokens: 10, output_tokens: 5 },
    } as never);
    render(<RecommendationPanel productId="p1" />);
    fireEvent.change(screen.getByLabelText("Your needs and intended use"), { target: { value: "commuting" } });
    fireEvent.change(screen.getByLabelText("Maximum budget (USD, optional)"), { target: { value: "0" } });
    fireEvent.change(screen.getByLabelText("Response language"), { target: { value: "zh" } });
    fireEvent.click(screen.getByText("Assess this product for me"));
    expect(await screen.findByText("This demo review describes commuting.")).toBeInTheDocument();
    expect(api.generateRecommendationReasons).toHaveBeenCalledWith("p1", {preferences: "commuting", max_budget: 0, language: "zh"}, expect.any(AbortSignal));
    expect(screen.getByRole("link", { name: "[1]" })).toHaveAttribute("href", "#p1-review:1");
    const details = screen.getByText("Sources (1)").closest("details");
    expect(details).not.toHaveAttribute("open");
    fireEvent.click(screen.getByRole("link", { name: "[1]" }));
    expect(details).toHaveAttribute("open");
    expect(screen.getByText("This product exceeds your stated budget.")).toBeInTheDocument();
  });
  it("shows service failure and restores the button", async () => {
    vi.mocked(api.generateRecommendationReasons).mockRejectedValue(new Error("AI recommendation is unavailable."));
    render(<RecommendationPanel productId="p1" />);
    fireEvent.change(screen.getByLabelText("Your needs and intended use"), { target: { value: "commute" } });
    fireEvent.click(screen.getByText("Assess this product for me"));
    expect(await screen.findByRole("alert")).toHaveTextContent("unavailable");
    await waitFor(() => expect(screen.getByText("Assess this product for me")).toBeEnabled());
  });
  it("aborts pending work on leaving a product", async () => {
    vi.mocked(api.getRecommendationEvidence).mockReturnValue(new Promise(() => {}));
    const view = render(<RecommendationPanel productId="p1" />);
    fireEvent.click(screen.getByText("View product info & reviews"));
    const signal = vi.mocked(api.getRecommendationEvidence).mock.calls[0][1];
    expect(signal?.aborted).toBe(false);
    view.unmount();
    expect(signal?.aborted).toBe(true);
  });
});
