import { test, expect, type Page } from "@playwright/test";

// Live read-only acceptance; no model calls, orders or inventory mutations.
test.use({ channel: "chrome" });

async function login(page: Page, email: string, password: string) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
}

test("manager operates the whole store without a seller entry", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await login(page, "manager.demo@gmail.com", "manager123");
  await expect(page).toHaveURL(/\/analysis/);
  const nav = page.locator("aside nav");
  await expect(nav.getByRole("link", { name: "Seller", exact: true })).toHaveCount(0);
  await expect(nav.getByRole("link", { name: "Approvals", exact: true })).toHaveCount(0);
  await nav.getByRole("link", { name: "Store Overview", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Store Overview", exact: true })).toBeVisible();
  await expect(page.getByText("Orders across the entire store", { exact: true })).toBeVisible();
  await expect(page.getByText("Item Sales Amount", { exact: true })).toBeVisible();
  await page.screenshot({ path: "../.claude/single-store-checks/manager-store-overview.png", fullPage: true });
  await page.getByRole("link", { name: "Manage Products", exact: true }).click();
  await expect(page).toHaveURL(/\/inventory/);
  await page.goto("/seller");
  await expect(page).toHaveURL(/\/management/);
  await page.goto("/seller/products");
  await expect(page).toHaveURL(/\/products/);
  expect(errors).toEqual([]);
});

test("customer cannot enter whole-store management", async ({ page }) => {
  await login(page, "alice.johnson@gmail.com", "customer123");
  await expect(page).toHaveURL(/\/chat/);
  const nav = page.locator("aside nav");
  await expect(nav.getByRole("link", { name: "Store Overview", exact: true })).toHaveCount(0);
  await expect(nav.getByRole("link", { name: "Inventory", exact: true })).toHaveCount(0);
  await page.goto("/management");
  await expect(page).toHaveURL(/\/chat/);
});


test("admin has platform approvals without shopping or store operations", async ({ page }) => {
  await login(page, "admin@test.com", "12345678");
  await expect(page).toHaveURL(/\/admin$/);
  const nav = page.locator("aside nav");
  for (const name of ["Home", "Cart", "Orders", "Products", "Inventory", "Store Overview", "Analysis & Forecast"]) {
    await expect(nav.getByRole("link", { name, exact: true })).toHaveCount(0);
  }
  for (const name of ["Overview", "Approvals", "Returns", "Usage"]) {
    await expect(nav.getByRole("link", { name, exact: true })).toBeVisible();
  }
  for (const path of ["/cart", "/orders", "/management", "/inventory", "/analysis", "/products"]) {
    await page.goto(path);
    await expect(page).toHaveURL(/\/admin$/);
  }
  await nav.getByRole("link", { name: "Returns", exact: true }).click();
  await expect(page).toHaveURL(/\/admin\/returns/);
});


for (const role of ["manager", "admin"] as const) {
  test(`${role} sees no shopping controls in chat, search or profile`, async ({ page }) => {
    await login(page, `${role}@test.com`, "12345678");
    await expect(page).toHaveURL(role === "admin" ? /\/admin$/ : /\/analysis/);
    await page.goto("/chat");
    await expect(page.getByRole("link", { name: "Cart", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Product Search", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: role === "admin" ? "Approval guide" : "Low stock", exact: true }).first()).toBeVisible();
    await page.getByRole("button", { name: "Search (Cmd+K)" }).click();
    const search = page.getByRole("dialog");
    await expect(search.getByRole("textbox", { name: "Search pages", exact: true })).toBeVisible();
    await expect(search.getByRole("button", { name: "Cart", exact: true })).toHaveCount(0);
    await expect(search.getByText("Demo scenarios", { exact: true })).toHaveCount(0);
    await expect(search.getByText("Recent orders", { exact: true })).toHaveCount(0);
    await page.keyboard.press("Escape");
    await page.goto("/profile");
    await expect(page.getByText("Account Details", { exact: true })).toBeVisible();
    await expect(page.getByText("Total Spend", { exact: true })).toHaveCount(0);
    await expect(page.getByText("Loyalty Benefits", { exact: true })).toHaveCount(0);
    await page.screenshot({ path: `../.claude/single-store-checks/${role}-profile-no-shopping.png`, fullPage: true });
  });
}

test("customer keeps chat shopping and the cart page", async ({ page }) => {
  await login(page, "user@test.com", "12345678");
  await expect(page).toHaveURL(/\/chat/);
  await expect(page.getByRole("link", { name: "Cart", exact: true }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Product Search", exact: true }).first()).toBeVisible();
  await page.goto("/cart");
  await expect(page.getByRole("heading", { name: "Shopping Cart", exact: true })).toBeVisible();
});
