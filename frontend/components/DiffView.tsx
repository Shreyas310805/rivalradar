"use client";

import type { DiffSegment } from "@/lib/types";

import { Draw } from "./Reveal";

/**
 * Before/after comparison.
 *
 * Two presentations from the same data:
 *  - `InlineDiff` for short values (a price, a plan limit) — reads as a single
 *    "X became Y" statement, which is how a person thinks about it.
 *  - `SplitDiff` for prose, with word-level highlighting in two columns.
 *
 * The threshold is length, because a side-by-side of two four-word strings
 * wastes the screen and an inline diff of two paragraphs is unreadable.
 *
 * Both reveal in order — the previous state, then the current one — so the
 * comparison is read as a sequence rather than presented as a fait accompli.
 * The tinted diff spans are the only colour here; a filled header bar as well
 * would bury them.
 */

const INLINE_MAX = 48;

/** The "after" column follows the "before" by this much. */
const AFTER_DELAY = 110;

export function ChangeComparison({
  before,
  after,
  segments,
}: {
  before: string | null;
  after: string | null;
  segments: DiffSegment[];
}) {
  const short =
    (before?.length ?? 0) <= INLINE_MAX && (after?.length ?? 0) <= INLINE_MAX;

  return short ? (
    <InlineDiff before={before} after={after} />
  ) : (
    <SplitDiff before={before} after={after} segments={segments} />
  );
}

/** Compact "before → after" for short values. */
export function InlineDiff({
  before,
  after,
}: {
  before: string | null;
  after: string | null;
}) {
  return (
    <Draw className="grid gap-6 border-y border-[var(--line)] py-6 sm:grid-cols-2 sm:gap-0">
      <div className="row-stage sm:pr-8">
        <p className="eyebrow">Before</p>
        {before ? (
          <p className="mono mt-2.5 text-[13px] leading-relaxed text-[var(--ink-soft)]">
            {before}
          </p>
        ) : (
          <p className="mt-2.5 text-[13px] text-[var(--ink-faint)]">
            nothing — this content is new
          </p>
        )}
      </div>

      <div
        className="row-stage sm:border-l sm:border-[var(--line)] sm:pl-8"
        style={{ ["--stage" as string]: `${AFTER_DELAY}ms` }}
      >
        <p className="eyebrow">After</p>
        {after ? (
          <p className="mono mt-2.5 text-[13px] font-medium leading-relaxed text-[var(--ink)]">
            {after}
          </p>
        ) : (
          <p className="mt-2.5 text-[13px] text-[var(--ink-faint)]">
            nothing — this content was removed
          </p>
        )}
      </div>
    </Draw>
  );
}

/** Two-column word-level diff for longer text. */
export function SplitDiff({
  before,
  after,
  segments,
}: {
  before: string | null;
  after: string | null;
  segments: DiffSegment[];
}) {
  const hasSegments = segments.length > 0;

  return (
    <Draw className="grid border-y border-[var(--line)] md:grid-cols-2">
      <div className="row-stage border-b border-[var(--line)] py-6 md:border-b-0 md:border-r md:pr-8">
        <p className="eyebrow">Before</p>
        <div className="mt-3 max-h-[320px] overflow-y-auto">
          {before ? (
            <p className="mono whitespace-pre-wrap break-words text-[12.5px] leading-[1.75] text-[var(--ink-soft)]">
              {hasSegments
                ? segments
                    .filter((segment) => segment.op !== "insert")
                    .map((segment, index) =>
                      segment.op === "delete" ? (
                        <span key={index} className="diff-del">
                          {segment.before}
                        </span>
                      ) : (
                        <span key={index}>{segment.before}</span>
                      ),
                    )
                : before}
            </p>
          ) : (
            <p className="text-[13px] text-[var(--ink-faint)]">
              nothing — this content is new
            </p>
          )}
        </div>
      </div>

      <div
        className="row-stage py-6 md:pl-8"
        style={{ ["--stage" as string]: `${AFTER_DELAY}ms` }}
      >
        <p className="eyebrow">After</p>
        <div className="mt-3 max-h-[320px] overflow-y-auto">
          {after ? (
            <p className="mono whitespace-pre-wrap break-words text-[12.5px] leading-[1.75] text-[var(--ink)]">
              {hasSegments
                ? segments
                    .filter((segment) => segment.op !== "delete")
                    .map((segment, index) =>
                      segment.op === "insert" ? (
                        <span key={index} className="diff-add">
                          {segment.after}
                        </span>
                      ) : (
                        <span key={index}>{segment.after}</span>
                      ),
                    )
                : after}
            </p>
          ) : (
            <p className="text-[13px] text-[var(--ink-faint)]">
              nothing — this content was removed
            </p>
          )}
        </div>
      </div>
    </Draw>
  );
}
