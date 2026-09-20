"use client";

import Link from "next/link";
import { useState } from "react";

import { ActivityFeed } from "@/components/ActivityFeed";
import { ChangeDrawer } from "@/components/ChangeDrawer";
import { MetricStrip } from "@/components/Metrics";
import { NoisePipeline } from "@/components/NoisePipeline";
import { Section } from "@/components/PageChrome";
import { LlmStatusNotice } from "@/components/Provenance";
import { RevealItem } from "@/components/Reveal";
import {
  FeedSkeleton,
  MetricsSkeleton,
  PipelineSkeleton,
  Skeleton,
} from "@/components/Skeletons";
import { Button, EmptyState, ErrorState, PageHeader, SectionTitle } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { api } from "@/lib/api";
import { formatPercent, hostOf, relativeTime } from "@/lib/format";
import type { Change } from "@/lib/types";

export default function DashboardPage() {
  const stats = useApi(() => api.getStats(), []);
  const changes = useApi(() => api.listChanges({ limit: 12 }), []);
  const competitors = useApi(() => api.listCompetitors(), []);
  const [selected, setSelected] = useState<Change | null>(null);

  const data = stats.data;
  const hasCompetitors = (competitors.data?.length ?? 0) > 0;

  // One short line of status, echoed into the contextual bar once the
  // masthead scrolls away. Which provider and model ran is an implementation
  // detail and lives in Settings.
  const status = data
    ? `Last scan ${relativeTime(data.last_scan)}${
        data.active_competitors > 0 ? " · Monitoring active" : ""
      }`
    : undefined;

  return (
    <div className="animate-page">
      <PageHeader
        title="Competitive intelligence"
        description="See what changed. Understand what matters."
        meta={status}
        action={
          stats.loading && !data ? (
            <Skeleton className="h-[14px] w-44" />
          ) : data ? (
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12.5px]">
              <span className="text-[var(--ink-soft)]">
                Last scan {relativeTime(data.last_scan)}
              </span>
              {data.active_competitors > 0 && (
                <>
                  <span className="h-3 w-px bg-[var(--line)]" aria-hidden />
                  <span className="inline-flex items-center gap-1.5 text-[var(--ink-faint)]">
                    <span
                      className="h-[5px] w-[5px] rounded-full bg-[var(--low)]"
                      aria-hidden
                    />
                    Monitoring active
                  </span>
                </>
              )}
            </div>
          ) : undefined
        }
      />

      {stats.error ? (
        <div className="mt-12">
          <ErrorState
            title="Cannot reach the API"
            message={stats.error}
            onRetry={stats.refetch}
          />
        </div>
      ) : (
        <>
          {data?.llm_last_status && (
            <div className="mt-10">
              <LlmStatusNotice status={data.llm_last_status} />
            </div>
          )}

          {/* The metric band steps back once the reader has moved down to the
              feed, so the thing they are reading is the thing in focus. */}
          <Section id="overview" label="Overview" className="mt-12" recede>
            {stats.loading && !data ? (
              <MetricsSkeleton />
            ) : data ? (
              <MetricStrip
                scope="dashboard"
                metrics={[
                  {
                    label: "Tracked competitors",
                    value: data.tracked_competitors,
                    hint: `${data.active_competitors} monitoring, ${data.tracked_urls} pages`,
                  },
                  {
                    label: "Meaningful changes",
                    value: data.meaningful_changes,
                    hint: `${data.changes_this_week} in the last 7 days`,
                  },
                  {
                    label: "High impact",
                    value: data.high_impact_changes,
                    hint: `${data.high_impact_this_week} in the last 7 days`,
                    accent: data.high_impact_changes > 0 ? "var(--critical)" : undefined,
                  },
                  {
                    label: "Noise removed",
                    value: data.noise_reduction,
                    display: (value) => formatPercent(value),
                    hint: `${data.noise_changes.toLocaleString()} of ${data.raw_changes.toLocaleString()} discarded`,
                  },
                ]}
              />
            ) : null}
          </Section>

          {/* Main column and a narrower intelligence rail, separated by a
              hairline rather than boxed into two cards. */}
          <div className="mt-16 grid gap-16 lg:grid-cols-[minmax(0,1fr)_280px] lg:gap-0">
            <Section id="activity" label="Activity" className="min-w-0 lg:pr-12">
              <SectionTitle
                title="Recent activity"
                action={
                  changes.data?.length ? (
                    <Link
                      href="/changes"
                      className="text-[12.5px] text-[var(--ink-soft)] transition-colors duration-[var(--dur-fast)] hover:text-[var(--ink)]"
                    >
                      All changes
                    </Link>
                  ) : undefined
                }
              />

              {changes.loading && !changes.data ? (
                <FeedSkeleton />
              ) : changes.error ? (
                <ErrorState message={changes.error} onRetry={changes.refetch} />
              ) : !changes.data?.length ? (
                <EmptyState
                  title={
                    hasCompetitors
                      ? "No competitive intelligence yet"
                      : "No competitors tracked yet"
                  }
                  description={
                    hasCompetitors
                      ? "The first scan of a page stores a baseline. Run a second scan and RivalRadar will report what moved between them."
                      : "Start by adding a competitor and RivalRadar will begin building your competitive timeline."
                  }
                  action={
                    <Link href="/competitors">
                      <Button>
                        {hasCompetitors ? "Go to competitors" : "Add competitor"}
                      </Button>
                    </Link>
                  }
                />
              ) : (
                <ActivityFeed changes={changes.data} onSelect={setSelected} />
              )}
            </Section>

            <aside className="min-w-0 space-y-16 lg:border-l lg:border-[var(--line)] lg:pl-12">
              <Section id="signals" label="Signals">
                {stats.loading && !data ? (
                  <PipelineSkeleton />
                ) : data ? (
                  <NoisePipeline
                    scope="dashboard"
                    raw={data.raw_changes}
                    noise={data.noise_changes}
                    meaningful={data.meaningful_changes}
                    highImpact={data.high_impact_changes}
                    noiseReduction={data.noise_reduction}
                    compact
                  />
                ) : null}
              </Section>

              <Section id="watchlist" label="Watchlist">
                <SectionTitle
                  title="Watchlist"
                  action={
                    hasCompetitors ? (
                      <Link
                        href="/competitors"
                        className="text-[12.5px] text-[var(--ink-soft)] transition-colors duration-[var(--dur-fast)] hover:text-[var(--ink)]"
                      >
                        Manage
                      </Link>
                    ) : undefined
                  }
                />
                {competitors.loading && !competitors.data ? (
                  <div>
                    {[0, 1].map((index) => (
                      <div key={index} className="border-b border-[var(--line)] py-4">
                        <Skeleton className="h-[12px] w-28" />
                        <Skeleton className="mt-2 h-[10px] w-20" />
                      </div>
                    ))}
                  </div>
                ) : !hasCompetitors ? (
                  <EmptyState
                    compact
                    title="Nothing tracked"
                    description="Track any public URL. A pricing page is the highest-signal place to start."
                    action={
                      <Link href="/competitors">
                        <Button size="sm">Add competitor</Button>
                      </Link>
                    }
                  />
                ) : (
                  <div>
                    {competitors.data!.map((competitor, index) => (
                      <RevealItem key={competitor.id} index={index}>
                        <Link
                          href={`/competitors/detail?id=${competitor.id}`}
                          className="group flex items-baseline justify-between gap-4 border-b border-[var(--line)] py-4 transition-colors duration-[var(--dur-fast)] hover:border-[var(--line-strong)] hover:bg-[var(--raised)]"
                        >
                          <span className="min-w-0">
                            <span className="block truncate text-[13px] font-medium">
                              {competitor.name}
                            </span>
                            <span className="mono block truncate text-[11px] text-[var(--ink-faint)] transition-colors duration-[var(--dur-fast)] group-hover:text-[var(--ink-soft)]">
                              {hostOf(competitor.website_url)}
                            </span>
                          </span>
                          <span className="shrink-0 text-right">
                            <span className="tabular block text-[13px] font-medium text-[var(--ink-soft)] transition-colors duration-[var(--dur-fast)] group-hover:text-[var(--ink)]">
                              {competitor.changes_this_week}
                            </span>
                            <span className="block text-[11px] text-[var(--ink-faint)]">
                              7d
                            </span>
                          </span>
                        </Link>
                      </RevealItem>
                    ))}
                  </div>
                )}
              </Section>
            </aside>
          </div>
        </>
      )}

      <ChangeDrawer change={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
