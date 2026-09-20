"use client";

import { useEffect, useRef, useState } from "react";

import { reducedMotion } from "@/lib/motion";

/**
 * Scroll-position hooks.
 *
 * All three use IntersectionObserver rather than a scroll listener: the
 * browser does the intersection maths off the main thread, so a fast scroll
 * never queues layout reads behind it.
 *
 * Two of them treat the observer purely as a *trigger* and re-measure the
 * element themselves. That is deliberate. An observer delivers its initial
 * callback once, asynchronously; if the document is hidden or the renderer is
 * throttled when that callback is due, it can be missed — and because every
 * later callback fires only on a *change*, an element that was already past
 * the boundary would never report again. Measuring on mount and on every
 * trigger makes the state correct regardless of when the observer got to run.
 */

/**
 * Scroll-entrance state for a block.
 *
 * Reveals once and then stops observing. A section that re-enters the
 * viewport should already be there, not animate again — re-animating on every
 * pass is what makes a page feel like a slideshow.
 */
export function useReveal<T extends HTMLElement = HTMLDivElement>(options?: {
  /** Fraction of the element that must be visible. */
  threshold?: number;
  /** Shrinks the viewport so a block starts moving slightly before it lands. */
  rootMargin?: string;
}) {
  const ref = useRef<T>(null);
  const [shown, setShown] = useState(false);

  useEffect(() => {
    const node = ref.current;

    // No observer, or motion turned off: the content is simply present.
    //
    // A hidden document counts too. Browsers stop advancing animations and
    // heavily throttle timers and observer callbacks in a backgrounded tab,
    // so waiting would leave the page blank for as long as it stays hidden —
    // and there is no entrance for anyone to watch either way.
    if (
      !node ||
      typeof IntersectionObserver === "undefined" ||
      reducedMotion() ||
      document.visibilityState === "hidden"
    ) {
      setShown(true);
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setShown(true);
          observer.disconnect();
        }
      },
      {
        threshold: options?.threshold ?? 0.05,
        rootMargin: options?.rootMargin ?? "0px 0px -8% 0px",
      },
    );
    observer.observe(node);

    // Insurance. If the observer never fires — a detached subtree, a browser
    // quirk, a zero-height parent — the content must not stay invisible.
    const failsafe = window.setTimeout(() => {
      setShown(true);
      observer.disconnect();
    }, 1500);

    // If the tab is backgrounded before the observer gets to run, stop
    // waiting: show the content and let it be there when the reader returns.
    const onHide = () => {
      if (document.visibilityState === "hidden") {
        setShown(true);
        observer.disconnect();
      }
    };
    document.addEventListener("visibilitychange", onHide);

    return () => {
      window.clearTimeout(failsafe);
      document.removeEventListener("visibilitychange", onHide);
      observer.disconnect();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { ref, shown };
}

/**
 * True once a block has scrolled up out of the reading area.
 *
 * Lets a section that is no longer the subject recede slightly, so the one
 * the reader has arrived at is the emphasised thing. Keeps observing, because
 * the state has to survive scrolling back up.
 */
export function useRecede<T extends HTMLElement = HTMLDivElement>() {
  const ref = useRef<T>(null);
  const [receded, setReceded] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node || typeof IntersectionObserver === "undefined" || reducedMotion()) {
      return;
    }

    // Receded once the block has all but left the top of the screen. A fixed
    // offset rather than a fraction of the viewport: a percentage large
    // enough to be useful on a tall window marks a short section as receded
    // while it is still sitting at rest under the masthead.
    const measure = () => setReceded(node.getBoundingClientRect().bottom < 100);

    measure();
    const observer = new IntersectionObserver(measure, {
      threshold: 0,
      rootMargin: "-100px 0px 0px 0px",
    });
    observer.observe(node);

    window.addEventListener("resize", measure, { passive: true });
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, []);

  return { ref, receded };
}

/**
 * True once the page has scrolled past a marker.
 *
 * Attach the returned ref to a zero-height sentinel; the flag flips when that
 * sentinel leaves the top of the viewport. No scroll handler.
 */
export function useScrolledPast<T extends HTMLElement = HTMLDivElement>() {
  const ref = useRef<T>(null);
  const [past, setPast] = useState(false);

  useEffect(() => {
    const node = ref.current;
    if (!node || typeof IntersectionObserver === "undefined") return;

    const measure = () => setPast(node.getBoundingClientRect().bottom < 0);

    measure();
    const observer = new IntersectionObserver(measure, { threshold: 0 });
    observer.observe(node);

    window.addEventListener("resize", measure, { passive: true });
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, []);

  return { ref, past };
}
