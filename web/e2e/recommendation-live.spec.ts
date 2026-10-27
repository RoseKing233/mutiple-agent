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
  for (const id of result.needs_assessment.source_ids) expect(known.has(id)).toBe(true);
  expect(result.needs_assessment.status).toBe("does_not_meet");
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

// Run seed_catalogue_options.py --apply before testing the demo colour listing.
test("live red bottle request confirms the listed demo colour before summaries", async ({ page, request }) => {
  test.skip(process.env.RUN_LIVE_RECOMMENDATION !== "true", "Set RUN_LIVE_RECOMMENDATION=true for one paid test.");
  test.skip(process.env.BACKEND_STACK === "dotnet", "Python implementation only.");
  test.setTimeout(90000);
  const response = await request.get("/api/products?search=Hydro%20Flask");
  expect(response.ok()).toBe(true);
  const { products } = await response.json();
  const product = products.find((item: { name: string }) => item.name === "Hydro Flask 32oz Wide Mouth");
  expect(product).toBeDefined();
  const evidenceResponse = await request.get(`/api/products/${product.id}/recommendation-evidence`);
  expect(evidenceResponse.ok()).toBe(true);
  const evidence = await evidenceResponse.json();
  expect(evidence.product.specs.demo_options.attributes.colours).toContain("Red");
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`/shop/products/${product.id}`);
  const panel = page.getByRole("region", { name: "Product suitability assessment" });
  await panel.getByLabel("Your needs and intended use").fill("我想要一个红色的这个款式的杯子");
  await panel.getByLabel("Maximum budget (USD, optional)").fill("50");
  await panel.getByLabel("Response language").selectOption("en");
  const generated = page.waitForResponse((r) => r.url().includes("/recommendation-reasons"), { timeout: 60000 });
  await panel.getByRole("button", { name: "Assess this product for me" }).click();
  const generatedResponse = await generated;
  expect(generatedResponse.status()).toBe(200);
  const result = await generatedResponse.json();
  expect(result.budget_fit).toBe(true);
  // A colour listing is confirmed; the overall fit may still flag the lack of
  // colour-specific order fulfilment. Assert the actual answer and its provenance.
  expect(["meets_needs", "cannot_confirm"]).toContain(result.needs_assessment.status);
  expect(result.needs_assessment.text.split(/[.!?]/)[0]).toMatch(/red/i);
  expect(result.needs_assessment.text).toMatch(/^Yes[, ]/i);
  expect(result.needs_assessment.text).toMatch(/demo/i);
  expect(result.needs_assessment.source_ids).toContain(`demo-options:${product.id}`);
  const known = new Set(result.sources.map((source: { id: string }) => source.id));
  expect(result.needs_assessment.source_ids.length).toBeGreaterThan(0);
  for (const id of result.needs_assessment.source_ids) expect(known.has(id)).toBe(true);
  const answer = panel.getByRole("region", { name: "Answer to your request" });
  await expect(answer).toContainText(result.needs_assessment.text);
  await expect(page.getByRole("region", { name: "Demo catalogue options" })).toContainText("Red, Black, White, Blue");
  const answerBox = await answer.boundingBox();
  const summaryBox = await panel.getByRole("heading", { name: "Product and document summary" }).boundingBox();
  expect(answerBox!.y + answerBox!.height).toBeLessThan(summaryBox!.y);
  await expect(panel.getByRole("alert")).toHaveCount(0);
  await mkdir("../.claude/recommendation-checks", { recursive: true });
  await writeFile("../.claude/recommendation-checks/live-red-bottle-with-options.json", JSON.stringify(result, null, 2));
  console.log("Direct answer:", result.needs_assessment, "Usage:", result.usage);
  await panel.screenshot({ path: "../.claude/recommendation-checks/red-bottle-with-options.png", style: "header { visibility: hidden; }" });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(answer).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await answer.screenshot({ path: "../.claude/recommendation-checks/red-bottle-with-options-mobile.png" });
  await answer.getByRole("link").first().click();
  await expect(panel.locator("details")).toHaveAttribute("open", "");
});

test("live colour stock question does not invent a variant quantity", async ({ request }) => {
  test.skip(process.env.RUN_LIVE_RECOMMENDATION !== "true", "Set RUN_LIVE_RECOMMENDATION=true for one paid test.");
  test.skip(process.env.BACKEND_STACK === "dotnet", "Python implementation only.");
  test.setTimeout(90000);
  const response = await request.get("/api/products?search=Hydro%20Flask");
  const { products } = await response.json();
  const product = products.find((item: { name: string }) => item.name === "Hydro Flask 32oz Wide Mouth");
  expect(product).toBeDefined();
  const generated = await request.post(`/api/products/${product.id}/recommendation-reasons`, {
    data: { preferences: "How many RED bottles are in stock right now? Can you guarantee a red one is available to order?", max_budget: 50, language: "en" },
    timeout: 60000,
  });
  expect(generated.status()).toBe(200);
  const result = await generated.json();
  expect(result.needs_assessment.status).toBe("cannot_confirm");
  expect(result.needs_assessment.text).toMatch(/red/i);
  expect(result.needs_assessment.text).toMatch(/cannot|can't|not (?:recorded|tracked|confirm)|no .*stock/i);
  expect(result.needs_assessment.source_ids).toContain(`demo-options:${product.id}`);
  await mkdir("../.claude/recommendation-checks", { recursive: true });
  await writeFile("../.claude/recommendation-checks/live-colour-stock.json", JSON.stringify(result, null, 2));
  console.log("Colour stock answer:", result.needs_assessment, "Usage:", result.usage);
});
