import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import StoreDashboardPage from "./page";

const state = vi.hoisted(() => ({
  role: "store_manager",
  users: {
    store_manager: { role: "store_manager" },
    customer: { role: "customer" },
    admin: { role: "admin" },
  } as Record<string, { role: string }>,
  stats: vi.fn(),
  orders: vi.fn(),
}));

vi.mock("@/lib/auth-context", () => ({
  useAuth: () => ({ user: state.users[state.role], isLoading: false, isAdmin: state.role === "admin" }),
}));
vi.mock("@/lib/api", () => ({
  api: { getStoreStats: state.stats, getStoreOrders: state.orders },
}));

beforeEach(() => {
  vi.clearAllMocks();
  state.role = "store_manager";
  state.stats.mockResolvedValue({ product_count: 50, order_count: 200, item_sales_amount: 1200, avg_rating: 4.5 });
  state.orders.mockResolvedValue({ orders: [{
    id: "order-123", buyer_name: "Alice", buyer_email: "alice@example.test", status: "placed",
    date: "2026-10-30T00:00:00Z", item_count: 2, total: 50,
  }], total: 200 });
});

describe("whole-store overview", () => {
  it.each(["store_manager"])("allows %s to read global orders and metrics", async (role) => {
    state.role = role;
    render(<StoreDashboardPage />);
    expect(await screen.findByText("Alice")).toBeVisible();
    expect(screen.getByRole("heading", { name: "Store Overview" })).toBeVisible();
    expect(screen.getByText("Orders across the entire store")).toBeVisible();
    expect(screen.getByText("Item Sales Amount")).toBeVisible();
    expect(screen.getByRole("link", { name: "Manage Products" })).toHaveAttribute("href", "/inventory");
    expect(state.stats).toHaveBeenCalledOnce();
    expect(state.orders).toHaveBeenCalledOnce();
  });

  it.each(["customer", "admin"])("does not request operating data for %s", async (role) => {
    state.role = role;
    render(<StoreDashboardPage />);
    expect(screen.getByRole("heading", { name: "Access Denied" })).toBeVisible();
    await waitFor(() => expect(state.orders).not.toHaveBeenCalled());
    expect(state.stats).not.toHaveBeenCalled();
  });

  it("shows a failed read instead of a false store summary", async () => {
    state.stats.mockRejectedValue(new Error("Store data unavailable"));
    render(<StoreDashboardPage />);
    expect(await screen.findByText("Store data unavailable")).toBeVisible();
    expect(screen.queryByText("Item Sales Amount")).toBeNull();
  });
});
