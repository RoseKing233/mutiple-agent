import { test, expect } from "@playwright/test";

// Browser regression for batched SSE events; never sends a paid model request.
test.use({ channel: "chrome" });

test("one tool step, specialist preview and final answer produce one assistant bubble", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("ecommerce_user", JSON.stringify({ email: "stream-test@example.test", name: "UI tester", role: "store_manager" }));
    localStorage.setItem("ecommerce_access_token", "ui-test-token");
  });
  let requests = 0;
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/chat/stream") {
      requests += 1;
      await route.fulfill({
        status: 200, contentType: "text/event-stream",
        body: [
          `event: step\ndata: ${JSON.stringify({ agent: "inventory-fulfillment", tool_name: "analyze_product_performance", tool_input: {}, tool_output: {}, status: "success", duration_ms: 29 })}`,
          "event: delta\ndata: Specialist preview text",
          "data: One final analysis answer.",
          'event: metadata\ndata: {"conversation_id":"stream-test","agents_involved":["inventory-fulfillment"]}',
          "data: [DONE]", "",
        ].join("\n\n"),
      });
      return;
    }
    await route.fulfill({ json: path === "/api/conversations" || path === "/api/orchestration/modes" ? [] : {} });
  });
  await page.goto("/chat");
  await page.getByRole("textbox").fill("Analyze Books");
  await page.getByRole("textbox").press("Enter");
  await expect(page.getByText("One final analysis answer.", { exact: true })).toHaveCount(1);
  await expect(page.getByText("Specialist preview text", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Copy", exact: true })).toHaveCount(1);
  expect(requests).toBe(1);
  expect(errors.filter((message) => message.includes("same key"))).toEqual([]);
});

test("live Markdown formatting matches the same reply after reloading history", async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem("ecommerce_user", JSON.stringify({ email: "stream-test@example.test", name: "UI tester", role: "store_manager" }));
    localStorage.setItem("ecommerce_access_token", "ui-test-token");
  });
  const content = "## Sales result\n\n- Units: **518**\n- Orders: **331**\n\nStock is known.\n";
  const conversation = { id: "format-test", title: "Format test", created_at: new Date().toISOString() };
  let sent = false;
  await page.route("**/api/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/chat/stream") {
      sent = true;
      const parts = ["## Sales result", "\n\n", "- Units: **518**\n", "- Orders: **331**\n\n", "Stock is known.\n"];
      const body = parts.map((part) => part.split("\n").map((line) => `data: ${line}\n`).join("") + "\n").join("");
      await route.fulfill({ contentType: "text/event-stream", body: body + 'event: metadata\ndata: {"conversation_id":"format-test","agents_involved":["inventory-fulfillment"]}\n\ndata: [DONE]\n\n' });
      return;
    }
    if (path === "/api/conversations/format-test") {
      await route.fulfill({ json: { ...conversation, messages: [{ id: "saved-answer", role: "assistant", content }] } });
      return;
    }
    await route.fulfill({ json: path === "/api/conversations" ? sent ? [conversation] : [] : path === "/api/orchestration/modes" ? [] : {} });
  });
  await page.goto("/chat");
  await page.getByRole("textbox").fill("Format test");
  await page.getByRole("textbox").press("Enter");
  await expect(page.getByRole("heading", { name: "Sales result", exact: true })).toBeVisible();
  const reply = page.locator(".prose").filter({ has: page.getByRole("heading", { name: "Sales result", exact: true }) });
  await expect(reply.locator("li")).toHaveCount(2);
  const before = await reply.innerHTML();
  await page.reload();
  await page.getByRole("button", { name: "Format test", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Sales result", exact: true })).toBeVisible();
  expect(await reply.innerHTML()).toBe(before);
});
