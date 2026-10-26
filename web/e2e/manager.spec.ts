import { test, expect, type Page } from "@playwright/test";

// Live seeded Python backend. Uses the installed Chrome, with a fresh headless profile.
test.use({ channel: "chrome" });

async function login(page: Page, email = "manager.demo@gmail.com", password = "manager123") {
  await page.goto("/login");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
}

test("manager login, navigation, product performance and sales orders", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await login(page);
  await expect(page).toHaveURL(/\/analysis/);
  await expect(page.getByRole("heading", { name: "Inventory & Sales Analysis", exact: true })).toBeVisible();
  await expect(page.getByText("50 products selected", { exact: true })).toBeVisible();
  const nav = page.locator("aside nav");
  await expect(nav.getByRole("link", { name: "Cart", exact: true })).toHaveCount(0);
  await expect(nav.getByRole("link", { name: "Orders", exact: true })).toHaveCount(0);
  await expect(nav.getByRole("link", { name: "Analysis & Forecast" })).toBeVisible();
  await expect(page.getByRole("table", { name: "Product performance classification" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Generate & save forecast", exact: true })).toBeVisible();
  await page.screenshot({ path: "../.claude/manager-dashboard-desktop.png", fullPage: true });
  await nav.getByRole("link", { name: "Products", exact: true }).click();
  await expect(page.getByRole("table", { name: "Product sales and current inventory" })).toBeVisible();
  await expect(page.getByRole("button", { name: /add to cart/i })).toHaveCount(0);
  await page.getByRole("table").locator("tbody tr").first().getByRole("link").first().click();
  await expect(page.getByRole("heading", { name: "Current stock by warehouse" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Related sales orders" })).toBeVisible();
  await expect(page.getByText("Read-only · selected period", { exact: false })).toBeVisible();
  await page.getByRole("link", { name: "Open analysis →", exact: true }).click();
  await expect(page.getByText("1 product selected", { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});

test("forecast generation, per-product curves and persisted report reload", async ({ page }) => {
  await login(page);
  await expect(page.getByText("50 products selected", { exact: true })).toBeVisible();
  await page.getByLabel("Category", { exact: true }).selectOption("Books");
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect(page.getByText("10 products selected", { exact: true })).toBeVisible();
  await page.getByLabel("Forecast horizon", { exact: true }).selectOption("7");
  const responsePromise = page.waitForResponse((r) => r.url().includes("/api/manager/analysis-runs") && r.request().method() === "POST");
  await page.getByRole("button", { name: "Generate & save forecast", exact: true }).click();
  const response = await responsePromise;
  expect(response.ok()).toBe(true);
  const report = await response.json();
  await expect(page.getByText(`Saved report · ${report.parameters.as_of} · 7 days`, { exact: true })).toBeVisible();
  await expect(page.getByRole("table", { name: "Forecast stockout risks" })).toBeVisible();
  const available = report.products.find((p: { forecast: { available: boolean } }) => p.forecast.available);
  expect(available).toBeTruthy();
  await page.getByLabel("Forecast product", { exact: true }).selectOption(available.product_id);
  await expect(page.getByText("Model comparison & backtest errors", { exact: true })).toBeVisible();
  await page.locator('[aria-label="Saved forecast result"]').screenshot({ path: "../.claude/manager-forecast.png" });
  await page.goto(`/analysis?run_id=${report.id}`);
  await expect(page.getByText(`Saved report · ${report.parameters.as_of} · 7 days`, { exact: true })).toBeVisible();
  await page.getByText("Saved performance, assumptions & reproducibility", { exact: true }).click();
  await expect(page.getByText(`Report ID: ${report.id}`, { exact: false })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("category and date filters, invalid dates, mobile and direct shopping routes", async ({ page }) => {
  await login(page);
  await expect(page.getByText("50 products selected", { exact: true })).toBeVisible();
  await page.getByLabel("Category", { exact: true }).selectOption("Books");
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect(page.getByText("10 products selected", { exact: true })).toBeVisible();
  await expect(page).toHaveURL(/category=Books/);
  await page.reload();
  await expect(page.getByLabel("Category", { exact: true })).toHaveValue("Books");
  await page.getByLabel("Start date", { exact: true }).fill("2026-10-01");
  await page.getByLabel("End date", { exact: true }).fill("2026-01-01");
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect(page.getByText("Start date must not be after end date", { exact: true })).toBeVisible();
  await page.goto("/cart");
  await expect(page).toHaveURL(/\/analysis/);
  await expect(page.getByText("50 products selected", { exact: true })).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: "../.claude/manager-dashboard-mobile.png", fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("customer keeps shopping and cannot open or query manager analysis", async ({ page }) => {
  await login(page, "alice.johnson@gmail.com", "customer123");
  await expect(page).toHaveURL(/\/chat/);
  await page.goto("/products");
  await expect(page.getByRole("heading", { name: "Product Catalog" })).toBeVisible();
  await expect(page.getByRole("button", { name: /add to cart/i }).first()).toBeVisible();
  await page.getByRole("button", { name: "Add to cart", exact: true }).first().click();
  await expect(page.getByRole("button", { name: "Added to cart", exact: true }).first()).toBeVisible();
  await expect(page.locator("aside nav").getByRole("link", { name: /^Cart\b/ })).toBeVisible();
  await page.goto("/analysis");
  await expect(page.getByRole("heading", { name: "Access denied", exact: true })).toBeVisible();
  const token = await page.evaluate(() => localStorage.getItem("ecommerce_access_token"));
  const response = await page.request.get("/api/manager/analysis", { headers: { Authorization: `Bearer ${token}` } });
  expect(response.status()).toBe(403);
});
