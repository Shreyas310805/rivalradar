"use client";

import { Menu, Moon, Sun, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { reducedMotion } from "@/lib/motion";

import { Wordmark } from "./Logo";
import { PageChromeProvider, usePageChrome } from "./PageChrome";
import { SlideOver } from "./SlideOver";

/**
 * Application shell.
 *
 * A text-only sidebar. No icons: six destinations set in the UI face read
 * faster than six glyphs, and dropping them removes the strongest "generic
 * dashboard" signal in the interface.
 *
 * The selection is a single 2px rail that slides between destinations rather
 * than a highlight that blinks out in one place and in at another — one
 * object moving, which is what makes navigation feel continuous.
 */

const NAV = [
  { href: "/", label: "Dashboard" },
  { href: "/competitors", label: "Competitors" },
  { href: "/changes", label: "Changes" },
  { href: "/analytics", label: "Analytics" },
  { href: "/digest", label: "Digest" },
  { href: "/evaluation", label: "Evaluation" },
] as const;

function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}

export function Shell({ children }: { children: ReactNode }) {
  return (
    <PageChromeProvider>
      <ShellFrame>{children}</ShellFrame>
    </PageChromeProvider>
  );
}

function ShellFrame({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [drawerOpen, setDrawerOpen] = useState(false);

  useEffect(() => setDrawerOpen(false), [pathname]);

  return (
    <div className="min-h-screen lg:flex">
      <aside className="sticky top-0 hidden h-screen w-[212px] shrink-0 flex-col border-r border-[var(--line)] bg-[var(--shell)] lg:flex">
        <SidebarContent pathname={pathname} />
      </aside>

      <SlideOver
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        label="Navigation"
        side="left"
        className="w-[248px] bg-[var(--shell)] lg:hidden"
      >
        <SidebarContent pathname={pathname} onClose={() => setDrawerOpen(false)} />
      </SlideOver>

      <div className="flex min-w-0 flex-1 flex-col">
        <MobileBar onOpen={() => setDrawerOpen(true)} />
        <CompactHeader />
        <main className="min-w-0 flex-1">
          <div className="mx-auto w-full max-w-[1140px] px-6 py-10 sm:px-10 sm:py-14">
            {children}
          </div>
        </main>
      </div>
    </div>
  );
}

/* =========================================================================
   Sidebar
   ========================================================================= */

function SidebarContent({
  pathname,
  onClose,
}: {
  pathname: string;
  onClose?: () => void;
}) {
  const { sections, active } = usePageChrome();
  const navRef = useRef<HTMLElement>(null);
  const [rail, setRail] = useState<{ y: number; height: number } | null>(null);

  // The rail follows whichever item is currently the destination — the active
  // section when the page has them, otherwise the active page.
  const measure = useCallback(() => {
    const nav = navRef.current;
    const target = nav?.querySelector<HTMLElement>('[data-rail="true"]');
    if (!nav || !target) {
      setRail(null);
      return;
    }
    const height = 15;
    setRail({
      y: target.offsetTop + (target.offsetHeight - height) / 2,
      height,
    });
  }, []);

  useLayoutEffect(measure, [measure, pathname, active, sections.length]);

  useEffect(() => {
    if (typeof ResizeObserver === "undefined" || !navRef.current) return;
    const observer = new ResizeObserver(measure);
    observer.observe(navRef.current);
    return () => observer.disconnect();
  }, [measure]);

  const showSections = sections.length > 1;

  return (
    <>
      <div className="flex h-[60px] shrink-0 items-center justify-between border-b border-[var(--line)] px-5">
        <Link href="/" className="rounded-[2px]">
          <Wordmark />
        </Link>
        {onClose && (
          <button
            onClick={onClose}
            aria-label="Close navigation"
            className="rounded-[var(--radius-xs)] p-1 text-[var(--ink-faint)] transition-colors duration-[var(--dur-fast)] hover:bg-[var(--raised)] hover:text-[var(--ink)]"
          >
            <X size={15} strokeWidth={1.75} />
          </button>
        )}
      </div>

      <nav
        ref={navRef}
        className="relative flex-1 overflow-y-auto py-5"
        aria-label="Main"
      >
        {/* One rail for the whole sidebar. It translates between destinations
            rather than fading out here and in there. */}
        <span
          aria-hidden
          className="absolute left-0 w-[2px] bg-[var(--accent)] transition-[transform,opacity] duration-[var(--dur)] [transition-timing-function:var(--ease)]"
          style={{
            height: rail?.height ?? 15,
            transform: `translateY(${rail?.y ?? 0}px)`,
            opacity: rail ? 1 : 0,
          }}
        />

        {NAV.map((item) => {
          const current = isActive(pathname, item.href);
          return (
            <div key={item.href}>
              <Link
                href={item.href}
                aria-current={current ? "page" : undefined}
                data-rail={current && !(showSections && active) ? "true" : undefined}
                className={`block py-[7px] pl-5 pr-4 text-[13px] transition-colors duration-[var(--dur-fast)] ${
                  current
                    ? "font-medium text-[var(--ink)]"
                    : "text-[var(--ink-soft)] hover:text-[var(--ink)]"
                }`}
              >
                {item.label}
              </Link>

              {current && showSections && (
                <SectionLinks sections={sections} active={active} />
              )}
            </div>
          );
        })}
      </nav>

      <div className="flex shrink-0 items-center justify-between border-t border-[var(--line)] py-4 pr-3">
        <Link
          href="/settings"
          aria-current={isActive(pathname, "/settings") ? "page" : undefined}
          className={`block py-[7px] pl-5 pr-4 text-[13px] transition-colors duration-[var(--dur-fast)] ${
            isActive(pathname, "/settings")
              ? "font-medium text-[var(--ink)]"
              : "text-[var(--ink-soft)] hover:text-[var(--ink)]"
          }`}
        >
          Settings
        </Link>
        <ThemeToggle />
      </div>
    </>
  );
}

/**
 * In-page sections for the current route.
 *
 * Only rendered when the page registered more than one, so every other route
 * is unaffected. Set faint and indented; it is orientation, not navigation
 * of equal weight.
 */
function SectionLinks({
  sections,
  active,
}: {
  sections: { id: string; label: string }[];
  active: string | null;
}) {
  return (
    <div className="animate-rise pb-1">
      {sections.map((section) => {
        const current = section.id === active;
        return (
          <a
            key={section.id}
            href={`#${section.id}`}
            data-rail={current ? "true" : undefined}
            onClick={(event) => {
              event.preventDefault();
              document.getElementById(section.id)?.scrollIntoView({
                behavior: reducedMotion() ? "auto" : "smooth",
                block: "start",
              });
            }}
            className={`block py-[5px] pl-9 pr-4 text-[12.5px] transition-colors duration-[var(--dur-fast)] ${
              current
                ? "text-[var(--ink)]"
                : "text-[var(--ink-faint)] hover:text-[var(--ink-soft)]"
            }`}
          >
            {section.label}
          </a>
        );
      })}
    </div>
  );
}

/* =========================================================================
   Chrome
   ========================================================================= */

function MobileBar({ onOpen }: { onOpen: () => void }) {
  return (
    <div className="sticky top-0 z-30 flex h-[52px] shrink-0 items-center justify-between border-b border-[var(--line)] bg-[var(--canvas)]/92 px-4 backdrop-blur-sm lg:hidden">
      <button
        onClick={onOpen}
        aria-label="Open navigation"
        className="rounded-[var(--radius-xs)] p-1.5 text-[var(--ink-soft)] transition-colors duration-[var(--dur-fast)] hover:bg-[var(--raised)] hover:text-[var(--ink)]"
      >
        <Menu size={17} strokeWidth={1.75} />
      </button>
      <Wordmark />
      <div className="w-8" aria-hidden />
    </div>
  );
}

/**
 * Contextual header.
 *
 * Takes over once the masthead has scrolled away, so the reader always knows
 * which page they are on without a permanent bar eating the top of every
 * screen. Fixed rather than sticky: it must not occupy layout, or appearing
 * would shift the content it sits above.
 */
function CompactHeader() {
  const { chrome, compact } = usePageChrome();
  const visible = compact && chrome !== null;

  return (
    <div
      aria-hidden={!visible}
      className={`fixed inset-x-0 top-[52px] z-20 border-b border-[var(--line)] bg-[var(--canvas)]/92 backdrop-blur-sm transition-[opacity,transform] duration-[var(--dur)] [transition-timing-function:var(--ease)] lg:left-[212px] lg:top-0 ${
        visible
          ? "pointer-events-auto translate-y-0 opacity-100"
          : "pointer-events-none -translate-y-2 opacity-0"
      }`}
    >
      <div className="mx-auto flex h-[44px] w-full max-w-[1140px] items-center justify-between gap-6 px-6 sm:px-10">
        <p className="truncate text-[13px] font-medium">{chrome?.title}</p>
        {chrome?.meta && (
          <p className="hidden shrink-0 text-[12px] text-[var(--ink-faint)] sm:block">
            {chrome.meta}
          </p>
        )}
      </div>
    </div>
  );
}

/**
 * Theme toggle.
 *
 * Adds a transition class to <html> for the length of the switch, so surfaces
 * and text cross-fade rather than snapping, then removes it — leaving the
 * blunt `*` transition rule out of the way for the rest of the session.
 */
function ThemeToggle() {
  const [theme, setTheme] = useState<"light" | "dark">("light");

  useEffect(() => {
    const current = document.documentElement.getAttribute("data-theme");
    setTheme(current === "dark" ? "dark" : "light");
  }, []);

  const toggle = useCallback(() => {
    const next = theme === "dark" ? "light" : "dark";
    const root = document.documentElement;

    if (!reducedMotion()) {
      root.classList.add("theme-transition");
      window.setTimeout(() => root.classList.remove("theme-transition"), 260);
    }

    setTheme(next);
    root.setAttribute("data-theme", next);
    try {
      window.localStorage.setItem("rivalradar-theme", next);
    } catch {
      // Private browsing or blocked storage — the toggle still works for this
      // session, it just will not be remembered.
    }
  }, [theme]);

  return (
    <button
      onClick={toggle}
      className="rounded-[var(--radius-xs)] p-1.5 text-[var(--ink-faint)] transition-colors duration-[var(--dur-fast)] hover:bg-[var(--raised)] hover:text-[var(--ink)] active:scale-[0.94]"
      aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
      title={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
    >
      {theme === "dark" ? (
        <Sun size={14.5} strokeWidth={1.75} />
      ) : (
        <Moon size={14.5} strokeWidth={1.75} />
      )}
    </button>
  );
}
