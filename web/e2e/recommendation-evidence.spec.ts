import { test, expect } from "@playwright/test";

// Real frontend + Python API + seeded Postgres. No LLM call or API mock.
// Run the base seed on a NEW demo database, then seed_recommendation_content.py.
test.describe("recommendation evidence", () => {
  test.skip(process.env.BACKEND_STACK === "dotnet", "This feature currently targets the Python stack.");

  for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
    test(`shows labelled evidence without generating AI output at ${viewport.width}px`, async ({ page, request }) => {
      await page.setViewportSize(viewport);
      const response = await request.get("/api/products?search=Sony");
      expect(response.ok()).toBe(true);
      const { products } = await response.json();
      const product = products.find((item: { name: string }) => item.name === "Sony WH-1000XM5");
      expect(product).toBeDefined();

      const paidRequests: string[] = [];
      page.on("request", (req) => {
        if (req.url().includes("/recommendation-reasons")) paidRequests.push(req.url());
      });
      await page.goto(`/shop/products/${product.id}`);
      const panel = page.getByRole("region", { name: "Recommendation reasons" });
      await expect(panel.getByRole("heading", { name: "Why this product?" })).toBeVisible();
      await panel.getByRole("button", { name: "View source evidence" }).click();
      await expect(panel.getByText("Includes AI-authored demo material.", { exact: false })).toBeVisible();
      await expect(panel.getByText("Synthetic demo review", { exact: false }).first()).toBeVisible();
      await expect(panel.getByText("Review evidence:", { exact: false })).toBeVisible();
      await expect(panel.getByRole("alert")).toHaveCount(0);
      expect(paidRequests).toHaveLength(0);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      await panel.screenshot({
        path: `../.claude/recommendation-checks/evidence-${viewport.width}.png`,
        style: "header { visibility: hidden; }",
      });
    });
  }
});
