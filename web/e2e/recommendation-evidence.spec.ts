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
      const browserErrors: string[] = [];
      page.on("pageerror", (error) => browserErrors.push(error.message));
      page.on("console", (message) => {
        if (message.type() === "error" && message.text().includes("Base UI:")) {
          browserErrors.push(message.text());
        }
      });
      page.on("request", (req) => {
        if (req.url().includes("/recommendation-reasons")) paidRequests.push(req.url());
      });
      await page.goto(`/shop/products/${product.id}`);
      const panel = page.getByRole("region", { name: "Product suitability assessment" });
      await expect(panel.getByRole("heading", { name: "Is this product right for me?" })).toBeVisible();
      await panel.getByRole("button", { name: "View product info & reviews" }).click();
      await expect(panel.getByText("Includes AI-authored demo material.", { exact: false })).toBeVisible();
      await expect(panel.getByText("Synthetic demo review", { exact: false }).first()).toBeVisible();
      await expect(panel.getByText("Review evidence:", { exact: false })).toBeVisible();
      await expect(panel.getByRole("alert")).toHaveCount(0);
      await expect(page.getByRole("link", { name: "Products", exact: true })).toHaveAttribute("href", "/shop/products");
      await expect(page.getByRole("link", { name: "Sign in", exact: true })).toHaveAttribute("href", "/login");
      await expect(page.getByRole("link", { name: "Ask the assistant", exact: true })).toHaveAttribute("href", /^\/shop\/assistant\?prompt=/);
      await expect(page.getByRole("button", { name: "Sign in to buy", exact: true })).toHaveJSProperty("tagName", "BUTTON");
      expect(browserErrors).toEqual([]);
      expect(paidRequests).toHaveLength(0);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      await panel.screenshot({
        path: `../.claude/recommendation-checks/evidence-${viewport.width}.png`,
        style: "header { visibility: hidden; }",
      });
    });
  }
});
