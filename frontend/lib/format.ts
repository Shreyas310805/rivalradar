/** Shared formatting and severity helpers. */

import type { Category, Severity } from "./types";

export function formatDate(value: string | null | undefined): string {
  if (!value) return "Never";
  const date = new Date(value.endsWith("Z") ? value : `${value}Z`);
  if (Number.isNaN(date.getTime())) return "Unknown";
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "Never";
  const date = new Date(value.endsWith("Z") ? value : `${value}Z`);
  if (Number.isNaN(date.getTime())) return "Unknown";
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function relativeTime(value: string | null | undefined): string {
  if (!value) return "never";
  const date = new Date(value.endsWith("Z") ? value : `${value}Z`);
  if (Number.isNaN(date.getTime())) return "unknown";

  const seconds = Math.round((Date.now() - date.getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days}d ago`;
  return formatDate(value);
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat().format(Math.round(value));
}

export function formatPercent(value: number, digits = 1): string {
  return `${value.toFixed(digits)}%`;
}

/**
 * Maps a severity onto a design token family.
 *
 * Returning a token name (not a hex value) keeps light and dark in step and
 * means severity colour is defined in exactly one place: globals.css.
 */
const SEVERITY_TOKENS: Record<Severity, string> = {
  critical: "critical",
  high: "high",
  medium: "medium",
  low: "low",
  noise: "neutral",
};

export function severityToken(severity: Severity): string {
  return SEVERITY_TOKENS[severity] ?? "neutral";
}

export function severityColor(severity: Severity): string {
  return `var(--${severityToken(severity)})`;
}

export function severityLabel(severity: Severity): string {
  if (severity === "noise") return "Noise";
  return severity.charAt(0).toUpperCase() + severity.slice(1);
}

const CATEGORY_LABELS: Record<Category, string> = {
  pricing: "Pricing",
  features: "Features",
  product: "Product",
  hiring: "Hiring",
  integrations: "Integrations",
  messaging: "Messaging",
  other: "Other",
};

export function categoryLabel(category: string): string {
  return CATEGORY_LABELS[category as Category] ?? capitalise(category);
}

/**
 * Category marks for charts only.
 *
 * Tokens rather than literals, so the desaturated light ramp and the lifted
 * dark one are both defined in globals.css and stay in step automatically.
 */
export const CATEGORY_COLORS: Record<string, string> = {
  pricing: "var(--cat-pricing)",
  features: "var(--cat-features)",
  product: "var(--cat-product)",
  hiring: "var(--cat-hiring)",
  integrations: "var(--cat-integrations)",
  messaging: "var(--cat-messaging)",
  other: "var(--ink-faint)",
};

export function categoryColor(category: string): string {
  return CATEGORY_COLORS[category] ?? "var(--ink-faint)";
}

export function capitalise(value: string): string {
  if (!value) return "";
  return value.charAt(0).toUpperCase() + value.slice(1).replace(/_/g, " ");
}

export function truncate(value: string | null | undefined, max = 140): string {
  if (!value) return "";
  return value.length <= max ? value : `${value.slice(0, max - 1).trimEnd()}…`;
}

export function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

export function pathOf(url: string): string {
  try {
    const parsed = new URL(url);
    return parsed.pathname === "/" ? "/" : parsed.pathname;
  } catch {
    return url;
  }
}

/** Clock time only, for activity-feed rows ("09:42 PM"). */
export function formatTime(value: string | null | undefined): string {
  if (!value) return "";
  const date = new Date(value.endsWith("Z") ? value : `${value}Z`);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

/** Day heading for grouped feeds ("Sep 19"). */
export function formatDayHeading(value: string | null | undefined): string {
  if (!value) return "Unknown";
  const date = new Date(value.endsWith("Z") ? value : `${value}Z`);
  if (Number.isNaN(date.getTime())) return "Unknown";

  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(today.getDate() - 1);
  const sameDay = (a: Date, b: Date) => a.toDateString() === b.toDateString();
  if (sameDay(date, today)) return "Today";
  if (sameDay(date, yesterday)) return "Yesterday";

  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    ...(date.getFullYear() !== today.getFullYear() ? { year: "numeric" } : {}),
  });
}
