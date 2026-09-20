"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { useRecede, useReveal } from "@/hooks/useReveal";

/**
 * Page chrome and section awareness.
 *
 * Two small pieces of shared state that the shell needs but the pages own:
 *
 *  - the current page's title, so a slim contextual bar can take over once the
 *    masthead has scrolled away;
 *  - the sections on the current page and which one the reader is in, so the
 *    sidebar can show where they are without the page having to know the
 *    sidebar exists.
 *
 * Both degrade to nothing. A page that registers no sections gets no
 * sub-navigation, and a page with no `PageHeader` gets no contextual bar.
 */

interface Chrome {
  title: string;
  /** One short line of status. Plain text, so it cannot churn identity. */
  meta?: string;
}

interface SectionEntry {
  id: string;
  label: string;
}

interface ChromeValue {
  chrome: Chrome | null;
  compact: boolean;
  sections: SectionEntry[];
  active: string | null;
  setChrome: (chrome: Chrome | null) => void;
  setCompact: (value: boolean) => void;
  register: (entry: SectionEntry) => () => void;
  report: (id: string, visible: boolean) => void;
}

const noop = () => {};

const PageChromeContext = createContext<ChromeValue>({
  chrome: null,
  compact: false,
  sections: [],
  active: null,
  setChrome: noop,
  setCompact: noop,
  register: () => noop,
  report: noop,
});

export function PageChromeProvider({ children }: { children: ReactNode }) {
  const [chrome, setChromeState] = useState<Chrome | null>(null);
  const [compact, setCompact] = useState(false);
  const [sections, setSections] = useState<SectionEntry[]>([]);
  const [active, setActive] = useState<string | null>(null);

  // Mirrors of the state that the observer callbacks can read synchronously
  // without being re-created on every change.
  const sectionsRef = useRef<SectionEntry[]>([]);
  const visibleRef = useRef<Set<string>>(new Set());

  const recompute = useCallback(() => {
    const first = sectionsRef.current.find((entry) => visibleRef.current.has(entry.id));
    setActive((current) => {
      if (first) return first.id;
      // At the very top or very bottom of a page nothing sits in the reading
      // band. Holding the last section is better than blinking the indicator
      // out — the reader has not left it, they have run out of page.
      const stillExists = sectionsRef.current.some((entry) => entry.id === current);
      return stillExists ? current : (sectionsRef.current[0]?.id ?? null);
    });
  }, []);

  const register = useCallback(
    (entry: SectionEntry) => {
      // Children mount in document order, so appending keeps the list in the
      // order the reader will scroll through.
      sectionsRef.current = [...sectionsRef.current, entry];
      setSections(sectionsRef.current);
      return () => {
        sectionsRef.current = sectionsRef.current.filter((item) => item.id !== entry.id);
        visibleRef.current.delete(entry.id);
        setSections(sectionsRef.current);
        recompute();
      };
    },
    [recompute],
  );

  const report = useCallback(
    (id: string, visible: boolean) => {
      if (visible) visibleRef.current.add(id);
      else visibleRef.current.delete(id);
      recompute();
    },
    [recompute],
  );

  const setChrome = useCallback((next: Chrome | null) => {
    setChromeState((current) => {
      if (next === null) return null;
      if (current && current.title === next.title && current.meta === next.meta) {
        return current;
      }
      return next;
    });
  }, []);

  const value = useMemo(
    () => ({
      chrome,
      compact,
      sections,
      active,
      setChrome,
      setCompact,
      register,
      report,
    }),
    [chrome, compact, sections, active, setChrome, register, report],
  );

  return (
    <PageChromeContext.Provider value={value}>{children}</PageChromeContext.Provider>
  );
}

export function usePageChrome(): ChromeValue {
  return useContext(PageChromeContext);
}

/**
 * Publishes the page title to the contextual bar for as long as it is mounted.
 */
export function usePublishChrome(title: string, meta?: string) {
  const { setChrome } = usePageChrome();

  useEffect(() => {
    setChrome({ title, meta });
    return () => setChrome(null);
  }, [title, meta, setChrome]);
}

/**
 * A major page section: scroll entrance plus a place in the sidebar.
 *
 * Registering and observing are separate concerns from revealing, but they
 * share one element, so they share one component rather than three nested
 * wrappers around every section on every page.
 */
export function Section({
  id,
  label,
  children,
  className = "",
  recede = false,
}: {
  id: string;
  label: string;
  children: ReactNode;
  className?: string;
  /** Let the section dim once the reader has scrolled up past it. */
  recede?: boolean;
}) {
  const { register, report } = usePageChrome();
  const { ref, shown } = useReveal<HTMLElement>();
  const fade = useRecede<HTMLElement>();
  const node = useRef<HTMLElement | null>(null);

  useEffect(() => register({ id, label }), [id, label, register]);

  useEffect(() => {
    const element = node.current;
    if (!element || typeof IntersectionObserver === "undefined") return;

    // The reading area is the band between 12% and 32% down the viewport: the
    // section a reader has settled on, not merely one that is on screen.
    //
    // The observer only triggers the measurement. Trusting its own
    // `isIntersecting` flag means a missed initial callback — which happens
    // when the renderer is throttled — leaves the section wrongly marked for
    // as long as it never crosses the boundary again.
    const measure = () => {
      const rect = element.getBoundingClientRect();
      const top = innerHeight * 0.12;
      const bottom = innerHeight * 0.32;
      report(id, rect.top < bottom && rect.bottom > top);
    };

    measure();
    const observer = new IntersectionObserver(measure, {
      threshold: 0,
      rootMargin: "-12% 0px -68% 0px",
    });
    observer.observe(element);

    window.addEventListener("resize", measure, { passive: true });
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
      report(id, false);
    };
  }, [id, report]);

  return (
    <section
      id={id}
      ref={(element: HTMLElement | null) => {
        node.current = element;
        ref.current = element;
        if (recede) fade.ref.current = element;
      }}
      className={`reveal scroll-mt-28 ${className}`}
      data-shown={shown}
      data-receded={recede ? fade.receded : undefined}
      aria-label={label}
    >
      {children}
    </section>
  );
}
