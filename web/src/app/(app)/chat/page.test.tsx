import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ChatPage from "./page";

const transport = vi.hoisted(() => ({ chatStream: vi.fn(), getConversations: vi.fn(), role: "customer" }));
vi.mock("@/lib/api", () => ({ api: transport }));
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams() }));
vi.mock("@/lib/auth-context", () => ({ useAuth: () => ({ isAuthenticated: true, user: { role: transport.role } }) }));
vi.mock("@/lib/cart-context", () => ({ useCart: () => ({ itemCount: 0 }) }));
vi.mock("@/components/chat/mode-switcher", () => ({ ModeSwitcher: () => null }));
vi.mock("@/components/chat/mode-comparison", () => ({ ModeComparison: () => null }));
vi.mock("@/components/chat/orchestration-graph", () => ({ OrchestrationGraph: () => null }));
vi.mock("@/components/chat/grounding-badge", () => ({ GroundingBadge: () => null }));
vi.mock("@/components/chat/rich-message", () => ({ RichMessage: ({ content }: { content: string }) => <p>{content}</p> }));
vi.mock("@/components/chat/agent-timeline", () => ({ AgentTimeline: ({ steps }: { steps: unknown[] }) => <span>{steps.length} recorded steps</span> }));
vi.mock("@/components/ui/ai-prompt-box", () => ({
  AGENT_MODES: [],
  PromptInputBox: ({ onSend }: { onSend: (message: string) => void }) => <button onClick={() => onSend("Analyze Books")}>Send test request</button>,
}));

const step = { agent: "inventory-fulfillment", tool_name: "analyze_product_performance", tool_input: {}, tool_output: {}, status: "success", duration_ms: 29 };

beforeEach(() => {
  vi.clearAllMocks();
  transport.role = "customer";
  transport.getConversations.mockResolvedValue([]);
  Element.prototype.scrollIntoView = vi.fn();
});

describe("chat stream message identity", () => {
  it.each([false, true])("keeps one reply when a tool step and text share a batch (preview=%s)", async (preview) => {
    // SSE can deliver a tool step and text in the same reader chunk. Both
    // callbacks run before React commits its pending state updates.
    transport.chatStream.mockImplementation(async (_message, _id, onChunk, _signal, options) => {
      options.onStep(step);
      if (preview) options.onDeltaChunk("Specialist preview");
      onChunk("Final analysis");
      onChunk(" from the agent.");
      return { conversation_id: "conversation-1", agents_involved: ["inventory-fulfillment"] };
    });
    render(<ChatPage />);
    fireEvent.click(screen.getByRole("button", { name: "Send test request" }));
    await waitFor(() => expect(screen.getAllByText("Final analysis from the agent.")).toHaveLength(1));
    expect(screen.getAllByText("1 recorded steps")).toHaveLength(1);
    expect(screen.queryByText(/Specialist preview/)).not.toBeInTheDocument();
    expect(transport.chatStream).toHaveBeenCalledTimes(1);
  });

  it("keeps graph, tool and text events on the same reply", async () => {
    transport.chatStream.mockImplementation(async (_message, _id, onChunk, _signal, options) => {
      options.onOrchestrationEvent("node", { node_id: "inventory", phase: "enter" });
      options.onStep(step);
      onChunk("One graph answer");
      options.onOrchestrationEvent("node", { node_id: "inventory", phase: "exit" });
      return { conversation_id: "conversation-1", agents_involved: ["inventory-fulfillment"] };
    });
    render(<ChatPage />);
    fireEvent.click(screen.getByRole("button", { name: "Send test request" }));
    await waitFor(() => expect(screen.getAllByText("One graph answer")).toHaveLength(1));
    expect(screen.getAllByText("1 recorded steps")).toHaveLength(1);
  });
});


describe("role-specific chat controls", () => {
  it("keeps the customer cart and shopping prompts", () => {
    render(<ChatPage />);
    expect(screen.getByRole("link", { name: "Cart" })).toHaveAttribute("href", "/cart");
    expect(screen.getByRole("button", { name: "Product Search" })).toBeVisible();
  });
  it.each(["store_manager", "admin"])("hides shopping controls for %s", (role) => {
    transport.role = role;
    render(<ChatPage />);
    expect(screen.queryByRole("link", { name: "Cart" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Product Search" })).toBeNull();
    expect(screen.getByRole("button", { name: role === "admin" ? "Approval guide" : "Low stock" })).toBeVisible();
  });
});
