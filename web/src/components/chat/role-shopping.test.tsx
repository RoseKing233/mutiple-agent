import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ChatProductCard } from "./product-card";
import { ChatCheckoutCard } from "./checkout-card";
import { ChatOrderCard } from "./order-card";

const state = vi.hoisted(() => ({ role: "customer", addItem: vi.fn() }));
vi.mock("@/lib/auth-context", () => ({ useAuth: () => ({ user: { role: state.role }, isAuthenticated: true }) }));
vi.mock("@/lib/cart-context", () => ({ useCart: () => ({ cart: null, addItem: state.addItem }) }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

beforeEach(() => { state.role = "customer"; });

describe("shopping card actions", () => {
  it.each(["store_manager", "admin"])("hides purchase and personal-order actions for %s", (role) => {
    state.role = role;
    render(<>
      <ChatProductCard data={{ id: "12345678-1234-1234-1234-123456789abc", name: "Book", price: 10 }} />
      <ChatCheckoutCard data={{ total: 10 }} />
      <ChatOrderCard data={{ id: "order1", status: "placed" }} onAction={vi.fn()} />
    </>);
    expect(screen.queryByRole("button", { name: "Add to Cart" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Complete Checkout" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Cancel" })).toBeNull();
    expect(screen.queryByRole("link", { name: "View" })).toBeNull();
  });
  it("retains purchase and cancellation actions for a customer", () => {
    render(<>
      <ChatProductCard data={{ id: "12345678-1234-1234-1234-123456789abc", name: "Book", price: 10 }} />
      <ChatCheckoutCard data={{ total: 10 }} />
      <ChatOrderCard data={{ id: "order1", status: "placed" }} onAction={vi.fn()} />
    </>);
    expect(screen.getByRole("button", { name: "Add to Cart" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Complete Checkout" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeVisible();
  });
});
