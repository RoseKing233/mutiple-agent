import { test, expect } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";

// Explicit manual opt-in only. One generation request spends real API credit.
test("live Chinese recommendation respects a low budget and opens cited sources", async ({ page, request }) => {
  test.skip(process.env.RUN_LIVE_RECOMMENDATION !== "true", "Set RUN_LIVE_RECOMMENDATION=true for one paid test.");
  test.skip(process.env.BACKEND_STACK === "dotnet", "Python implementation only.");
  test.setTimeout(90000);
  const response = await request.get("/api/products?search=Sony");
  expect(response.ok()).toBe(true);
  const { products } = await response.json();
  const product = products.find((item: { name: string }) => item.name === "Sony WH-1000XM5");
  expect(product).toBeDefined();
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`/shop/products/${product.id}`);
  const panel = page.getByRole("region", { name: "Product suitability assessment" });
  await panel.getByLabel("Your needs and intended use").fill("我想买通勤用的降噪耳机，预算最多100美元，请说明这款是否适合和它的限制。");
  await panel.getByLabel("Maximum budget (USD, optional)").fill("100");
  await panel.getByLabel("Response language").selectOption("zh");
  const generated = page.waitForResponse((r) => r.url().includes("/recommendation-reasons"), { timeout: 60000 });
  await panel.getByRole("button", { name: "Assess this product for me" }).click();
  const generatedResponse = await generated;
  expect(generatedResponse.status()).toBe(200);
  const result = await generatedResponse.json();
  expect(result.budget_fit).toBe(false);
  expect(result.usage.input_tokens).toBeGreaterThan(0);
  const known = new Set(result.sources.map((source: { id: string }) => source.id));
  for (const section of ["product_summary", "review_summary", "reasons", "cautions"]) {
    for (const point of result[section]) {
      expect(point.source_ids.length).toBeGreaterThan(0);
      for (const id of point.source_ids) expect(known.has(id)).toBe(true);
    }
  }
  expect(result.reasons.some((point: { text: string }) => /[\u4e00-\u9fff]/.test(point.text))).toBe(true);
  await expect(panel.getByText("This product exceeds your stated budget.")).toBeVisible();
  await expect(panel.getByRole("alert")).toHaveCount(0);
  await mkdir("../.claude/recommendation-checks", { recursive: true });
  await writeFile("../.claude/recommendation-checks/live-low-budget.json", JSON.stringify(result, null, 2));
  console.log("Live recommendation usage:", result.usage);
  await panel.screenshot({ path: "../.claude/recommendation-checks/live-desktop.png", style: "header { visibility: hidden; }" });
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await panel.screenshot({ path: "../.claude/recommendation-checks/live-mobile.png", style: "header { visibility: hidden; }" });
  const sources = panel.locator("details");
  await expect(sources).not.toHaveAttribute("open", "");
  await panel.getByRole("link").first().click();
  await expect(sources).toHaveAttribute("open", "");
});
