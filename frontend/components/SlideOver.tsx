"use client";

import { useEffect, useState, type ReactNode } from "react";

import { MOTION } from "@/lib/motion";

import { Portal } from "./Portal";

/**
 * Slide-over panel.
 *
 * Enter and exit are the same transition run in both directions, so a panel
 * never simply disappears. That requires staying mounted for the length of
 * the exit, which is what `mounted` tracks; `entered` is the flag CSS reads.
 *
 * Portalled to <body>, because an ancestor with a transform — including one
 * mid-animation, like a revealing section — becomes the containing block for
 * `position: fixed` descendants and would unpin the panel from the viewport.
 */
export function SlideOver({
  open,
  onClose,
  label,
  side = "right",
  className = "",
  children,
}: {
  open: boolean;
  onClose: () => void;
  label: string;
  side?: "left" | "right";
  className?: string;
  children: ReactNode;
}) {
  const [mounted, setMounted] = useState(false);
  const [entered, setEntered] = useState(false);

  useEffect(() => {
    if (open) {
      setMounted(true);
      return;
    }
    setEntered(false);
    const timer = window.setTimeout(() => setMounted(false), MOTION.overlay);
    return () => window.clearTimeout(timer);
  }, [open]);

  // One frame after the closed state has been committed to the DOM, flip to
  // open so the browser has something to transition from.
  useEffect(() => {
    if (!mounted || !open) return;
    const frame = requestAnimationFrame(() => setEntered(true));
    return () => cancelAnimationFrame(frame);
  }, [mounted, open]);

  useEffect(() => {
    if (!mounted) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    // Stop the page behind the panel from scrolling.
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, [mounted, onClose]);

  if (!mounted) return null;

  return (
    <Portal>
      <div
        className="scrim fixed inset-0 z-40 bg-[var(--overlay)]"
        data-open={entered}
        onClick={onClose}
        aria-hidden
      />
      <aside
        className={`slide-panel fixed inset-y-0 z-50 flex flex-col bg-[var(--panel)] shadow-[var(--shadow-lg)] ${
          side === "left"
            ? "left-0 border-r border-[var(--line)]"
            : "right-0 border-l border-[var(--line)]"
        } ${className}`}
        data-open={entered}
        style={{ ["--slide-from" as string]: side === "left" ? "-24px" : "24px" }}
        role="dialog"
        aria-modal="true"
        aria-label={label}
      >
        {children}
      </aside>
    </Portal>
  );
}
