import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ProfilePage from "./page";

const state = vi.hoisted(() => ({ role: "customer" }));
vi.mock("@/lib/auth-context", () => ({ useAuth: () => ({ user: { role: state.role }, isLoading: false }) }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn() }) }));
vi.mock("@/lib/api", () => ({ api: {
  getProfile: async () => ({
    id: "12345678-1234-1234-1234-123456789abc", email: "role@test.com", name: "Demo Account", role: state.role,
    loyalty_tier: "bronze", total_spend: 0, order_count: 0, review_count: 0, member_since: "2026-01-01T00:00:00Z",
    tier_benefits: { discount_pct: 0, free_shipping_threshold: null, priority_support: false },
  }),
  getUserMemories: async () => [],
} }));
beforeEach(() => { state.role = "customer"; });
describe("profile shopping panels", () => {
  it.each(["store_manager", "admin"])("omits customer spending and loyalty panels for %s", async (role) => {
    state.role = role;
    render(<ProfilePage />);
    expect(await screen.findByText("Account Details")).toBeVisible();
    expect(screen.queryByText("Your account details and loyalty status")).toBeNull();
    expect(screen.queryByText("Loyalty Tier")).toBeNull();
    expect(screen.queryByText("Total Spend")).toBeNull();
    expect(screen.queryByText("Loyalty Benefits")).toBeNull();
  });
  it("retains spending and membership details for customers", async () => {
    render(<ProfilePage />);
    expect(await screen.findByText("Loyalty Tier")).toBeVisible();
    expect(screen.getByText("Total Spend")).toBeVisible();
    expect(screen.getByText("Loyalty Benefits")).toBeVisible();
  });
});
