"use client";

import { useReveal } from "@/hooks/useReveal";
import { useCountUp } from "@/hooks/useCountUp";
import { formatNumber, formatPercent } from "@/lib/format";

/**
 * Signal extraction.
 *
 * RivalRadar's central claim, made legible: how much came in, how much was
 * rejected, how little actually mattered. A vertical progression down a
 * single rail, with a hairline bar per stage sized against the raw total — so
 * the collapse is visible without a funnel graphic or a box per stage.
 *
 * The stages draw in sequence when the block arrives, top to bottom, which is
 * the order the pipeline actually runs in. It draws once; scrolling back to
 * it shows the finished state.
 */

/** Each stage waits for the one above it to finish drawing. */
const STAGE_DELAY = 90;

interface Props {
  raw: number;
  noise: number;
  meaningful: number;
  highImpact: number;
  noiseReduction: number;
  /** Drops the explanatory sentence; the numbers are unchanged. */
  compact?: boolean;
  /** Namespaces the once-per-session count-up. */
  scope?: string;
}

export function NoisePipeline({
  raw,
  noise,
  meaningful,
  highImpact,
  noiseReduction,
  compact = false,
  scope = "pipeline",
}: Props) {
  const { ref, shown } = useReveal<HTMLDivElement>({ threshold: 0.15 });
  const reduction = useCountUp(noiseReduction, { id: `${scope}:reduction`, play: shown });

  const stages = [
    { label: "raw changes", value: raw, color: "var(--ink-faint)" },
    { label: "filtered as noise", value: noise, color: "var(--neutral)" },
    { label: "meaningful", value: meaningful, color: "var(--accent)" },
    { label: "high impact", value: highImpact, color: "var(--critical)" },
  ];
  const max = Math.max(raw, 1);

  return (
    <div ref={ref} data-shown={shown}>
      <h2 className="eyebrow">Signal extraction</h2>

      <div className="mt-5 flex items-baseline gap-2.5">
        <p className="metric text-[var(--accent)]">{formatPercent(reduction)}</p>
        <p className="text-[13px] text-[var(--ink-soft)]">noise removed</p>
      </div>

      {!compact && (
        <p className="mt-3 max-w-[54ch] text-[12.5px] leading-relaxed text-[var(--ink-soft)]">
          Every raw difference is counted, then kept or rejected by a named rule.
          Nothing is discarded silently.
        </p>
      )}

      <ol className="mt-7 border-l border-[var(--line)]">
        {stages.map((stage, index) => (
          <li key={stage.label} className="relative pb-6 pl-5 last:pb-0">
            <span
              className="absolute left-0 top-[7px] h-[5px] w-[5px] -translate-x-1/2 rounded-full"
              style={{ backgroundColor: stage.color }}
              aria-hidden
            />
            <p className="flex items-baseline gap-2">
              <span className="tabular text-[15px] font-semibold tracking-[-0.018em]">
                {formatNumber(stage.value)}
              </span>
              <span className="text-[12.5px] text-[var(--ink-soft)]">{stage.label}</span>
            </p>
            <div className="mt-2.5 h-[2px] w-full bg-[var(--line)]">
              <div
                className="bar-fill h-full"
                style={{
                  width: `${Math.max((stage.value / max) * 100, 0.8)}%`,
                  backgroundColor: stage.color,
                  ["--bar-delay" as string]: `${index * STAGE_DELAY}ms`,
                }}
              />
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
