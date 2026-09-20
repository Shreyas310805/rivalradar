"use client";

import { useState } from "react";

import { NoisePipeline } from "@/components/NoisePipeline";
import { Reveal } from "@/components/Reveal";
import { PipelineSkeleton, Skeleton } from "@/components/Skeletons";
import {
  Button,
  DetailRow,
  EmptyState,
  ErrorState,
  PageHeader,
  SectionTitle,
} from "@/components/ui";
import { useAction, useApi } from "@/hooks/useApi";
import { api } from "@/lib/api";
import { categoryLabel, formatDateTime, formatNumber, formatPercent } from "@/lib/format";

/**
 * Evaluation.
 *
 * An engineering benchmark page. Two sections, both fed entirely from stored
 * records:
 *  - Live tracking: the funnel measured across real tracked competitor pages.
 *  - Wayback: the same pipeline benchmarked against real archived captures.
 *
 * No figure on this page is estimated or hardcoded.
 */
export default function EvaluationPage() {
  const evaluations = useApi(() => api.listEvaluations(), []);
  const stats = useApi(() => api.getStats(), []);
  const run = useAction(api.runEvaluation);

  const [url, setUrl] = useState("https://www.python.org/");
  const [fromDate, setFromDate] = useState("2023-01-01");
  const [toDate, setToDate] = useState("2024-12-31");

  const latest = evaluations.data?.[0];
  const live = stats.data;

  return (
    <div className="animate-page">
      <PageHeader
        title="Evaluation"
        description="Every number here is counted from database records produced by actual pipeline runs. Nothing is estimated."
      />

      {/* --- Live tracking ---------------------------------------------- */}
      <Reveal as="section" className="mt-12 mb-20">
        <SectionTitle
          title="Live tracking"
          description="Measured across every real competitor page you track."
        />
        {stats.loading && !live ? (
          <PipelineSkeleton />
        ) : stats.error ? (
          <ErrorState message={stats.error} onRetry={stats.refetch} compact />
        ) : !live || live.raw_changes === 0 ? (
          <EmptyState
            compact
            title="No live tracking data yet"
            description="Add a competitor and scan it twice — once for the baseline, once to detect what changed."
          />
        ) : (
          <div className="grid gap-10 lg:grid-cols-[minmax(0,1fr)_300px] lg:gap-0">
            <div className="lg:pr-10">
              <NoisePipeline
                raw={live.raw_changes}
                noise={live.noise_changes}
                meaningful={live.meaningful_changes}
                highImpact={live.high_impact_changes}
                noiseReduction={live.noise_reduction}
                compact
                scope="eval-live"
              />
            </div>
            <div className="lg:border-l lg:border-[var(--line)] lg:pl-12">
              <h3 className="eyebrow mb-1">Coverage</h3>
              <dl className="divide-y divide-[var(--line)]">
                <DetailRow label="Competitors" value={String(live.tracked_competitors)} />
                <DetailRow label="Pages tracked" value={String(live.tracked_urls)} />
                <DetailRow label="Snapshots stored" value={String(live.total_snapshots)} />
                <DetailRow
                  label="Analyst"
                  value={live.llm_is_llm ? live.llm_label : "Deterministic"}
                />
                {live.llm_is_llm && <DetailRow label="Model" value={live.llm_model} mono />}
              </dl>
            </div>
          </div>
        )}
      </Reveal>

      {/* --- Wayback ------------------------------------------------------ */}
      <Reveal as="section">
        <SectionTitle
          title="Wayback benchmark"
          description="The same pipeline run over two real historical captures from the Internet Archive."
        />

        <form
          onSubmit={async (event) => {
            event.preventDefault();
            if (await run.run(url.trim(), fromDate, toDate)) evaluations.refetch();
          }}
          className="grid gap-4 border-y border-[var(--line)] py-6 sm:grid-cols-[2fr_1fr_1fr_auto] sm:items-end"
        >
          <label className="block">
            <span className="field-label mb-2">Target URL</span>
            <input
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              required
              className="input"
              placeholder="https://example.com"
            />
          </label>
          <label className="block">
            <span className="field-label mb-2">From</span>
            <input
              type="date"
              value={fromDate}
              onChange={(event) => setFromDate(event.target.value)}
              className="input"
            />
          </label>
          <label className="block">
            <span className="field-label mb-2">To</span>
            <input
              type="date"
              value={toDate}
              onChange={(event) => setToDate(event.target.value)}
              className="input"
            />
          </label>
          <Button type="submit" disabled={run.pending}>
            {run.pending ? "Running…" : "Run"}
          </Button>
        </form>

        {run.pending && (
          <p className="mt-4 max-w-[62ch] text-[12.5px] leading-relaxed text-[var(--ink-faint)]">
            Querying the CDX API, downloading two captures and running the full
            pipeline. This usually takes 30&ndash;90 seconds.
          </p>
        )}
        {run.error && (
          <div className="mt-6">
            <ErrorState
              title="Evaluation could not complete"
              message={run.error}
              compact
            />
          </div>
        )}

        <div className="mt-12">
          {evaluations.loading && !evaluations.data ? (
            <Skeleton className="h-[180px] w-full" />
          ) : evaluations.error ? (
            <ErrorState message={evaluations.error} onRetry={evaluations.refetch} />
          ) : !evaluations.data?.length ? (
            <EmptyState
              compact
              title="No benchmarks run yet"
              description="Run an evaluation above, or from the CLI with: rivalradar wayback --url https://example.com"
            />
          ) : (
            <>
              {latest && (
                <div className="mb-16 grid gap-10 lg:grid-cols-[minmax(0,1fr)_300px] lg:gap-0">
                  <div className="lg:pr-10">
                    <NoisePipeline
                      raw={latest.raw_changes}
                      noise={latest.noise_changes}
                      meaningful={latest.meaningful_changes}
                      highImpact={latest.high_impact_changes}
                      noiseReduction={latest.noise_reduction}
                      compact
                      scope="eval-wayback"
                    />
                  </div>
                  <div className="lg:border-l lg:border-[var(--line)] lg:pl-10">
                    <h3 className="eyebrow mb-2">Latest run</h3>
                    <p className="mono mb-2 truncate text-[12px] text-[var(--ink-soft)]">
                      {latest.target_url}
                    </p>
                    <dl className="divide-y divide-[var(--line)]">
                      <DetailRow
                        label="Snapshots"
                        value={
                          latest.snapshot_a && latest.snapshot_b
                            ? `${stamp(latest.snapshot_a)} → ${stamp(latest.snapshot_b)}`
                            : "n/a"
                        }
                        mono
                      />
                      <DetailRow
                        label="Pages evaluated"
                        value={String(latest.pages_evaluated)}
                      />
                      <DetailRow label="Status" value={latest.status} />
                      <DetailRow label="Run at" value={formatDateTime(latest.created_at)} />
                    </dl>
                    <CategoryBreakdown raw={latest.category_breakdown} />
                  </div>
                </div>
              )}

              <SectionTitle title="Benchmark history" />
              <div className="overflow-x-auto">
                <table className="w-full min-w-[720px] border-collapse text-[12.5px]">
                  <thead>
                    <tr className="border-y border-[var(--line)] text-left">
                      <Th>Target</Th>
                      <Th>Snapshots</Th>
                      <Th align="right">Raw</Th>
                      <Th align="right">Noise</Th>
                      <Th align="right">Meaningful</Th>
                      <Th align="right">High impact</Th>
                      <Th align="right">Removed</Th>
                      <Th>Run at</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {evaluations.data.map((item) => (
                      <tr
                        key={item.id}
                        className="border-b border-[var(--line)] transition-colors duration-[var(--dur-fast)] hover:bg-[var(--raised)]"
                      >
                        <Td>
                          <span className="mono block max-w-[210px] truncate text-[11.5px]">
                            {item.target_url}
                          </span>
                        </Td>
                        <Td>
                          <span className="mono text-[11px] text-[var(--ink-faint)]">
                            {item.snapshot_a && item.snapshot_b
                              ? `${stamp(item.snapshot_a)} → ${stamp(item.snapshot_b)}`
                              : "—"}
                          </span>
                        </Td>
                        <Td align="right">{formatNumber(item.raw_changes)}</Td>
                        <Td align="right">{formatNumber(item.noise_changes)}</Td>
                        <Td align="right">{formatNumber(item.meaningful_changes)}</Td>
                        <Td align="right">{formatNumber(item.high_impact_changes)}</Td>
                        <Td align="right">
                          <span className="font-medium">
                            {formatPercent(item.noise_reduction)}
                          </span>
                        </Td>
                        <Td>
                          <span className="text-[var(--ink-faint)]">
                            {formatDateTime(item.created_at)}
                          </span>
                        </Td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
        </div>
      </Reveal>
    </div>
  );
}

/** Format a 14-digit CDX timestamp as YYYY-MM-DD. */
function stamp(value: string): string {
  return value.length < 8
    ? value
    : `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`;
}

function CategoryBreakdown({ raw }: { raw: string }) {
  let parsed: Record<string, number> = {};
  try {
    parsed = JSON.parse(raw || "{}");
  } catch {
    parsed = {};
  }
  const entries = Object.entries(parsed).filter(([, count]) => count > 0);
  if (!entries.length) return null;

  return (
    <div className="mt-6">
      <h3 className="eyebrow mb-2.5">Detection categories</h3>
      <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-[12px] text-[var(--ink-faint)]">
        {entries.map(([category, count]) => (
          <span key={category}>
            {categoryLabel(category)}{" "}
            <span className="tabular font-medium text-[var(--ink)]">{count}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

function Th({ children, align }: { children: React.ReactNode; align?: "right" }) {
  return (
    <th
      className={`eyebrow py-3 pr-6 font-medium last:pr-0 ${
        align === "right" ? "text-right" : ""
      }`}
    >
      {children}
    </th>
  );
}

function Td({ children, align }: { children: React.ReactNode; align?: "right" }) {
  return (
    <td
      className={`py-3 pr-6 last:pr-0 ${align === "right" ? "tabular text-right" : ""}`}
    >
      {children}
    </td>
  );
}
