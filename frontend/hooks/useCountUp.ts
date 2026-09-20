"use client";

import { useEffect, useRef, useState } from "react";

import { MOTION, reducedMotion } from "@/lib/motion";

/**
 * Metrics that have already counted up in this session.
 *
 * Module scope, so it survives client-side navigation but resets on a real
 * page load. A number should introduce itself once; scrolling back up to it,
 * or a background refetch landing, must not restart the animation — that is
 * what turns a figure into a slot machine.
 */
const counted = new Set<string>();

/**
 * Animates a number up to its target, at most once.
 *
 * Hand-rolled rather than pulling in an animation library: this is forty
 * lines against tens of kilobytes for one effect.
 *
 * `play` gates the start, so a metric below the fold begins counting when its
 * section arrives rather than while nobody is looking.
 */
export function useCountUp(
  target: number,
  {
    id,
    play = true,
    duration = MOTION.count,
  }: { id: string; play?: boolean; duration?: number },
): number {
  // Starts at the target, not zero: if the animation never runs — reduced
  // motion, an already-counted metric, a failed observer — the correct value
  // is what renders.
  const [value, setValue] = useState(target);
  const frame = useRef<number | null>(null);
  const done = useRef(false);

  useEffect(() => {
    if (!play || done.current || counted.has(id) || reducedMotion() || !Number.isFinite(target)) {
      setValue(target);
      return;
    }

    done.current = true;
    counted.add(id);

    const start = performance.now();
    const step = (now: number) => {
      // Clamped at both ends. requestAnimationFrame reports the start of the
      // frame, which can precede the timestamp captured when it was
      // scheduled — an unclamped negative progress inverts the easing and
      // the first frame renders "-0".
      const progress = Math.min(1, Math.max(0, (now - start) / duration));
      // easeOutQuart — fast settle, no overshoot.
      setValue(target * (1 - Math.pow(1 - progress, 4)));
      if (progress < 1) frame.current = requestAnimationFrame(step);
    };

    setValue(0);
    frame.current = requestAnimationFrame(step);

    return () => {
      if (frame.current !== null) cancelAnimationFrame(frame.current);
    };
  }, [play, id, target, duration]);

  return value;
}
