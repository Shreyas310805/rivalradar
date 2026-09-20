"use client";

import { Loader2 } from "lucide-react";
import { useEffect, type ReactNode } from "react";

import { useScrolledPast } from "@/hooks/useReveal";
import { categoryLabel, severityColor, severityLabel } from "@/lib/format";
import type { Severity } from "@/lib/types";

import { usePageChrome, usePublishChrome } from "./PageChrome";

/* =========================================================================
   Primitives.

   Two rules run through this file. Colour is reserved for meaning, so a
   severity is a coloured dot beside neutral text rather than a filled chip.
   And a container earns its border: if whitespace and alignment can do the
   separating, there is no border.
   ========================================================================= */

/**
 * Severity, as a line of text.
 *
 * `• High · 82`. The dot carries the colour, the words carry the meaning and
 * the number stays tabular so a column of them aligns.
 */
export function SeverityText({
  severity,
  score,
  className = "",
}: {
  severity: Severity;
  score?: number;
  className?: string;
}) {
  return (
    <span
      className={`inline-flex items-baseline gap-1.5 text-[12px] text-[var(--ink-soft)] ${className}`}
    >
      <span
        className="h-[5px] w-[5px] shrink-0 translate-y-[-1px] rounded-full"
        style={{ backgroundColor: severityColor(severity) }}
        aria-hidden
      />
      {severityLabel(severity)}
      {score !== undefined && (
        <>
          <span className="text-[var(--ink-faint)]" aria-hidden>
            &middot;
          </span>
          <span className="tabular font-medium text-[var(--ink)]">
            {Math.round(score)}
          </span>
        </>
      )}
    </span>
  );
}

/**
 * `Features · Python.org` — the context line above a change title.
 *
 * Plain text with a middot, not two chips. Category is de-emphasised because
 * it is orientation; the competitor name is what the eye is scanning for.
 */
export function ContextLine({
  category,
  competitor,
  className = "",
}: {
  category: string;
  competitor?: string;
  className?: string;
}) {
  return (
    <p className={`text-[12px] text-[var(--ink-faint)] ${className}`}>
      {categoryLabel(category)}
      {competitor && (
        <>
          <span className="px-1" aria-hidden>
            &middot;
          </span>
          <span className="font-medium text-[var(--ink-soft)]">{competitor}</span>
        </>
      )}
    </p>
  );
}

export function Button({
  children,
  onClick,
  variant = "primary",
  size = "md",
  disabled,
  type = "button",
  title,
  full,
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md";
  disabled?: boolean;
  type?: "button" | "submit";
  title?: string;
  full?: boolean;
}) {
  // The press is the only scale in the system, and it is 2%: enough to feel
  // the button give, not enough to see it move.
  const base =
    "inline-flex items-center justify-center gap-1.5 rounded-[var(--radius-sm)] font-medium " +
    "whitespace-nowrap transition-[background-color,border-color,color,opacity,transform] " +
    "duration-[var(--dur-fast)] [transition-timing-function:var(--ease)] active:scale-[0.98] " +
    "disabled:pointer-events-none disabled:opacity-40";
  const sizes = {
    sm: "px-2.5 py-[5px] text-[12.5px]",
    md: "px-3 py-[6px] text-[13px]",
  };
  // Primary is near-black, not blue: the accent stays reserved for links and
  // data marks, so a page never has two competing "important" colours.
  const variants = {
    primary: "bg-[var(--ink)] text-[var(--canvas)] hover:opacity-85",
    secondary:
      "border border-[var(--line-strong)] text-[var(--ink)] hover:bg-[var(--raised)]",
    ghost: "text-[var(--ink-soft)] hover:bg-[var(--raised)] hover:text-[var(--ink)]",
    danger:
      "border border-[var(--line-strong)] text-[var(--critical)] hover:bg-[var(--critical-soft)] hover:border-[var(--critical-line)]",
  };
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`${base} ${sizes[size]} ${variants[variant]} ${full ? "w-full" : ""}`}
    >
      {children}
    </button>
  );
}

/**
 * Page masthead.
 *
 * Also the source of the contextual bar in the shell: it publishes the title,
 * and a sentinel underneath it reports when the masthead has scrolled away.
 * The page never has to know the bar exists.
 */
export function PageHeader({
  title,
  description,
  action,
  meta,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  /** One short line of status, echoed into the contextual bar. */
  meta?: string;
}) {
  const { setCompact } = usePageChrome();
  const { ref, past } = useScrolledPast<HTMLDivElement>();

  usePublishChrome(title, meta);

  useEffect(() => setCompact(past), [past, setCompact]);
  useEffect(() => () => setCompact(false), [setCompact]);

  return (
    <>
      <header className="flex flex-wrap items-end justify-between gap-x-10 gap-y-4">
        <div className="min-w-0">
          <h1>{title}</h1>
          {description && (
            <p className="mt-2 max-w-[60ch] text-[13.5px] leading-relaxed text-[var(--ink-soft)]">
              {description}
            </p>
          )}
        </div>
        {action && <div className="flex shrink-0 items-center gap-2">{action}</div>}
      </header>
      <div ref={ref} aria-hidden className="h-px" />
    </>
  );
}

/**
 * Section heading.
 *
 * The one place uppercase is used: small, tracked, faint — a filing label
 * above the content rather than a title competing with it.
 */
export function SectionTitle({
  title,
  description,
  action,
  className = "",
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`mb-5 flex flex-wrap items-baseline justify-between gap-x-6 gap-y-1 ${className}`}
    >
      <div className="min-w-0">
        <h2 className="eyebrow">{title}</h2>
        {description && (
          <p className="mt-2 max-w-[62ch] text-[12.5px] leading-relaxed text-[var(--ink-soft)]">
            {description}
          </p>
        )}
      </div>
      {action}
    </div>
  );
}

/** Empty state: type and whitespace. No illustration, no border, no card. */
export function EmptyState({
  title,
  description,
  action,
  compact,
}: {
  title: string;
  description: string;
  action?: ReactNode;
  compact?: boolean;
}) {
  return (
    <div className={`text-center ${compact ? "py-12" : "py-24"}`}>
      <p className="text-[13.5px] font-medium">{title}</p>
      <p className="mx-auto mt-2 max-w-[46ch] text-[13px] leading-relaxed text-[var(--ink-soft)]">
        {description}
      </p>
      {action && <div className="mt-7 flex justify-center">{action}</div>}
    </div>
  );
}

/**
 * Error state.
 *
 * A rule in the critical colour and plain language — no filled red panel and
 * never a stack trace.
 */
export function ErrorState({
  title = "Something went wrong",
  message,
  onRetry,
  compact,
}: {
  title?: string;
  message: string;
  onRetry?: () => void;
  compact?: boolean;
}) {
  return (
    <div
      className={`border-l-2 border-[var(--critical)] pl-4 ${compact ? "py-1" : "py-2"}`}
    >
      <p className="text-[13.5px] font-medium text-[var(--critical)]">{title}</p>
      <p className="mt-1 max-w-[62ch] text-[13px] leading-relaxed text-[var(--ink-soft)]">
        {message}
      </p>
      {onRetry && (
        <div className="mt-3">
          <Button variant="secondary" size="sm" onClick={onRetry}>
            Retry
          </Button>
        </div>
      )}
    </div>
  );
}

/** Advisory notice — for degraded-but-working conditions. */
export function Notice({ children }: { children: ReactNode }) {
  return (
    <div className="border-l-2 border-[var(--high)] py-1 pl-4">
      <p className="max-w-[72ch] text-[12.5px] leading-relaxed text-[var(--ink-soft)]">
        {children}
      </p>
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <span className="inline-flex items-center gap-2 text-[12.5px] text-[var(--ink-soft)]">
      <Loader2 size={13} strokeWidth={2} className="animate-spin" />
      {label}
    </span>
  );
}

/** A key/value row used in detail panels. */
export function DetailRow({
  label,
  value,
  mono,
}: {
  label: string;
  value: ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-6 py-[7px]">
      <dt className="shrink-0 text-[12.5px] text-[var(--ink-faint)]">{label}</dt>
      <dd className={`min-w-0 truncate text-right text-[12.5px] ${mono ? "mono" : ""}`}>
        {value}
      </dd>
    </div>
  );
}

/**
 * Hairline meter. Two pixels, square ends — a rule, not a pill.
 *
 * Draws itself when its section arrives: `.bar-fill` is collapsed only while
 * an ancestor is still unrevealed, so a meter outside a revealed section
 * still renders at full length.
 */
export function Meter({
  value,
  color = "var(--accent)",
  ariaLabel,
  delay = 0,
}: {
  value: number;
  color?: string;
  ariaLabel?: string;
  delay?: number;
}) {
  const clamped = Math.max(0, Math.min(100, value));
  return (
    <div
      className="h-[2px] w-full overflow-hidden bg-[var(--line)]"
      role="img"
      aria-label={ariaLabel ?? `${Math.round(clamped)} of 100`}
    >
      <div
        className="bar-fill h-full"
        style={{
          width: `${Math.max(clamped, 1)}%`,
          backgroundColor: color,
          ["--bar-delay" as string]: `${delay}ms`,
        }}
      />
    </div>
  );
}

/** Monitoring state, as text with a status dot. */
export function StatusText({ active }: { active: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[12px] text-[var(--ink-faint)]">
      <span
        className="h-[5px] w-[5px] rounded-full"
        style={{ backgroundColor: active ? "var(--low)" : "var(--ink-faint)" }}
        aria-hidden
      />
      {active ? "Monitoring" : "Paused"}
    </span>
  );
}

/**
 * Segmented control.
 *
 * Underline-selected rather than a pill inside a tray: fewer shapes, and the
 * options read as one row of text the way a filter bar should.
 */
export function Segmented({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
      <span className="text-[12px] text-[var(--ink-faint)]">{label}</span>
      <div className="flex flex-wrap items-baseline gap-x-3.5 gap-y-1">
        {options.map((option) => {
          const active = option.value === value;
          return (
            <button
              key={option.value}
              onClick={() => onChange(option.value)}
              aria-pressed={active}
              className={`border-b py-[1px] text-[12.5px] transition-colors duration-[var(--dur-fast)] [transition-timing-function:var(--ease)] ${
                active
                  ? "border-[var(--ink)] font-medium text-[var(--ink)]"
                  : "border-transparent text-[var(--ink-faint)] hover:text-[var(--ink)]"
              }`}
            >
              {option.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
