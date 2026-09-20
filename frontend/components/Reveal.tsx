"use client";

import type { ReactNode } from "react";

import { useRecede, useReveal } from "@/hooks/useReveal";
import { staggerStyle } from "@/lib/motion";

/**
 * Scroll entrance.
 *
 * `Reveal` wraps a block; the block settles into place as it arrives. All the
 * animation is CSS on two theme-independent properties — opacity and
 * transform — so light and dark run exactly the same code, and the compositor
 * handles it without touching layout.
 *
 * `data-shown` is the only thing React toggles. Descendants can key off the
 * same attribute (see `.bar-fill` in globals.css), which is how the signal
 * bars and meters draw themselves when their section arrives rather than on
 * mount.
 */
export function Reveal({
  children,
  index,
  recede = false,
  className = "",
  as: Tag = "div",
  id,
}: {
  children: ReactNode;
  /** Position in a staggered group. */
  index?: number;
  /** Let the block dim once it has scrolled up out of the reading area. */
  recede?: boolean;
  className?: string;
  as?: "div" | "section" | "aside" | "header";
  id?: string;
}) {
  const reveal = useReveal<HTMLDivElement>();
  const fade = useRecede<HTMLDivElement>();

  return (
    <Tag
      ref={(node: HTMLDivElement | null) => {
        reveal.ref.current = node;
        if (recede) fade.ref.current = node;
      }}
      id={id}
      className={`reveal ${className}`}
      data-shown={reveal.shown}
      data-receded={recede ? fade.receded : undefined}
      style={index === undefined ? undefined : staggerStyle(index)}
    >
      {children}
    </Tag>
  );
}

/**
 * Publishes `data-shown` without animating the wrapper itself.
 *
 * For blocks whose children do the animating — meters and bars keying off
 * `.bar-fill`, or staged children — where a second fade on the container
 * would just be motion on top of motion. Used inside the drawer, where the
 * panel is already sliding in.
 */
export function Draw({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  const { ref, shown } = useReveal<HTMLDivElement>({ threshold: 0 });
  return (
    // Both flags: `data-shown` drives `.bar-fill`, `data-row-shown` drives
    // `.row-stage`. They are separate attributes because a section must be
    // able to reveal itself without also firing every row inside it.
    <div ref={ref} data-shown={shown} data-row-shown={shown} className={className}>
      {children}
    </div>
  );
}

/**
 * A row inside an already-revealed group.
 *
 * Travels less than a whole section — 10px rather than 18 — because a list
 * that moves as far as its container reads as two competing animations.
 */
export function RevealItem({
  children,
  index = 0,
  className = "",
}: {
  children: ReactNode;
  index?: number;
  className?: string;
}) {
  const { ref, shown } = useReveal<HTMLDivElement>({ rootMargin: "0px 0px -4% 0px" });

  return (
    <div
      ref={ref}
      className={`reveal-item ${className}`}
      data-shown={shown}
      style={staggerStyle(index)}
    >
      {children}
    </div>
  );
}
