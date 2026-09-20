"use client";

import { ChevronLeft, ExternalLink, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { useState } from "react";

import { ActivityFeed } from "@/components/ActivityFeed";
import { ChangeDrawer } from "@/components/ChangeDrawer";
import { Figure } from "@/components/Metrics";
import { NoisePipeline } from "@/components/NoisePipeline";
import { Reveal, RevealItem } from "@/components/Reveal";
import { FeedSkeleton, PipelineSkeleton, Skeleton } from "@/components/Skeletons";
import {
  Button,
  EmptyState,
  ErrorState,
  SectionTitle,
  Spinner,
  StatusText,
} from "@/components/ui";
import { useAction, useApi } from "@/hooks/useApi";
import { api } from "@/lib/api";
import { hostOf, relativeTime, truncate } from "@/lib/format";
import type { Change } from "@/lib/types";

function CompetitorDetailPageContent() {
  const searchParams = useSearchParams();
  const id = Number(searchParams.get("id"));
  const validId = Number.isInteger(id) && id > 0;

  const competitor = useApi(() => api.getCompetitor(id), [id]);
  const changes = useApi(() => api.listChanges({ competitor_id: id, limit: 60 }), [id]);
  const allChanges = useApi(
    () => api.listChanges({ competitor_id: id, include_noise: true, limit: 500 }),
    [id],
  );

  const [newUrl, setNewUrl] = useState("");
  const [scanning, setScanning] = useState(false);
  const [selected, setSelected] = useState<Change | null>(null);

  const scan = useAction(api.scanCompetitor);
  const addUrl = useAction(api.addTrackedUrl);
  const deleteUrl = useAction(api.deleteTrackedUrl);

  async function handleScan() {
    setScanning(true);
    await scan.run(id);
    setScanning(false);
    competitor.refetch();
    changes.refetch();
    allChanges.refetch();
  }

  // A hand-edited or truncated link. Say so rather than firing a request
  // for id NaN and surfacing the backend's validation error.
  if (!validId) {
    return (
      <div className="animate-page">
        <EmptyState
          title="No competitor selected"
          description="This link is missing a competitor id. Pick one from the competitors list."
          action={
            <Link href="/competitors">
              <Button>Back to competitors</Button>
            </Link>
          }
        />
      </div>
    );
  }

  if (competitor.loading && !competitor.data) {
    return (
      <div className="space-y-8">
        <Skeleton className="h-[12px] w-32" />
        <Skeleton className="h-[26px] w-64" />
        <Skeleton className="h-[64px] w-full" />
        <FeedSkeleton rows={3} />
      </div>
    );
  }

  if (competitor.error) {
    return (
      <ErrorState
        title="Cannot load this competitor"
        message={competitor.error}
        onRetry={competitor.refetch}
      />
    );
  }
  if (!competitor.data) return null;

  const record = competitor.data;
  const pool = allChanges.data ?? [];
  const raw = pool.length;
  const noise = pool.filter((change) => change.is_noise).length;
  const highImpact = pool.filter(
    (change) => !change.is_noise && change.relevance_score >= 70,
  ).length;

  return (
    <div className="animate-page">
      <nav className="mb-6">
        <Link
          href="/competitors"
          className="inline-flex items-center gap-1 text-[12.5px] text-[var(--ink-faint)] transition-colors duration-[var(--dur-fast)] hover:text-[var(--ink)]"
        >
          <ChevronLeft size={13} strokeWidth={1.75} />
          Competitors
        </Link>
      </nav>

      <header className="mb-8 flex flex-wrap items-end justify-between gap-x-8 gap-y-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <h1>{record.name}</h1>
            <StatusText active={record.active} />
            {record.is_demo && (
              <span className="text-[11.5px] text-[var(--high)]">Demo data</span>
            )}
          </div>
          <a
            href={record.website_url}
            target="_blank"
            rel="noopener noreferrer"
            className="mono mt-1.5 inline-flex items-center gap-1 text-[11.5px] text-[var(--ink-soft)] transition-colors duration-[var(--dur-fast)] hover:text-[var(--ink)]"
          >
            {hostOf(record.website_url)}
            <ExternalLink size={11} strokeWidth={1.75} />
          </a>
        </div>

        {scanning ? (
          <Spinner label="Scanning…" />
        ) : (
          <Button onClick={handleScan}>Run scan</Button>
        )}
      </header>

      {scan.error && (
        <div className="mb-8">
          <ErrorState
            title="Scan could not complete"
            message={scan.error}
            onRetry={handleScan}
            compact
          />
        </div>
      )}

      <Reveal className="grid grid-cols-2 gap-x-8 gap-y-6 border-y border-[var(--line)] py-7 sm:grid-cols-4">
        <Figure label="Tracked pages" value={record.tracked_url_count} />
        <Figure label="Changes this week" value={record.changes_this_week} />
        <Figure
          label="High impact (7 days)"
          value={record.high_impact_this_week}
          accent={record.high_impact_this_week > 0 ? "var(--critical)" : undefined}
        />
        <Figure label="Last scan" value={relativeTime(record.last_scan)} />
      </Reveal>

      <div className="mt-16 grid gap-16 lg:grid-cols-[minmax(0,1fr)_280px] lg:gap-0">
        <Reveal as="section" className="min-w-0 lg:pr-12">
          <SectionTitle title="Activity" />
          {changes.loading && !changes.data ? (
            <FeedSkeleton rows={3} />
          ) : changes.error ? (
            <ErrorState message={changes.error} onRetry={changes.refetch} />
          ) : !changes.data?.length ? (
            <EmptyState
              title="No changes detected yet"
              description="The first scan captures a baseline snapshot. Run a second scan after the site changes and the timeline will fill in here."
              action={<Button onClick={handleScan}>Run scan</Button>}
            />
          ) : (
            <ActivityFeed
              changes={changes.data}
              onSelect={setSelected}
              showCompetitor={false}
            />
          )}
        </Reveal>

        <aside className="min-w-0 space-y-16 lg:border-l lg:border-[var(--line)] lg:pl-12">
          <Reveal>
          {allChanges.loading && !allChanges.data ? (
            <PipelineSkeleton />
          ) : (
            <NoisePipeline
              scope={`competitor-${id}`}
              raw={raw}
              noise={noise}
              meaningful={raw - noise}
              highImpact={highImpact}
              noiseReduction={raw ? Number(((noise / raw) * 100).toFixed(2)) : 0}
              compact
            />
          )}
          </Reveal>

          <Reveal as="section" index={1}>
            <SectionTitle title="Tracked pages" />
            <div className="border-t border-[var(--line)]">
              {record.tracked_urls.map((url, index) => (
                <RevealItem
                  key={url.id}
                  index={index}
                  className="flex items-start justify-between gap-2 border-b border-[var(--line)] py-4"
                >
                  <div className="min-w-0">
                    <p className="text-[12.5px] font-medium">
                      {url.label ?? url.page_type}
                    </p>
                    <p className="mono mt-0.5 truncate text-[11px] text-[var(--ink-faint)]">
                      {url.url}
                    </p>
                    <p
                      className="mt-1 text-[11px]"
                      style={{
                        color: url.last_error ? "var(--critical)" : "var(--ink-faint)",
                      }}
                    >
                      {url.last_error
                        ? truncate(url.last_error, 70)
                        : `checked ${relativeTime(url.last_checked)}`}
                    </p>
                  </div>
                  <Button
                    size="sm"
                    variant="ghost"
                    title="Stop tracking this page"
                    onClick={async () => {
                      await deleteUrl.run(url.id);
                      competitor.refetch();
                    }}
                  >
                    <Trash2 size={13} strokeWidth={1.75} />
                  </Button>
                </RevealItem>
              ))}
            </div>

            <form
              onSubmit={async (event) => {
                event.preventDefault();
                if (!newUrl.trim()) return;
                if (await addUrl.run(id, newUrl.trim())) {
                  setNewUrl("");
                  competitor.refetch();
                }
              }}
              className="mt-4 flex gap-2"
            >
              <input
                value={newUrl}
                onChange={(event) => setNewUrl(event.target.value)}
                placeholder="https://competitor.com/pricing"
                aria-label="Page URL to track"
                className="input"
              />
              <Button size="sm" type="submit" disabled={addUrl.pending} title="Track this page">
                <Plus size={13} strokeWidth={2} />
              </Button>
            </form>
            {addUrl.error && (
              <p className="mt-2 text-[12px] text-[var(--critical)]">{addUrl.error}</p>
            )}
          </Reveal>
        </aside>
      </div>

      <ChangeDrawer change={selected} onClose={() => setSelected(null)} />
    </div>
  );
}

/**
 * The page itself is a Suspense shell.
 *
 * `useSearchParams` suspends during prerender, and a statically exported page
 * has no server to fall back to — so without this boundary the build fails.
 * The record id lives in the query string rather than the path because
 * GitHub Pages serves static files only: one exported document answers every
 * id, where a `[id]` route would need one build-time file per record.
 */
export default function CompetitorDetailPage() {
  return (
    <Suspense fallback={<div className="space-y-8"><Skeleton className="h-[12px] w-32" /><Skeleton className="h-[26px] w-64" /><Skeleton className="h-[64px] w-full" /></div>}>
      <CompetitorDetailPageContent />
    </Suspense>
  );
}
