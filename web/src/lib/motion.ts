/**
 * Shared framer-motion variants for the app shell and pages.
 *
 * Keep transitions short and physical — this is a productivity/shopping
 * surface, not a marketing splash. All durations are in seconds.
 *
 * Respect reduced-motion: components should read {@link prefersReducedMotion}
 * (or framer-motion's `useReducedMotion`) and pass {@link instant} variants /
 * `transition={{ duration: 0 }}` when the user opts out.
 */
import type { Transition, Variants } from "framer-motion";

/** Standard easing curve (ease-out-ish) used across the shell. */
export const EASE_OUT: Transition["ease"] = [0.16, 1, 0.3, 1];

export const DURATION = {
  fast: 0.15,
  base: 0.22,
  slow: 0.35,
} as const;

/** Page / route content enter. */
export const pageEnter: Variants = {
  hidden: { opacity: 0, y: 8 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: DURATION.base, ease: EASE_OUT },
  },
};

/** Container that staggers its children (use with {@link listItem}). */
export const listStagger: Variants = {
  hidden: {},
  visible: {
    transition: { staggerChildren: 0.05, delayChildren: 0.02 },
  },
};

/** Item inside a {@link listStagger} container. */
export const listItem: Variants = {
  hidden: { opacity: 0, y: 6 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { duration: DURATION.fast, ease: EASE_OUT },
  },
};

/** Subtle lift on hover for cards. */
export const cardHover = {
  rest: { y: 0 },
  hover: { y: -2, transition: { duration: DURATION.fast, ease: EASE_OUT } },
} satisfies Variants;

/** Gentle pulse for streaming / in-progress indicators. */
export const streamPulse: Variants = {
  animate: {
    opacity: [0.4, 1, 0.4],
    transition: { duration: 1.2, repeat: Infinity, ease: "easeInOut" },
  },
};

/** Zero-motion variant set, returned when the user prefers reduced motion. */
export const instant: Variants = {
  hidden: { opacity: 0 },
  visible: { opacity: 1, transition: { duration: 0 } },
};

/**
 * SSR-safe reduced-motion check. Returns `false` on the server (no matchMedia)
 * so first paint matches; pair with framer-motion's `useReducedMotion` in
 * client components for the reactive case.
 */
export function prefersReducedMotion(): boolean {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return false;
  }
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/**
 * Pick the appropriate variants for the user's motion preference.
 * @param variants the animated variant set
 * @param reduced whether the user prefers reduced motion
 */
export function withMotionPreference(
  variants: Variants,
  reduced: boolean,
): Variants {
  return reduced ? instant : variants;
}
