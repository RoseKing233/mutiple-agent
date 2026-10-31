import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CartProvider, useCart } from "./cart-context";

const state = vi.hoisted(() => ({ role: "customer", getCart: vi.fn(), addToCart: vi.fn() }));
vi.mock("@/lib/auth-context", () => ({ useAuth: () => ({ user: { role: state.role }, isAuthenticated: true }) }));
vi.mock("@/lib/api", () => ({ api: { getCart: state.getCart, addToCart: state.addToCart } }));
function Probe() {
  const { addItem } = useCart();
  return <button onClick={() => { void addItem("product").catch(() => {}); }}>Add item</button>;
}
beforeEach(() => {
  vi.clearAllMocks();
  state.getCart.mockResolvedValue({ item_count: 0, items: [] });
  state.addToCart.mockResolvedValue({});
});
describe("cart provider role enforcement", () => {
  it.each(["store_manager", "admin"])("does not fetch or mutate a cart for %s", async (role) => {
    state.role = role;
    render(<CartProvider><Probe /></CartProvider>);
    fireEvent.click(screen.getByRole("button", { name: "Add item" }));
    await waitFor(() => {
      expect(state.getCart).not.toHaveBeenCalled();
      expect(state.addToCart).not.toHaveBeenCalled();
    });
  });
  it("fetches and updates the cart for a customer", async () => {
    state.role = "customer";
    render(<CartProvider><Probe /></CartProvider>);
    await waitFor(() => expect(state.getCart).toHaveBeenCalledOnce());
    fireEvent.click(screen.getByRole("button", { name: "Add item" }));
    await waitFor(() => expect(state.addToCart).toHaveBeenCalledWith("product", 1));
  });
});
