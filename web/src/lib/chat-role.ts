import type { AgentMode } from "@/components/ui/ai-prompt-box";
import { QUICK_PROMPTS } from "./scenarios";
import type { Suggestion } from "./suggestions";

interface ChatExperience {
  description: string;
  prompts: Suggestion[];
  modes?: AgentMode[];
}

export function chatExperience(role?: string): ChatExperience {
  if (role === "customer") return {
    description: "Find products, compare prices and reviews, or get help with your purchases and returns.",
    prompts: QUICK_PROMPTS,
  };
  if (role === "store_manager") return {
    description: "Manage store products and inventory, review sales performance, and forecast replenishment needs.",
    prompts: [
      { label: "Store overview", prompt: "Show the current whole-store product and order statistics." },
      { label: "Sales analysis", prompt: "Analyze sales performance over the last 28 days." },
      { label: "Low stock", prompt: "Which store products currently have low stock?" },
    ],
    modes: [
      { id: null, label: "Auto", placeholder: "Ask about store operations, inventory or sales..." },
      { id: "product-discovery", label: "Products", placeholder: "View the whole-store product catalog..." },
      { id: "order-management", label: "Store orders", placeholder: "View whole-store orders and order statistics..." },
      { id: "inventory-fulfillment", label: "Inventory & sales", placeholder: "Analyze sales, forecast demand or manage stock..." },
      { id: "review-sentiment", label: "Reviews", placeholder: "Analyze reviews or draft a response template..." },
    ],
  };
  return {
    description: "Get help using platform monitoring, Agent access requests, return receipt and refund approval pages.",
    prompts: role === "admin" ? [
      { label: "Approval guide", prompt: "Where can I review pending approval requests as a platform administrator?" },
      { label: "Return receipt guide", prompt: "How do I confirm receipt of a returned item on the admin page?" },
      { label: "Platform monitoring guide", prompt: "Where can an administrator view platform usage and run records?" },
    ] : [],
    modes: [{ id: null, label: "Auto", placeholder: "Ask about platform management or approval procedures..." }],
  };
}
