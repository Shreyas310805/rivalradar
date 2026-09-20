"use client";

import { Notice } from "./ui";

/**
 * Honest provenance.
 *
 * These components exist so the interface can never imply AI involvement that
 * did not happen. When no model ran, they say so plainly. All of them are
 * text: provenance is a footnote, not a badge.
 */

/**
 * Per-record provenance line.
 *
 * Set faint and inline so it reads as a byline under the analysis rather than
 * a claim about it.
 */
export function AnalysisSource({
  status,
  model,
}: {
  status: string;
  model?: string | null;
}) {
  const text: Record<string, string> = {
    ok: model ? `AI analysis · ${shortModel(model)}` : "AI analysis",
    rate_limited: "Rule-based · AI rate limited",
    failed: "Rule-based · AI unavailable",
    budget: "Rule-based · request budget reached",
    skipped: "Rule-based",
  };

  return (
    <span
      className="text-[11.5px] text-[var(--ink-faint)]"
      title={status === "ok" && model ? model : undefined}
    >
      {text[status] ?? text.skipped}
    </span>
  );
}

/** Trim a provider-prefixed slug for display. */
function shortModel(model: string): string {
  const tail = model.includes("/") ? model.split("/").pop()! : model;
  return tail.replace(/:free$/, "");
}

/** Banner explaining a degraded LLM, shown once per page. */
export function LlmStatusNotice({ status }: { status: string | null }) {
  if (!status || status === "ok" || status === "skipped") return null;

  const messages: Record<string, string> = {
    rate_limited:
      "AI analysis is temporarily unavailable — the free-tier rate limit was reached. Detection, filtering and scoring ran normally; the write-ups below are rule-based.",
    failed:
      "AI analysis is temporarily unavailable — the model could not be reached. Detection, filtering and scoring ran normally; the write-ups below are rule-based.",
    budget:
      "Some changes were written up without AI to stay inside the per-scan request budget. Detection and scoring are unaffected.",
  };
  const message = messages[status];
  if (!message) return null;

  return <Notice>{message}</Notice>;
}
