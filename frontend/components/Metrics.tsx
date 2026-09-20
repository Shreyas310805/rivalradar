"use client";

import type { ReactNode } from "react";

import { useReveal } from "@/hooks/useReveal";
import { useCountUp } from "@/hooks/useCountUp";
import { staggerStyle } from "@/lib/motion";

/**
 * Metrics.
 *
 * One horizontal strip divided by hairlines — not four cards. The figure
 * leads, the label sits under it in sentence case, and a closing rule
 * separates the band from whatever follows. Nothing is boxed.
 *
 * The strip counts up when it arrives in the viewport and never again, and
 * dims slightly once the reader has scrolled past it, so whatever they have
 * moved on to is the thing in focus.
 */

export interface MetricSpec {
  label: string;
  value: number;
  /** Rendered instead of the animated number (e.g. "79.3%"). */
  display?: (value: number) => string;
  hint?: ReactNode;
  accent?: string;
}

function MetricValue({
  id,
  value,
  display,
  accent,
  play,
}: {
  id: string;
  value: number;
  display?: (value: number) => string;
  accent?: string;
  play: boolean;
}) {
  const animated = useCountUp(value, { id, play });
  // `|| 0` normalises negative zero, which formats as "-0".
  const text = display
    ? display(animated)
    : (Math.round(animated) || 0).toLocaleString();
  return (
    <p className="metric" style={accent ? { color: accent } : undefined}>
      {text}
    </p>
  );
}

export function MetricStrip({
  metrics,
  scope = "metrics",
}: {
  metrics: MetricSpec[];
  /** Namespaces the once-per-session count-up so two pages do not collide. */
  scope?: string;
}) {
  const { ref, shown } = useReveal<HTMLDivElement>({ threshold: 0.2 });

  return (
    // The strip itself does not fade: it is already inside a revealing
    // section, and two fades on the same pixels read as a stutter. Only the
    // four figures stagger in.
    <div
      ref={ref}
      className="grid grid-cols-2 border-b border-[var(--line)] pb-9 lg:grid-cols-4"
    >
      {metrics.map((metric, index) => (
        <div
          key={metric.label}
          data-shown={shown}
          style={staggerStyle(index)}
          className={`reveal-item px-5 first:pl-0 ${index < 2 ? "pb-8 lg:pb-0" : ""} ${
            index % 2 === 1
              ? "border-l border-[var(--line)]"
              : "lg:border-l lg:border-[var(--line)] lg:first:border-l-0"
          }`}
        >
          <MetricValue
            id={`${scope}:${metric.label}`}
            value={metric.value}
            display={metric.display}
            accent={metric.accent}
            play={shown}
          />
          <p className="mt-2.5 text-[13px] text-[var(--ink-soft)]">{metric.label}</p>
          {metric.hint && (
            <p className="mt-1 text-[12px] leading-relaxed text-[var(--ink-faint)]">
              {metric.hint}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}

/** Compact figure for secondary areas: digest statistics, scan summaries. */
export function Figure({
  label,
  value,
  accent,
}: {
  label: string;
  value: number | string;
  accent?: string;
}) {
  return (
    <div>
      <p
        className="tabular text-[19px] font-semibold leading-none tracking-[-0.024em]"
        style={accent ? { color: accent } : undefined}
      >
        {typeof value === "number" ? value.toLocaleString() : value}
      </p>
      <p className="mt-2 text-[12px] text-[var(--ink-faint)]">{label}</p>
    </div>
  );
}
