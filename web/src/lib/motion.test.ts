import { afterEach, describe, expect, it, vi } from "vitest";
import {
  instant,
  pageEnter,
  prefersReducedMotion,
  withMotionPreference,
} from "./motion";

describe("motion", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("exposes hidden/visible states on the page-enter variant", () => {
    expect(pageEnter.hidden).toBeDefined();
    expect(pageEnter.visible).toBeDefined();
  });

  it("returns instant variants when the user prefers reduced motion", () => {
    expect(withMotionPreference(pageEnter, true)).toBe(instant);
    expect(withMotionPreference(pageEnter, false)).toBe(pageEnter);
  });

  it("prefersReducedMotion is false when matchMedia is unavailable", () => {
    vi.stubGlobal("window", {});
    expect(prefersReducedMotion()).toBe(false);
  });

  it("prefersReducedMotion reflects the media query match", () => {
    vi.stubGlobal("window", {
      matchMedia: (query: string) => ({
        matches: query.includes("reduce"),
      }),
    });
    expect(prefersReducedMotion()).toBe(true);
  });
});
