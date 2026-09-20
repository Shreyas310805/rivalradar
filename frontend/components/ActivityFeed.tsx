"use client";

import { useReveal } from "@/hooks/useReveal";
import { formatDayHeading, formatTime, pathOf, truncate } from "@/lib/format";
import { staggerDelay } from "@/lib/motion";
import type { Change } from "@/lib/types";

import { ContextLine, SeverityText } from "./ui";

/**
 * Activity feed.
 *
 * Closer to a news wire than a dashboard: a timestamp in the gutter, then
 * context, headline, standfirst and severity set in one column. Entries are
 * separated by a single hairline — no card per item, no badge row.
 *
 * Rows unfold as they arrive, in three grouped stages: when it happened, what
 * happened, then how much it matters. Animating all five lines separately
 * reads as a teleprompter; three stages reads as a record being written.
 */

/** Only the rows likely on screen at load are staggered. A row scrolled to on
 *  its own should answer immediately, not wait its turn in a queue. */
const STAGGERED_ROWS = 6;

export function ActivityFeed({
  changes,
  onSelect,
  showCompetitor = true,
}: {
  changes: Change[];
  onSelect: (change: Change) => void;
  showCompetitor?: boolean;
}) {
  const groups = new Map<string, Change[]>();
  for (const change of changes) {
    const day = formatDayHeading(change.detected_at);
    groups.set(day, [...(groups.get(day) ?? []), change]);
  }

  let position = 0;

  return (
    <div>
      {[...groups.entries()].map(([day, items]) => (
        <section key={day}>
          <div className="sticky top-0 z-10 border-b border-[var(--line)] bg-[var(--canvas)]/95 py-2 backdrop-blur-sm">
            <p className="eyebrow">{day}</p>
          </div>
          {items.map((change) => (
            <ActivityRow
              key={change.id}
              change={change}
              index={position++}
              onSelect={onSelect}
              showCompetitor={showCompetitor}
            />
          ))}
        </section>
      ))}
    </div>
  );
}

function ActivityRow({
  change,
  index,
  onSelect,
  showCompetitor,
}: {
  change: Change;
  index: number;
  onSelect: (change: Change) => void;
  showCompetitor: boolean;
}) {
  const { ref, shown } = useReveal<HTMLButtonElement>({ rootMargin: "0px 0px -4% 0px" });

  const intel = change.intelligence;
  const title = intel?.title ?? `Content changed in ${change.location}`;
  const summary = intel?.summary ?? describe(change);
  const path = pathOf(change.source_url);

  return (
    <button
      ref={ref}
      data-row-shown={shown}
      onClick={() => onSelect(change)}
      style={{
        ["--reveal-delay" as string]: `${index < STAGGERED_ROWS ? staggerDelay(index) : 0}ms`,
      }}
      className="activity-row relative flex w-full gap-6 border-b border-[var(--line)] py-6 text-left sm:-mx-4 sm:w-[calc(100%+2rem)] sm:px-4"
      aria-label={`Open details for ${title}`}
    >
      {/* Hover mark. Sits in the gutter so nothing reflows when it appears. */}
      <span
        className="row-mark absolute left-0 top-1/2 h-[18px] w-[2px] -translate-y-1/2 bg-[var(--ink-faint)] sm:left-1"
        aria-hidden
      />

      {/* Stage one: when, and in what context. */}
      <div className="row-stage hidden w-[68px] shrink-0 sm:block">
        <p className="tabular text-[12px] text-[var(--ink-faint)]">
          {formatTime(change.detected_at)}
        </p>
      </div>

      <div className="min-w-0 flex-1">
        <div className="row-stage flex flex-wrap items-baseline gap-x-3">
          <ContextLine
            category={change.category}
            competitor={showCompetitor ? change.competitor_name : undefined}
          />
          <span className="tabular text-[12px] text-[var(--ink-faint)] sm:hidden">
            {formatTime(change.detected_at)}
          </span>
        </div>

        {/* Stage two: what changed. */}
        <div className="row-stage" style={{ ["--stage" as string]: "70ms" }}>
          <p className="mt-2.5 max-w-[60ch] text-[14px] font-medium leading-snug tracking-[-0.008em]">
            {title}
          </p>
          <p className="mt-1.5 max-w-[68ch] text-[13px] leading-relaxed text-[var(--ink-soft)]">
            {truncate(summary, 165)}
          </p>
        </div>

        {/* Stage three: the evidence and the weight. */}
        <div className="row-stage" style={{ ["--stage" as string]: "140ms" }}>
          {change.before && change.after && (
            <p className="mono mt-3 flex flex-wrap items-center gap-1.5 text-[11.5px]">
              <span className="diff-del">{truncate(change.before, 38)}</span>
              <span className="text-[var(--ink-faint)]" aria-hidden>
                &rarr;
              </span>
              <span className="diff-add">{truncate(change.after, 38)}</span>
            </p>
          )}

          <div className="mt-3.5 flex flex-wrap items-baseline gap-x-4 gap-y-1">
            <SeverityText severity={change.severity} score={change.relevance_score} />
            {/* A bare "/" tells the reader nothing, so the path is shown only
                when it actually locates the change on the site. */}
            {path !== "/" && (
              <span className="mono truncate text-[11px] text-[var(--ink-faint)]">
                {path}
              </span>
            )}
          </div>
        </div>
      </div>
    </button>
  );
}

function describe(change: Change): string {
  if (change.before && change.after) {
    return `Content in the ${change.location} section changed.`;
  }
  if (change.after) return `New content appeared in the ${change.location} section.`;
  if (change.before) return `Content was removed from the ${change.location} section.`;
  return `A change was detected in the ${change.location} section.`;
}
