import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RichMessage } from "./rich-message";

const report = "/analysis?run_id=c9101694-d6b7-499e-9fab-43cafec24afc";

describe("saved analysis links", () => {
  it.each([true, false])("keeps report links inside the app (streaming=%s)", (streaming) => {
    render(<RichMessage streaming={streaming} content={`[Saved report](https://yourdomain.com${report})`} />);
    expect(screen.getByRole("link", { name: "Saved report" })).toHaveAttribute("href", report);
  });

  it.each([
    report,
    "https://example.com/docs",
    "https://example.com/analysis?run_id=invalid",
    "/products?id=example",
  ])("preserves other links and canonical relative URLs: %s", (href) => {
    render(<RichMessage content={`[Details](${href})`} />);
    expect(screen.getByRole("link", { name: "Details" })).toHaveAttribute("href", href);
  });

  it("still removes unsafe protocols", () => {
    const { container } = render(<RichMessage content="[Unsafe](javascript:alert%281%29)" />);
    expect(container.querySelector("a")).not.toHaveAttribute("href", expect.stringContaining("javascript:"));
  });
});
