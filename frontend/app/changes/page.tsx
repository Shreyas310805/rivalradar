"use client";

import Link from "next/link";
import { useState } from "react";

import { ActivityFeed } from "@/components/ActivityFeed";
import { Reveal } from "@/components/Reveal";
import { ChangeDrawer } from "@/components/ChangeDrawer";
import { FeedSkeleton } from "@/components/Skeletons";
import { Button, EmptyState, ErrorState, PageHeader, Segmented } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { api } from "@/lib/api";
import { categoryLabel } from "@/lib/format";
import type { Change } from "@/lib/types";

const CATEGORIES = [
  "pricing",
  "features",
  "product",
  "hiring",
  "integrations",
  "messaging",
  "other",
] as const;

/**
 * All detected changes, with the filters that matter operationally:
 * category, relevance floor, and whether to reveal what was filtered out.
 *
 * The filter bar is a row of text with an underlined selection — no tray, no
 * pills — so it reads as part of the page rather than a control panel on top
 * of it.
 */
export default function ChangesPage() {
  const [category, setCategory] = useState<string>("");
  const [minScore, setMinScore] = useState<number>(0);
  const [includeNoise, setIncludeNoise] = useState(false);
  const [selected, setSelected] = useState<Change | null>(null);

  const changes = useApi(
    () =>
      api.listChanges({
        limit: 120,
        category: category || undefined,
        min_score: minScore || undefined,
        include_noise: includeNoise,
      }),
    [category, minScore, includeNoise],
  );

  const filtered = Boolean(category || minScore);

  return (
    <div className="animate-page">
      <PageHeader
        title="Changes"
        description="Every difference RivalRadar detected across your tracked pages."
      />

      <Reveal className="mt-12 flex flex-wrap items-baseline gap-x-10 gap-y-4 border-y border-[var(--line)] py-4">
        <Segmented
          label="Category"
          value={category}
          onChange={setCategory}
          options={[
            { value: "", label: "All" },
            ...CATEGORIES.map((item) => ({
              value: item,
              label: categoryLabel(item),
            })),
          ]}
        />
        <Segmented
          label="Relevance"
          value={String(minScore)}
          onChange={(value) => setMinScore(Number(value))}
          options={[
            { value: "0", label: "Any" },
            { value: "50", label: "50+" },
            { value: "70", label: "High" },
            { value: "85", label: "Critical" },
          ]}
        />
        <label className="flex cursor-pointer items-center gap-2 text-[12.5px] text-[var(--ink-soft)]">
          <input
            type="checkbox"
            checked={includeNoise}
            onChange={(event) => setIncludeNoise(event.target.checked)}
            className="h-[13px] w-[13px] accent-[var(--ink)]"
          />
          Show filtered noise
        </label>
      </Reveal>

      <div className="mt-10">
        {changes.loading && !changes.data ? (
          <FeedSkeleton rows={6} />
        ) : changes.error ? (
          <ErrorState
            title="Cannot load changes"
            message={changes.error}
            onRetry={changes.refetch}
          />
        ) : !changes.data?.length ? (
          <EmptyState
            title={
              filtered || !includeNoise
                ? "Nothing matches these filters"
                : "No changes detected yet"
            }
            description={
              filtered
                ? "Try widening the filters, or turn on “Show filtered noise” to see what the pipeline discarded and why."
                : "Scan a tracked page twice — once for the baseline, once to detect what moved."
            }
            action={
              filtered ? (
                <Button
                  variant="secondary"
                  onClick={() => {
                    setCategory("");
                    setMinScore(0);
                  }}
                >
                  Clear filters
                </Button>
              ) : (
                <Link href="/competitors">
                  <Button>Go to competitors</Button>
                </Link>
              )
            }
          />
        ) : (
          <>
            <p className="mb-2 text-[12.5px] text-[var(--ink-faint)]">
              {changes.data.length} change{changes.data.length === 1 ? "" : "s"}
              {includeNoise ? ", including filtered noise" : ""}
            </p>
            <ActivityFeed changes={changes.data} onSelect={setSelected} />
          </>
        )}
      </div>

      <ChangeDrawer change={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
