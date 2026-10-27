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
  const chineseText = [result.needs_assessment.text, ...["product_summary", "review_summary", "reasons", "cautions"].flatMap((section) => result[section].map((point: { text: string }) => point.text))].join("\n");
  expect(chineseText).not.toMatch(/demo|synthetic|classroom|fictional|test data|演示|模拟|测试数据/i);
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
test("live black bottle request confirms the listed colour in normal shop wording", async ({ page, request }) => {
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
  expect(evidence.product.specs.demo_options.attributes.colours).toContain("Black");
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(`/shop/products/${product.id}`);
  const panel = page.getByRole("region", { name: "Product suitability assessment" });
  await panel.getByLabel("Your needs and intended use").fill("I want a Black one");
  await panel.getByLabel("Maximum budget (USD, optional)").fill("60");
  await panel.getByLabel("Response language").selectOption("en");
  const generated = page.waitForResponse((r) => r.url().includes("/recommendation-reasons"), { timeout: 60000 });
  await panel.getByRole("button", { name: "Assess this product for me" }).click();
  const generatedResponse = await generated;
  expect(generatedResponse.status()).toBe(200);
  const result = await generatedResponse.json();
  expect(result.budget_fit).toBe(true);
  // A simple listed-colour preference does not ask for fulfilment guarantees.
  expect(result.needs_assessment.status).toBe("meets_needs");
  expect(result.needs_assessment.text.split(/[.!?]/)[0]).toMatch(/black/i);
  expect(result.needs_assessment.text).toMatch(/^Yes[, ]/i);
  const generatedText = [result.needs_assessment.text, ...["product_summary", "review_summary", "reasons", "cautions"].flatMap((section) => result[section].map((point: { text: string }) => point.text))].join("\n");
  expect(generatedText).not.toMatch(/demo|synthetic|classroom|fictional|test data|演示|模拟|测试数据/i);
  expect(result.needs_assessment.source_ids).toContain(`demo-options:${product.id}`);
  const known = new Set(result.sources.map((source: { id: string }) => source.id));
  expect(result.needs_assessment.source_ids.length).toBeGreaterThan(0);
  for (const id of result.needs_assessment.source_ids) expect(known.has(id)).toBe(true);
  const answer = panel.getByRole("region", { name: "Answer to your request" });
  await expect(answer).toContainText(result.needs_assessment.text);
  await expect(page.getByRole("region", { name: "Product options" })).toContainText("Red, Black, White, Blue");
  const answerBox = await answer.boundingBox();
  const summaryBox = await panel.getByRole("heading", { name: "Product and document summary" }).boundingBox();
  expect(answerBox!.y + answerBox!.height).toBeLessThan(summaryBox!.y);
  await expect(panel.getByRole("alert")).toHaveCount(0);
  await mkdir("../.claude/recommendation-checks", { recursive: true });
  await writeFile("../.claude/recommendation-checks/live-black-bottle-shop-wording.json", JSON.stringify(result, null, 2));
  console.log("Direct answer:", result.needs_assessment, "Usage:", result.usage);
  await panel.screenshot({ path: "../.claude/recommendation-checks/black-bottle-shop-wording.png", style: "header, nextjs-portal { visibility: hidden; }" });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(answer).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await answer.screenshot({ path: "../.claude/recommendation-checks/black-bottle-shop-wording-mobile.png", style: "nextjs-portal { visibility: hidden; }" });
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

test("live green bottle request answers an unlisted colour with valid citations", async ({ page, request }) => {
  test.skip(process.env.RUN_LIVE_RECOMMENDATION !== "true", "Set RUN_LIVE_RECOMMENDATION=true for one paid test.");
  test.skip(process.env.BACKEND_STACK === "dotnet", "Python implementation only.");
  test.setTimeout(90000);
  const response = await request.get("/api/products?search=Hydro%20Flask");
  expect(response.ok()).toBe(true);
  const { products } = await response.json();
  const product = products.find((item: { name: string }) => item.name === "Hydro Flask 32oz Wide Mouth");
  expect(product).toBeDefined();
  await page.goto(`/shop/products/${product.id}`);
  const panel = page.getByRole("region", { name: "Product suitability assessment" });
  await panel.getByLabel("Your needs and intended use").fill("I want a green one");
  await panel.getByLabel("Maximum budget (USD, optional)").fill("49");
  const generated = page.waitForResponse((r) => r.url().includes("/recommendation-reasons"), { timeout: 60000 });
  await panel.getByRole("button", { name: "Assess this product for me" }).click();
  const generatedResponse = await generated;
  expect(generatedResponse.status()).toBe(200);
  const result = await generatedResponse.json();
  expect(result.budget_fit).toBe(true);
  expect(result.needs_assessment.status).toBe("cannot_confirm");
  expect(result.needs_assessment.text).toMatch(/green/i);
  expect(result.needs_assessment.text).toMatch(/not listed|no green|does not (?:list|include)|doesn't (?:list|include)/i);
  expect(result.needs_assessment.text).not.toMatch(/out of stock/i);
  expect(result.needs_assessment.source_ids).toContain(`demo-options:${product.id}`);
  const known = new Map<string, string>(result.sources.map((source: { id: string; kind: string }) => [source.id, source.kind]));
  const points = [result.needs_assessment, ...result.product_summary, ...result.review_summary, ...result.reasons, ...result.cautions];
  for (const point of points) {
    expect(point.source_ids.length).toBeGreaterThan(0);
    for (const id of point.source_ids) expect(known.has(id)).toBe(true);
  }
  for (const point of result.product_summary) {
    for (const id of point.source_ids) expect(["catalogue", "document"]).toContain(known.get(id));
  }
  for (const point of result.review_summary) {
    for (const id of point.source_ids) expect(known.get(id)).toBe("review");
  }
  const allText = points.map((point: { text: string }) => point.text).join("\n");
  expect(allText).not.toMatch(/in stock for (?:the )?listed colo[u]?rs|all colo[u]?rs are available/i);
  const answer = panel.getByRole("region", { name: "Answer to your request" });
  await expect(answer).toContainText(result.needs_assessment.text);
  await expect(panel.getByRole("alert")).toHaveCount(0);
  await answer.getByRole("link").first().click();
  await expect(panel.locator("details")).toHaveAttribute("open", "");
  await mkdir("../.claude/recommendation-checks", { recursive: true });
  await writeFile("../.claude/recommendation-checks/live-green-bottle.json", JSON.stringify(result, null, 2));
  await answer.screenshot({ path: "../.claude/recommendation-checks/green-bottle-answer.png", style: "header, nextjs-portal { visibility: hidden; }" });
  console.log("Green colour answer:", result.needs_assessment, "Usage:", result.usage);
});

const assessmentCases = [
  { name: "zero budget", product: "Hydro Flask 32oz Wide Mouth", preferences: "I want a black bottle, but I cannot spend any money.", budget: 0, language: "en", status: "does_not_meet", budgetFit: false, answer: /44\.95|budget|money|free|cost/i },
  { name: "exact price boundary", product: "Hydro Flask 32oz Wide Mouth", preferences: "I want a black bottle.", budget: 44.95, language: "en", status: "meets_needs", budgetFit: true, answer: /black/i },
  { name: "colour and size combination stock", product: "Uniqlo Ultra Light Down Jacket", preferences: "I need a red jacket in size M. Is this exact combination available to order today?", budget: 60, language: "en", status: "cannot_confirm", budgetFit: true, answer: /cannot|can't|no .*confirm|not .*confirm/i },
  { name: "missing book language", product: "Atomic Habits", preferences: "我想买中文版，请根据商品资料和评价告诉我是否适合，并说明不确定的信息。", budget: null, language: "zh", status: "cannot_confirm", budgetFit: null, answer: /中文/ },
  { name: "many requirements in Chinese", product: "Sony WH-1000XM5", preferences: ("我每天乘火车通勤，需要主动降噪、至少30小时续航、轻便、同时连接手机和电脑、麦克风适合嘈杂车站通话、雨天防水、佩戴眼镜也舒适、黑色款、可以折叠放包里、两年保修。请逐项说明有资料支持的条件、没有资料确认的条件以及不符合的条件，不能把我的愿望当成功能。请根据商品介绍、文档、正面与负面评价提供简明分析。不要只说预算合适。".repeat(9)).slice(0, 1500), budget: 300, language: "zh", status: "cannot_confirm", budgetFit: true, answer: /无法确认|未.*确认|没有.*资料|未.*提供|缺乏/ },
];

for (const scenario of assessmentCases) {
  test(`live assessment handles ${scenario.name}`, async ({ request }) => {
    test.skip(process.env.RUN_LIVE_RECOMMENDATION !== "true", "Explicit opt-in: spends real API credit.");
    test.skip(process.env.BACKEND_STACK === "dotnet", "Python implementation only.");
    test.setTimeout(90000);
    const productsResponse = await request.get(`/api/products?search=${encodeURIComponent(scenario.product)}`);
    expect(productsResponse.ok()).toBe(true);
    const { products } = await productsResponse.json();
    const product = products.find((item: { name: string }) => item.name === scenario.product);
    expect(product).toBeDefined();
    const response = await request.post(`/api/products/${product.id}/recommendation-reasons`, {
      data: { preferences: scenario.preferences, max_budget: scenario.budget, language: scenario.language },
      timeout: 60000,
    });
    expect(response.status()).toBe(200);
    const result = await response.json();
    expect(result.budget_fit).toBe(scenario.budgetFit);
    expect(result.needs_assessment.status).toBe(scenario.status);
    expect(result.needs_assessment.text).toMatch(scenario.answer);
    if (scenario.name === "colour and size combination stock") {
      expect(result.needs_assessment.text).not.toMatch(/red jacket in size m is listed/i);
      expect(result.needs_assessment.text).toMatch(/combination/i);
    }
    if (scenario.language === "zh") expect(result.needs_assessment.text).toMatch(/[\u4e00-\u9fff]/);
    const known = new Map<string, string>(result.sources.map((source: { id: string; kind: string }) => [source.id, source.kind]));
    const points = [result.needs_assessment, ...result.product_summary, ...result.review_summary, ...result.reasons, ...result.cautions];
    for (const point of points) {
      expect(point.text.trim().length).toBeGreaterThan(0);
      expect(point.source_ids.length).toBeGreaterThan(0);
      for (const id of point.source_ids) expect(known.has(id)).toBe(true);
    }
    for (const point of result.review_summary) {
      for (const id of point.source_ids) expect(known.get(id)).toBe("review");
    }
    for (const point of result.product_summary) {
      for (const id of point.source_ids) expect(["catalogue", "document"]).toContain(known.get(id));
    }
    await mkdir("../.claude/recommendation-checks", { recursive: true });
    await writeFile(`../.claude/recommendation-checks/live-${scenario.name.replaceAll(" ", "-")}.json`, JSON.stringify(result, null, 2));
    console.log(scenario.name, result.needs_assessment, result.usage);
  });
}
