"use client";

import Link from "next/link";
import { useState } from "react";

import { ActivityChart, CategoryBars, NoiseReasons, SeverityBar } from "@/components/Charts";
import { MetricStrip } from "@/components/Metrics";
import { NoisePipeline } from "@/components/NoisePipeline";
import { Reveal } from "@/components/Reveal";
import { ChartSkeleton, MetricsSkeleton, PipelineSkeleton } from "@/components/Skeletons";
import {
  EmptyState,
  ErrorState,
  PageHeader,
  SectionTitle,
  Segmented,
} from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { api } from "@/lib/api";
import { formatPercent } from "@/lib/format";

export default function AnalyticsPage() {
  const [days, setDays] = useState<number>(30);
  const analytics = useApi(() => api.getAnalytics(days), [days]);
  const data = analytics.data;
  const hasData = (data?.stats.raw_changes ?? 0) > 0;

  return (
    <div className="animate-page">
      <PageHeader
        title="Analytics"
        description="How much noise the pipeline removed, and what it kept. Every figure is counted from stored records."
        action={
          <Segmented
            label="Period"
            value={String(days)}
            onChange={(value) => setDays(Number(value))}
            options={[
              { value: "7", label: "7 days" },
              { value: "30", label: "30 days" },
              { value: "90", label: "90 days" },
            ]}
          />
        }
      />

      {analytics.loading && !data ? (
        <div className="mt-12 space-y-16">
          <MetricsSkeleton />
          <ChartSkeleton />
          <PipelineSkeleton />
        </div>
      ) : analytics.error ? (
        <ErrorState
          title="Cannot load analytics"
          message={analytics.error}
          onRetry={analytics.refetch}
        />
      ) : !data ? null : !hasData ? (
        <EmptyState
          title="No analytics yet"
          description="Analytics are computed from detected changes. Scan a tracked page twice and this page will populate."
          action={
            <Link
              href="/competitors"
              className="text-[13px] font-medium text-[var(--ink)] underline underline-offset-4"
            >
              Go to competitors
            </Link>
          }
        />
      ) : (
        <div className="mt-12 space-y-16">
          <MetricStrip
            scope="analytics"
            metrics={[
              {
                label: "Raw changes",
                value: data.stats.raw_changes,
                hint: "Every structural difference found",
              },
              {
                label: "Meaningful",
                value: data.stats.meaningful_changes,
                hint: "Survived noise filtering",
              },
              {
                label: "High impact",
                value: data.stats.high_impact_changes,
                hint: "Relevance 70 or above",
                accent:
                  data.stats.high_impact_changes > 0 ? "var(--critical)" : undefined,
              },
              {
                label: "Noise removed",
                value: data.stats.noise_reduction,
                display: (value) => formatPercent(value),
                hint: `${data.stats.noise_changes.toLocaleString()} discarded`,
              },
            ]}
          />

          <Reveal as="section">
            <SectionTitle
              title="Change volume"
              description="Daily totals. The darker portion of each bar survived filtering."
            />
            <ActivityChart data={data.timeline} />
          </Reveal>

          <div className="grid gap-16 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] lg:gap-0">
            <Reveal as="section" className="lg:pr-14">
              <SectionTitle
                title="Category distribution"
                description="What kind of competitive moves were detected."
              />
              <CategoryBars data={data.categories} />
            </Reveal>

            <Reveal as="section" index={1} className="lg:border-l lg:border-[var(--line)] lg:pl-14">
              <SectionTitle
                title="Why changes were filtered"
                description="Each rejection is attributed to a named rule."
              />
              <NoiseReasons data={data.noise_reasons} />
            </Reveal>
          </div>

          <Reveal as="section">
            <SectionTitle
              title="Severity distribution"
              description="How the meaningful changes scored."
            />
            <SeverityBar data={data.severity_distribution} />
          </Reveal>

          <Reveal as="section">
          <NoisePipeline
            scope="analytics"
            raw={data.stats.raw_changes}
            noise={data.stats.noise_changes}
            meaningful={data.stats.meaningful_changes}
            highImpact={data.stats.high_impact_changes}
            noiseReduction={data.stats.noise_reduction}
          />
          </Reveal>

          {data.top_competitors.length > 0 && (
            <Reveal as="section">
              <SectionTitle title="Most active competitors" />
              <div className="border-t border-[var(--line)]">
                {data.top_competitors.map((competitor) => (
                  <Link
                    key={competitor.competitor_id}
                    href={`/competitors/detail?id=${competitor.competitor_id}`}
                    className="flex items-baseline justify-between gap-6 border-b border-[var(--line)] py-3.5 transition-colors duration-[var(--dur-fast)] hover:bg-[var(--raised)] sm:-mx-3 sm:px-3"
                  >
                    <span className="truncate text-[13px] font-medium">
                      {competitor.name}
                    </span>
                    <span className="flex shrink-0 gap-6 text-[12.5px] text-[var(--ink-faint)]">
                      <span>
                        <span className="tabular font-medium text-[var(--ink)]">
                          {competitor.meaningful_changes}
                        </span>{" "}
                        meaningful
                      </span>
                      <span>
                        <span
                          className="tabular font-medium"
                          style={{
                            color:
                              competitor.high_impact_changes > 0
                                ? "var(--critical)"
                                : "var(--ink)",
                          }}
                        >
                          {competitor.high_impact_changes}
                        </span>{" "}
                        high impact
                      </span>
                    </span>
                  </Link>
                ))}
              </div>
            </Reveal>
          )}
        </div>
      )}
    </div>
  );
}
