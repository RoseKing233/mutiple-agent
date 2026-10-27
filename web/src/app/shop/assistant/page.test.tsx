import { StrictMode } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import AssistantPage from "./page";
import { api } from "@/lib/api";

vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams() }));

afterEach(() => {
  vi.restoreAllMocks();
  Reflect.deleteProperty(HTMLElement.prototype, "scrollTo");
});

describe("storefront assistant streaming in Strict Mode", () => {
  it("displays each chunk and tool step once and preserves earlier replies", async () => {
    Object.defineProperty(HTMLElement.prototype, "scrollTo", { configurable: true, value: vi.fn() });
    const chat = vi.spyOn(api, "chatStream").mockImplementation(async (_message, _id, onChunk, _signal, options) => {
      onChunk("The Sony headphones ");
      await Promise.resolve();
      onChunk("cost $299.99.");
      options?.onStep?.({ agent: "product-discovery", tool_name: "search_products", status: "success", duration_ms: 5 });
      return { conversation_id: "", agents_involved: ["product-discovery"] };
    });
    render(<StrictMode><AssistantPage /></StrictMode>);
    fireEvent.click(screen.getByRole("button", { name: "Find me wireless headphones under $300" }));
    expect(await screen.findByText("The Sony headphones cost $299.99.")).toBeInTheDocument();
    expect(screen.getByText("Agent activity · 1 step")).toBeInTheDocument();
    expect(screen.getAllByText("search_products")).toHaveLength(1);
    expect(chat).toHaveBeenCalledTimes(1);

    chat.mockImplementationOnce(async (_message, _id, onChunk) => {
      onChunk("No matching dresses.");
      return { conversation_id: "", agents_involved: ["product-discovery"] };
    });
    fireEvent.change(screen.getByPlaceholderText("Ask about products…"), { target: { value: "Find a dress" } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Send" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("No matching dresses.")).toBeInTheDocument();
    expect(screen.getAllByText("The Sony headphones cost $299.99.")).toHaveLength(1);
  });
});
