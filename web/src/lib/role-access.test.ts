import { describe, expect, it } from "vitest";
import { roleHome, roleRedirect } from "./role-access";

describe("separate business areas", () => {
  it("gives every role its own landing page", () => {
    expect(roleHome("admin")).toBe("/admin");
    expect(roleHome("store_manager")).toBe("/analysis");
    expect(roleHome("customer")).toBe("/chat");
  });
  it.each(["/home", "/cart", "/checkout", "/orders", "/orders/123"])("only customers use %s", (path) => {
    expect(roleRedirect("customer", path)).toBeNull();
    expect(roleRedirect("store_manager", path)).toBe("/analysis");
    expect(roleRedirect("admin", path)).toBe("/admin");
  });
  it.each(["/management", "/inventory", "/analysis", "/seller", "/seller/products"])("only managers use %s", (path) => {
    expect(roleRedirect("store_manager", path)).toBeNull();
    expect(roleRedirect("customer", path)).toBe("/chat");
    expect(roleRedirect("admin", path)).toBe("/admin");
  });
  it("reserves admin pages and keeps the public catalog separate from shopping", () => {
    expect(roleRedirect("customer", "/admin/returns")).toBe("/chat");
    expect(roleRedirect("store_manager", "/admin/returns")).toBe("/analysis");
    expect(roleRedirect("admin", "/admin/returns")).toBeNull();
    expect(roleRedirect("admin", "/products/123")).toBe("/admin");
    expect(roleRedirect("customer", "/products/123")).toBeNull();
    expect(roleRedirect("store_manager", "/products/123")).toBeNull();
  });
});
