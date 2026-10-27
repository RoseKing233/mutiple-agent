import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AnalysisFilters } from "./filters";

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }), usePathname: () => "/analysis" }));

describe("analysis date filters", () => {
  it("submits edited dates instead of initial values", () => {
    render(<AnalysisFilters query="start_date=2026-01-01&end_date=2026-01-28" catalog={null} />);
    fireEvent.change(screen.getByLabelText("Start date"), { target: { value: "2026-01-05" } });
    fireEvent.submit(screen.getByRole("form", { name: "Analysis filters" }));
    expect(replace).toHaveBeenCalledWith("/analysis?start_date=2026-01-05&end_date=2026-01-28");
  });
  it("explains invalid ranges before navigation", () => {
    replace.mockClear();
    render(<AnalysisFilters query="start_date=2026-01-01&end_date=2026-01-28" catalog={null} />);
    fireEvent.change(screen.getByLabelText("Start date"), { target: { value: "2026-02-01" } });
    fireEvent.submit(screen.getByRole("form", { name: "Analysis filters" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Start date must not be after end date");
    expect(replace).not.toHaveBeenCalled();
  });
});
