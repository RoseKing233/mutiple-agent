import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CommandPalette } from "./command-palette";

const state = vi.hoisted(() => ({ role: "customer", getOrders: vi.fn() }));
vi.mock("@/lib/auth-context", () => ({ useAuth: () => ({ user: { role: state.role }, isAdmin: state.role === "admin" }) }));
vi.mock("@/lib/api", () => ({ api: { getOrders: state.getOrders } }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

beforeEach(() => {
  vi.clearAllMocks();
  state.getOrders.mockResolvedValue({ orders: [{ id: "12345678-1234-1234-1234-123456789abc", status: "placed", total: 10 }] });
});
describe("command palette shopping controls", () => {
  it.each(["store_manager", "admin"])("omits shopping scenarios and personal-order reads for %s", async (role) => {
    state.role = role;
    render(<CommandPalette />);
    fireEvent(window, new CustomEvent("ecommerce:open-command-palette"));
    expect(await screen.findByRole("dialog")).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Search pages" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Cart" })).toBeNull();
    expect(screen.queryByText("Demo scenarios")).toBeNull();
    expect(screen.queryByText("Recent orders")).toBeNull();
    await waitFor(() => expect(state.getOrders).not.toHaveBeenCalled());
  });
  it("retains shopping navigation, scenarios and order reads for customers", async () => {
    state.role = "customer";
    render(<CommandPalette />);
    fireEvent(window, new CustomEvent("ecommerce:open-command-palette"));
    expect(await screen.findByRole("dialog")).toBeVisible();
    expect(screen.getByRole("button", { name: "Cart" })).toBeVisible();
    expect(screen.getByText("Demo scenarios")).toBeVisible();
    expect(await screen.findByText("Recent orders")).toBeVisible();
    expect(state.getOrders).toHaveBeenCalledOnce();
  });
});
