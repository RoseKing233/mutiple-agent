import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { SectionHeader } from "./section-header";

describe("SectionHeader", () => {
  it("renders the title as a heading", () => {
    render(<SectionHeader title="Active Test Plans" />);
    expect(
      screen.getByRole("heading", { name: "Active Test Plans" }),
    ).toBeInTheDocument();
  });

  it("renders eyebrow, description, and action", () => {
    render(
      <SectionHeader
        eyebrow="Your Workspace"
        title="Active Test Plans"
        description="Track coverage across plans."
        action={<button type="button">New Plan</button>}
      />,
    );
    expect(screen.getByText("Your Workspace")).toBeInTheDocument();
    expect(screen.getByText("Track coverage across plans.")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "New Plan" }),
    ).toBeInTheDocument();
  });
});
