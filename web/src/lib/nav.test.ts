import { describe, expect, it } from "vitest";
import { visibleGroups, labelForPath } from "./nav";

describe("visibleGroups", () => {
  it("gives managers analysis and products without shopping or admin navigation", () => {
    const groups = visibleGroups({ isAdmin: false, isManager: true });
    const paths = groups.flatMap((g) => g.items.map((i) => i.href));
    expect(paths).toContain("/analysis");
    expect(paths).toContain("/management");
    expect(paths).toContain("/inventory");
    expect(paths).not.toContain("/seller");
    expect(paths).toContain("/products");
    expect(paths).toContain("/chat");
    expect(paths).not.toContain("/cart");
    expect(paths).not.toContain("/orders");
    expect(paths).not.toContain("/admin");
    expect(groups[0].label).toBe("Store");
  });
  it("shows shop + account to a plain customer, hides admin/seller", () => {
    const groups = visibleGroups({ isAdmin: false });
    const labels = groups.flatMap((g) => g.items.map((i) => i.label));
    expect(labels).toContain("Home");
    expect(labels).toContain("Chat");
    expect(labels).toContain("Agents"); // visible to all authenticated users
    expect(labels).toContain("Runs");   // Phase 4 — visible to all users
    expect(labels).toContain("Profile");
    expect(labels).not.toContain("Usage"); // adminOnly
    expect(labels).not.toContain("Seller"); // sellerOnly
    expect(labels).not.toContain("Marketplace");
    expect(groups.find((g) => g.label === "Admin")).toBeUndefined();
  });

  it("shows whole-store operations to a manager but not admin approval items", () => {
    const groups = visibleGroups({ isAdmin: false, isManager: true });
    const labels = groups.flatMap((g) => g.items.map((i) => i.label));
    expect(labels).toContain("Store Overview");
    expect(labels).toContain("Inventory");
    expect(labels).not.toContain("Seller");
    expect(labels).not.toContain("Approvals");
    expect(labels).not.toContain("Usage");
  });

  it("shows admin items (Overview, Approvals, Usage) to an admin — no old labels", () => {
    const groups = visibleGroups({ isAdmin: true });
    const labels = groups.flatMap((g) => g.items.map((i) => i.label));
    expect(labels).toContain("Overview");
    expect(labels).toContain("Approvals");
    expect(labels).toContain("Usage");
    expect(labels).toContain("Runs"); // single Runs entry, from the Shop group
    expect(labels).not.toContain("Store Overview");
    expect(labels).not.toContain("Inventory");
    expect(labels).not.toContain("Analysis & Forecast");
    expect(labels).not.toContain("Home");
    expect(labels).not.toContain("Cart");
    expect(labels).not.toContain("Orders");
    expect(labels).not.toContain("Products");
    expect(labels).not.toContain("Seller");
    expect(labels).not.toContain("Requests");
    expect(labels).not.toContain("Audit");
    // Only ONE "Runs" entry now (the admin /admin/audit duplicate was removed)
    expect(labels.filter((l) => l === "Runs")).toHaveLength(1);
  });
});

describe("labelForPath", () => {
  it("matches the most specific nav item", () => {
    expect(labelForPath("/admin/usage")).toBe("Usage");
    expect(labelForPath("/admin")).toBe("Overview");
    expect(labelForPath("/runs")).toBe("Runs"); // the single user-facing runs page
  });

  it("matches nested detail routes to their parent item", () => {
    expect(labelForPath("/orders/abc-123")).toBe("Orders");
    expect(labelForPath("/products/p1")).toBe("Products");
    expect(labelForPath("/agents/product-discovery")).toBe("Agents");
  });

  it("falls back to Home for unknown paths", () => {
    expect(labelForPath("/totally-unknown")).toBe("Home");
  });
});
