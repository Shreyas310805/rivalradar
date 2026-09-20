"use client";

import { categoryColor, categoryLabel, formatNumber } from "@/lib/format";
import type { CategoryCount, NoiseReasonCount, TimelinePoint } from "@/lib/types";

/**
 * Charts.
 *
 * Hand-drawn SVG rather than a charting library: the shapes needed here are
 * simple, drawing them directly keeps the bundle free of a dependency, and
 * every mark inherits the design tokens — which is what makes them work in
 * both themes without a second palette.
 *
 * Rules: flat fills, square corners, one baseline plus one midline, no
 * gradients, no plot background, no rainbow.
 */

function EmptyChart({ label, height = 88 }: { label: string; height?: number }) {
  return (
    <div className="flex items-center justify-center" style={{ height }}>
      <p className="text-[12px] text-[var(--ink-faint)]">{label}</p>
    </div>
  );
}

/** Daily volume: noise underneath, meaningful on top, high-impact marked. */
export function ActivityChart({ data }: { data: TimelinePoint[] }) {
  if (!data.length) return <EmptyChart label="No activity recorded yet" height={180} />;

  const width = 680;
  const height = 180;
  const pad = { top: 12, right: 6, bottom: 24, left: 30 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;

  const max = Math.max(...data.map((point) => point.raw_changes), 1);
  const step = plotW / data.length;
  const barW = Math.max(2, Math.min(22, step - 6));
  // Two references only: the baseline and a single midline.
  const ticks = [Math.round(max / 2), max];

  return (
    <div>
      <div className="overflow-x-auto">
        <svg
          viewBox={`0 0 ${width} ${height}`}
          className="h-[180px] w-full min-w-[440px]"
          role="img"
          aria-label="Daily change volume"
        >
          {ticks.map((tick) => {
            const y = pad.top + plotH - (tick / max) * plotH;
            return (
              <g key={tick}>
                <line
                  x1={pad.left}
                  y1={y}
                  x2={width - pad.right}
                  y2={y}
                  stroke="var(--line)"
                  strokeWidth="1"
                />
                <text
                  x={pad.left - 8}
                  y={y + 3}
                  textAnchor="end"
                  fontSize="9.5"
                  fill="var(--ink-faint)"
                >
                  {tick}
                </text>
              </g>
            );
          })}

          {data.map((point, index) => {
            const x = pad.left + index * step + (step - barW) / 2;
            const meaningfulH = (point.meaningful_changes / max) * plotH;
            const noiseH =
              ((point.raw_changes - point.meaningful_changes) / max) * plotH;
            return (
              <g key={point.date}>
                <title>
                  {point.date}: {point.raw_changes} raw, {point.meaningful_changes}{" "}
                  meaningful, {point.high_impact_changes} high impact
                </title>
                <rect
                  x={x}
                  y={pad.top + plotH - noiseH}
                  width={barW}
                  height={Math.max(0, noiseH)}
                  fill="var(--line-strong)"
                />
                <rect
                  x={x}
                  y={pad.top + plotH - noiseH - meaningfulH}
                  width={barW}
                  height={Math.max(0, meaningfulH)}
                  fill="var(--accent)"
                />
                {point.high_impact_changes > 0 && (
                  <circle
                    cx={x + barW / 2}
                    cy={pad.top + plotH - noiseH - meaningfulH - 6}
                    r="2"
                    fill="var(--critical)"
                  />
                )}
              </g>
            );
          })}

          <line
            x1={pad.left}
            y1={pad.top + plotH}
            x2={width - pad.right}
            y2={pad.top + plotH}
            stroke="var(--line-strong)"
            strokeWidth="1"
          />

          {data.map((point, index) => {
            const stride = Math.max(1, Math.ceil(data.length / 7));
            if (index % stride !== 0) return null;
            return (
              <text
                key={point.date}
                x={pad.left + index * step + step / 2}
                y={height - 7}
                textAnchor="middle"
                fontSize="9.5"
                fill="var(--ink-faint)"
              >
                {point.date.slice(5)}
              </text>
            );
          })}
        </svg>
      </div>

      <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5 text-[11.5px] text-[var(--ink-faint)]">
        <Legend color="var(--accent)" label="Meaningful" />
        <Legend color="var(--line-strong)" label="Filtered as noise" />
        <Legend color="var(--critical)" label="Had high-impact changes" round />
      </div>
    </div>
  );
}

/** Horizontal category bars. */
export function CategoryBars({ data }: { data: CategoryCount[] }) {
  if (!data.length) return <EmptyChart label="No categorised changes yet" />;
  const max = Math.max(...data.map((item) => item.count), 1);

  return (
    <div className="space-y-3.5">
      {data.map((item, index) => (
        <div key={item.category}>
          <div className="flex items-baseline justify-between text-[12.5px]">
            <span className="text-[var(--ink-soft)]">{categoryLabel(item.category)}</span>
            <span className="tabular font-medium">{item.count}</span>
          </div>
          <div className="mt-2 h-[2px] w-full bg-[var(--line)]">
            <div
              className="bar-fill h-full"
              style={{
                width: `${(item.count / max) * 100}%`,
                backgroundColor: categoryColor(item.category),
                ["--bar-delay" as string]: `${index * 40}ms`,
              }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

/** Which noise rules did the most work — the filter's receipts. */
export function NoiseReasons({ data }: { data: NoiseReasonCount[] }) {
  if (!data.length) return <EmptyChart label="Nothing has been filtered yet" />;
  const total = data.reduce((sum, item) => sum + item.count, 0);

  return (
    <div className="space-y-3.5">
      {data.map((item, index) => (
        <div key={item.reason}>
          <div className="flex items-baseline justify-between gap-4 text-[12.5px]">
            <span className="truncate text-[var(--ink-soft)]" title={item.reason}>
              {item.reason}
            </span>
            <span className="tabular shrink-0 font-medium">
              {formatNumber(item.count)}
            </span>
          </div>
          <div className="mt-2 h-[2px] w-full bg-[var(--line)]">
            <div
              className="bar-fill h-full bg-[var(--neutral)]"
              style={{
                width: `${(item.count / total) * 100}%`,
                ["--bar-delay" as string]: `${index * 40}ms`,
              }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

/** Severity mix as one proportional bar. */
export function SeverityBar({ data }: { data: CategoryCount[] }) {
  const total = data.reduce((sum, item) => sum + item.count, 0);
  if (!total) return <EmptyChart label="No scored changes yet" height={56} />;

  const token = (name: string) =>
    ({
      critical: "var(--critical)",
      high: "var(--high)",
      medium: "var(--medium)",
      low: "var(--low)",
      noise: "var(--neutral)",
    })[name] ?? "var(--neutral)";

  return (
    <div>
      <div className="bar-fill flex h-[6px] w-full overflow-hidden">
        {data.map((item) => (
          <div
            key={item.category}
            title={`${item.category}: ${item.count}`}
            style={{
              width: `${(item.count / total) * 100}%`,
              backgroundColor: token(item.category),
            }}
          />
        ))}
      </div>
      <div className="mt-3.5 flex flex-wrap gap-x-5 gap-y-1.5">
        {data.map((item) => (
          <span
            key={item.category}
            className="flex items-baseline gap-1.5 text-[12px] text-[var(--ink-soft)]"
          >
            <span
              className="h-[5px] w-[5px] translate-y-[-1px] rounded-full"
              style={{ backgroundColor: token(item.category) }}
              aria-hidden
            />
            {categoryLabel(item.category)}
            <span className="tabular font-medium text-[var(--ink)]">{item.count}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

function Legend({
  color,
  label,
  round,
}: {
  color: string;
  label: string;
  round?: boolean;
}) {
  return (
    <span className="flex items-center gap-1.5">
      <span
        className={round ? "h-[5px] w-[5px] rounded-full" : "h-[2px] w-3"}
        style={{ backgroundColor: color }}
        aria-hidden
      />
      {label}
    </span>
  );
}
