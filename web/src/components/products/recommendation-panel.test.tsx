import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RecommendationPanel } from "./recommendation-panel";
import { api } from "@/lib/api";

vi.mock("@/lib/api", () => ({ api: { getRecommendationEvidence: vi.fn(), generateRecommendationReasons: vi.fn() } }));
const source = { id: "review:1", kind: "review", title: "Demo opinion: commute", text: "[SYNTHETIC DEMO REVIEW] In this fictional commute, I liked the noise cancelling.", origin: "Synthetic demo review", is_synthetic: true };
const evidence = {
  sources: [source], warnings: ["Includes AI-authored demo material. Synthetic reviews are not real customer feedback.", "Stock availability is unknown."],
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
  it("can inspect evidence in shop wording without a paid call and retains stock uncertainty", async () => {
    vi.mocked(api.getRecommendationEvidence).mockResolvedValue(evidence as never);
    render(<RecommendationPanel productId="p1" />);
    fireEvent.click(screen.getByText("View product info & reviews"));
    expect(await screen.findByText("I liked the noise cancelling.")).toBeInTheDocument();
    expect(screen.getByText("Stock availability is unknown.")).toBeInTheDocument();
    expect(screen.queryByText(/synthetic|fictional|demo/i)).not.toBeInTheDocument();
    expect(api.generateRecommendationReasons).not.toHaveBeenCalled();
  });
  it("passes zero budget and language, renders reasons with source links", async () => {
    vi.mocked(api.generateRecommendationReasons).mockResolvedValue({
      ...evidence, product_id: "p1", product_name: "Test", preferences: "commuting", budget_fit: false,
      needs_assessment: { status: "does_not_meet", text: "It exceeds your budget.", source_ids: ["review:1"] },
      product_summary: [], review_summary: [], cautions: [],
      reasons: [{ text: "This review describes commuting.", source_ids: ["review:1"] }],
      usage: { input_tokens: 10, output_tokens: 5 },
    } as never);
    render(<RecommendationPanel productId="p1" />);
    fireEvent.change(screen.getByLabelText("Your needs and intended use"), { target: { value: "commuting" } });
    fireEvent.change(screen.getByLabelText("Maximum budget (USD, optional)"), { target: { value: "0" } });
    fireEvent.change(screen.getByLabelText("Response language"), { target: { value: "zh" } });
    fireEvent.click(screen.getByText("Assess this product for me"));
    expect(await screen.findByText("This review describes commuting.")).toBeInTheDocument();
    expect(api.generateRecommendationReasons).toHaveBeenCalledWith("p1", {preferences: "commuting", max_budget: 0, language: "zh"}, expect.any(AbortSignal));
    const directAnswer = screen.getByRole("region", { name: "Answer to your request" });
    expect(within(directAnswer).getByRole("link", { name: "[1]" })).toHaveAttribute("href", "#p1-review:1");
    const details = screen.getByText("Sources (1)").closest("details");
    expect(details).not.toHaveAttribute("open");
    fireEvent.click(within(directAnswer).getByRole("link", { name: "[1]" }));
    expect(details).toHaveAttribute("open");
    expect(screen.getByText("This product exceeds your stated budget.")).toBeInTheDocument();
  });
  it("answers the missing colour question before summaries even when the budget fits", async () => {
    const catalogue = { ...source, id: "product:1", kind: "catalogue", title: "Bottle", text: "32oz steel bottle", is_synthetic: false };
    vi.mocked(api.generateRecommendationReasons).mockResolvedValue({
      ...evidence, sources: [catalogue], product_id: "p1", product_name: "Bottle", preferences: "I want red", budget_fit: true,
      needs_assessment: { status: "cannot_confirm", text: "A red version cannot be confirmed because colours are not specified. Check the colour options with the seller.", source_ids: ["product:1"] },
      product_summary: [{ text: "32oz steel bottle", source_ids: ["product:1"] }], review_summary: [],
      reasons: [{ text: "It is within budget.", source_ids: ["product:1"] }], cautions: [],
      usage: { input_tokens: 10, output_tokens: 5 },
    } as never);
    render(<RecommendationPanel productId="p1" />);
    fireEvent.change(screen.getByLabelText("Your needs and intended use"), { target: { value: "I want red" } });
    fireEvent.click(screen.getByText("Assess this product for me"));
    const answer = await screen.findByRole("region", { name: "Answer to your request" });
    const status = within(answer).getByText("Some details still need confirmation — see the explanation above.");
    expect(within(answer).getByText(/A red version cannot be confirmed/).compareDocumentPosition(status) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(answer).toHaveTextContent("A red version cannot be confirmed");
    expect(answer.compareDocumentPosition(screen.getByRole("heading", { name: "Product and document summary" })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(answer.compareDocumentPosition(screen.getByText("Stock availability is unknown.")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.queryByText("Supported by the available evidence")).not.toBeInTheDocument();
    fireEvent.click(within(answer).getByRole("link", { name: "[1]" }));
    expect(screen.getByText("Sources (1)").closest("details")).toHaveAttribute("open");
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

  it.each([
    ["Your needs and intended use", "I need a different colour"],
    ["Maximum budget (USD, optional)", "1"],
    ["Response language", "zh"],
  ])("clears the previous assessment when %s changes", async (label, value) => {
    vi.mocked(api.generateRecommendationReasons).mockResolvedValue({
      ...evidence, product_id: "p1", product_name: "Bottle", preferences: "I want black", budget_fit: true,
      needs_assessment: { status: "meets_needs", text: "Black is listed and fits your budget.", source_ids: ["review:1"] },
      product_summary: [], review_summary: [], reasons: [], cautions: [], usage: { input_tokens: 10, output_tokens: 5 },
    } as never);
    render(<RecommendationPanel productId="p1" />);
    fireEvent.change(screen.getByLabelText("Your needs and intended use"), { target: { value: "I want black" } });
    fireEvent.click(screen.getByText("Assess this product for me"));
    await screen.findByRole("region", { name: "Answer to your request" });
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
    expect(screen.queryByRole("region", { name: "Answer to your request" })).not.toBeInTheDocument();
    expect(api.generateRecommendationReasons).toHaveBeenCalledTimes(1);
  });

  it.each(["-1", "1000001"])("rejects invalid budget %s without spending an AI request", async (value) => {
    render(<RecommendationPanel productId="p1" />);
    fireEvent.change(screen.getByLabelText("Your needs and intended use"), { target: { value: "commuting" } });
    fireEvent.change(screen.getByLabelText("Maximum budget (USD, optional)"), { target: { value } });
    fireEvent.click(screen.getByText("Assess this product for me"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter a budget between");
    expect(api.generateRecommendationReasons).not.toHaveBeenCalled();
  });

  it("allows retry after a failure and prevents duplicate requests while waiting", async () => {
    vi.mocked(api.generateRecommendationReasons)
      .mockRejectedValueOnce(new Error("AI recommendation is unavailable."))
      .mockReturnValueOnce(new Promise(() => {}));
    render(<RecommendationPanel productId="p1" />);
    fireEvent.change(screen.getByLabelText("Your needs and intended use"), { target: { value: "commute" } });
    const submit = screen.getByText("Assess this product for me");
    fireEvent.click(submit);
    await screen.findByRole("alert");
    fireEvent.click(submit);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(submit).toBeDisabled();
    fireEvent.click(submit);
    expect(api.generateRecommendationReasons).toHaveBeenCalledTimes(2);
  });
});
