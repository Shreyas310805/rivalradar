"use client";

import { Pause, Play, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { AddCompetitorSheet } from "@/components/AddCompetitorSheet";
import { Figure } from "@/components/Metrics";
import { Reveal, RevealItem } from "@/components/Reveal";
import { CompetitorListSkeleton } from "@/components/Skeletons";
import {
  Button,
  EmptyState,
  ErrorState,
  PageHeader,
  SectionTitle,
  Spinner,
  StatusText,
} from "@/components/ui";
import { useAction, useApi } from "@/hooks/useApi";
import { api } from "@/lib/api";
import { formatPercent, hostOf, relativeTime } from "@/lib/format";
import type { ScanResponse } from "@/lib/types";

/**
 * Competitors.
 *
 * A list, not a deck of cards: name, host and the numbers on one line each,
 * separated by hairlines. Actions stay quiet until the row is hovered.
 */
export default function CompetitorsPage() {
  const competitors = useApi(() => api.listCompetitors(), []);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [scanningId, setScanningId] = useState<number | null>(null);
  const [lastScan, setLastScan] = useState<ScanResponse | null>(null);

  const scan = useAction(api.scanCompetitor);
  const toggle = useAction(api.toggleCompetitor);
  const remove = useAction(api.deleteCompetitor);

  async function handleScan(id: number) {
    setScanningId(id);
    setLastScan(null);
    const result = await scan.run(id);
    setScanningId(null);
    if (result) {
      setLastScan(result);
      competitors.refetch();
    }
  }

  async function handleDelete(id: number, name: string) {
    if (
      !window.confirm(
        `Stop tracking ${name} and delete all of its data? This cannot be undone.`,
      )
    ) {
      return;
    }
    await remove.run(id);
    competitors.refetch();
  }

  const actionError = scan.error ?? toggle.error ?? remove.error;

  return (
    <div className="animate-page">
      <PageHeader
        title="Competitors"
        description="Track whole domains or specific pages. Each scan compares against the last snapshot."
        action={<Button onClick={() => setSheetOpen(true)}>Add competitor</Button>}
      />

      {actionError && (
        <div className="mt-10">
          <ErrorState message={actionError} compact />
        </div>
      )}

      {lastScan && (
        <Reveal className="mt-10">
          <ScanSummary result={lastScan} onDismiss={() => setLastScan(null)} />
        </Reveal>
      )}

      <div className="mt-12">
      {competitors.loading && !competitors.data ? (
        <CompetitorListSkeleton />
      ) : competitors.error ? (
        <ErrorState
          title="Cannot load competitors"
          message={competitors.error}
          onRetry={competitors.refetch}
        />
      ) : !competitors.data?.length ? (
        <EmptyState
          title="No competitors tracked yet"
          description="Start by adding a competitor and RivalRadar will begin building your competitive timeline."
          action={<Button onClick={() => setSheetOpen(true)}>Add your first competitor</Button>}
        />
      ) : (
        <div className="border-t border-[var(--line)]">
          {competitors.data.map((competitor, index) => (
            <RevealItem key={competitor.id} index={index}>
            <article
              className="competitor-row flex flex-wrap items-start justify-between gap-x-8 gap-y-4 border-b border-[var(--line)] py-6 sm:-mx-4 sm:px-4"
            >
              <div className="min-w-0 flex-1">
                <Link href={`/competitors/detail?id=${competitor.id}`} className="block min-w-0">
                  <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                    <h2 className="truncate text-[15px] font-semibold tracking-[-0.013em]">
                      {competitor.name}
                    </h2>
                    <StatusText active={competitor.active} />
                    {competitor.is_demo && (
                      <span className="text-[11.5px] text-[var(--high)]">Demo data</span>
                    )}
                  </div>
                  <p className="host mono mt-1 truncate text-[11.5px] text-[var(--ink-faint)] transition-colors duration-[var(--dur-fast)]">
                    {hostOf(competitor.website_url)}
                  </p>

                  <p className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-[12.5px] text-[var(--ink-faint)]">
                    <Stat
                      label={competitor.tracked_url_count === 1 ? "page" : "pages"}
                      value={competitor.tracked_url_count}
                    />
                    <Stat label="changes this week" value={competitor.changes_this_week} />
                    <Stat
                      label="high impact"
                      value={competitor.high_impact_this_week}
                      accent={
                        competitor.high_impact_this_week > 0
                          ? "var(--critical)"
                          : undefined
                      }
                    />
                    <span>Last scan {relativeTime(competitor.last_scan)}</span>
                  </p>

                  {competitor.tracked_urls.length > 0 && (
                    <p className="mono mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-[var(--ink-faint)]">
                      {competitor.tracked_urls.slice(0, 5).map((url) => (
                        <span
                          key={url.id}
                          title={url.last_error ?? url.url}
                          style={
                            url.last_error ? { color: "var(--critical)" } : undefined
                          }
                        >
                          {url.label ?? url.page_type}
                        </span>
                      ))}
                      {competitor.tracked_urls.length > 5 && (
                        <span>+{competitor.tracked_urls.length - 5}</span>
                      )}
                    </p>
                  )}
                </Link>
              </div>

              <div className="flex shrink-0 items-center gap-1.5">
                {scanningId === competitor.id ? (
                  <Spinner label="Scanning…" />
                ) : (
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => handleScan(competitor.id)}
                  >
                    Run scan
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="ghost"
                  title={competitor.active ? "Pause monitoring" : "Resume monitoring"}
                  onClick={async () => {
                    await toggle.run(competitor.id, !competitor.active);
                    competitors.refetch();
                  }}
                >
                  {competitor.active ? (
                    <Pause size={13} strokeWidth={1.75} />
                  ) : (
                    <Play size={13} strokeWidth={1.75} />
                  )}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  title="Delete competitor"
                  onClick={() => handleDelete(competitor.id, competitor.name)}
                >
                  <Trash2 size={13} strokeWidth={1.75} />
                </Button>
              </div>
            </article>
            </RevealItem>
          ))}
        </div>
      )}
      </div>

      <AddCompetitorSheet
        open={sheetOpen}
        onClose={() => setSheetOpen(false)}
        onCreated={() => {
          setSheetOpen(false);
          competitors.refetch();
        }}
      />
    </div>
  );
}

function Stat({
  label,
  value,
  accent,
}: {
  label: string;
  value: number;
  accent?: string;
}) {
  return (
    <span>
      <span
        className="tabular font-medium text-[var(--ink)]"
        style={accent ? { color: accent } : undefined}
      >
        {value}
      </span>{" "}
      {label}
    </span>
  );
}

function ScanSummary({
  result,
  onDismiss,
}: {
  result: ScanResponse;
  onDismiss: () => void;
}) {
  const { stats } = result;
  return (
    <section className="border-y border-[var(--line)] py-6">
      <SectionTitle
        title={`Scan complete · ${result.competitor_name}`}
        description={`${result.urls_scanned} page(s) scanned, ${result.urls_failed} failed.`}
        action={
          <Button size="sm" variant="ghost" onClick={onDismiss}>
            Dismiss
          </Button>
        }
      />
      <div className="grid grid-cols-2 gap-x-8 gap-y-5 sm:grid-cols-5">
        <Figure label="Raw" value={stats.raw_changes} />
        <Figure label="Noise" value={stats.noise_changes} />
        <Figure label="Meaningful" value={stats.meaningful_changes} />
        <Figure label="High impact" value={stats.high_impact_changes} />
        <Figure label="Noise removed" value={formatPercent(stats.noise_reduction)} />
      </div>

      {result.results.length > 0 && (
        <ul className="mt-6 space-y-1 border-t border-[var(--line)] pt-4">
          {result.results.map((item) => (
            <li key={item.url} className="mono text-[11px] text-[var(--ink-faint)]">
              <span
                style={{
                  color: item.status === "failed" ? "var(--critical)" : "var(--low)",
                }}
              >
                {item.status}
              </span>{" "}
              {item.url}
              {item.message ? ` — ${item.message}` : ""}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
