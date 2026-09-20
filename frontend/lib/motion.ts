/**
 * The motion system.
 *
 * Every duration and delay in the interface resolves to one of these values,
 * so timing is a property of the product rather than of whichever component
 * was written last. The CSS half of the system lives in globals.css as
 * `--dur-*` custom properties set from the same numbers.
 *
 * One easing curve throughout: a decelerating ease-out. Motion here reports
 * that something happened; it never performs.
 */

export const MOTION = {
  /** Hover, focus, colour — felt, not watched. */
  fast: 150,
  /** Standard state change: the nav rail, a filter, a toggle. */
  normal: 220,
  /** Larger repositioning. */
  slow: 400,
  /** Scroll-entrance of a section. */
  reveal: 500,
  /** Slide-over enter and exit. */
  overlay: 300,
  /** Metric count-up. */
  count: 650,
  /** Gap between staggered siblings. */
  stagger: 45,
  /**
   * Stagger is capped so a long list never leaves the last row waiting. Six
   * steps is ~270ms, which still reads as a cascade.
   */
  staggerCap: 6,
} as const;

export const EASE = "cubic-bezier(0.22, 1, 0.36, 1)";

/** Reads the OS setting. Safe to call during render on the client only. */
export function reducedMotion(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/** Delay for the nth item in a staggered group, in milliseconds. */
export function staggerDelay(index: number): number {
  return Math.min(Math.max(index, 0), MOTION.staggerCap) * MOTION.stagger;
}

/** Inline style carrying a stagger delay to the CSS transition. */
export function staggerStyle(index: number): React.CSSProperties {
  return { ["--reveal-delay" as string]: `${staggerDelay(index)}ms` };
}
