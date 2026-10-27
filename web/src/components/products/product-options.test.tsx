import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ProductOptions } from "./product-options";

describe("demo catalogue options", () => {
  it("lists the red option with its demo provenance and does not imply variant stock", () => {
    render(<ProductOptions specs={{ demo_options: {
      is_synthetic: true, source: "Classroom demo", attributes: { colours: ["Red", "Black"], sizes: ["S", "M"] },
    } }} />);
    expect(screen.getByText("Red, Black")).toBeVisible();
    expect(screen.getByText(/not verified manufacturer offerings/)).toBeVisible();
    expect(screen.getByText(/Availability of a specific colour or size is not recorded/)).toBeVisible();
    expect(screen.getByText(/not every combination is confirmed/)).toBeVisible();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByText("In stock", { exact: true })).not.toBeInTheDocument();
  });
  it.each([undefined, {}, { demo_options: { attributes: { colours: ["Red"] } } }, { demo_options: "bad data" }])(
    "does not present absent or malformed demo data as catalogue options",
    (specs) => {
      const { container } = render(<ProductOptions specs={specs} />);
      expect(container).toBeEmptyDOMElement();
    },
  );
});
