"use client";

import { ChevronLeft, ExternalLink } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense } from "react";

import { ChangeComparison } from "@/components/DiffView";
import { AnalysisSource } from "@/components/Provenance";
import { Draw, Reveal } from "@/components/Reveal";
import { Skeleton } from "@/components/Skeletons";
import {
  Button,
  ContextLine,
  DetailRow,
  EmptyState,
  ErrorState,
  Meter,
  SectionTitle,
  SeverityText,
} from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { api } from "@/lib/api";
import { capitalise, formatDateTime, severityColor } from "@/lib/format";

/**
 * Full change view.
 *
 * The drawer handles the common case; this page exists for deep links,
 * sharing, and reading a long diff with the whole width available.
 */
function ChangeDetailPageContent() {
  const searchParams = useSearchParams();
  const id = Number(searchParams.get("id"));
  const validId = Number.isInteger(id) && id > 0;
  const change = useApi(() => api.getChange(id), [id]);

  // A hand-edited or truncated link. Say so rather than firing a request
  // for id NaN and surfacing the backend's validation error.
  if (!validId) {
    return (
      <div className="animate-page">
        <EmptyState
          title="No change selected"
          description="This link is missing a change id. Open a change from the activity feed."
          action={
            <Link href="/changes">
              <Button>Back to changes</Button>
            </Link>
          }
        />
      </div>
    );
  }

  if (change.loading && !change.data) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-[12px] w-48" />
        <Skeleton className="h-[26px] w-2/3" />
        <Skeleton className="h-[110px] w-full" />
        <Skeleton className="h-[180px] w-full" />
      </div>
    );
  }

  if (change.error) {
    return (
      <ErrorState
        title="Cannot load this change"
        message={change.error}
        onRetry={change.refetch}
      />
    );
  }
  if (!change.data) return null;

  const record = change.data;
  const intel = record.intelligence;

  return (
    <div className="animate-page">
      <nav className="mb-6 flex flex-wrap items-center gap-1.5 text-[12.5px] text-[var(--ink-faint)]">
        <Link
          href="/changes"
          className="inline-flex items-center gap-1 transition-colors duration-[var(--dur-fast)] hover:text-[var(--ink)]"
        >
          <ChevronLeft size={13} strokeWidth={1.75} />
          Changes
        </Link>
        <span aria-hidden>/</span>
        <Link
          href={`/competitors/detail?id=${record.competitor_id}`}
          className="transition-colors duration-[var(--dur-fast)] hover:text-[var(--ink)]"
        >
          {record.competitor_name}
        </Link>
        <span aria-hidden>/</span>
        <span className="text-[var(--ink-soft)]">Change #{record.id}</span>
      </nav>

      <header className="mb-10">
        <ContextLine category={record.category} competitor={record.competitor_name} />
        <h1 className="mt-2.5 max-w-[42ch] text-[24px] font-semibold leading-[1.28] tracking-[-0.024em]">
          {intel?.title ?? `Content changed in ${record.location}`}
        </h1>
        {intel?.summary && (
          <p className="mt-3 max-w-[64ch] text-[14.5px] leading-relaxed text-[var(--ink-soft)]">
            {intel.summary}
          </p>
        )}

        <div className="mt-4 flex flex-wrap items-baseline gap-x-5 gap-y-1.5">
          <SeverityText severity={record.severity} score={record.relevance_score} />
          <span className="text-[11.5px] text-[var(--ink-faint)]">
            {formatDateTime(record.detected_at)}
          </span>
          <span className="text-[11.5px] text-[var(--ink-faint)]">
            {capitalise(record.change_type)}
          </span>
          {intel && <AnalysisSource status={intel.llm_status} model={intel.llm_model} />}
          {record.is_noise && (
            <span className="text-[11.5px] text-[var(--ink-faint)]">
              Filtered as noise
            </span>
          )}
        </div>
      </header>

      <Reveal as="section" className="mb-16">
        <SectionTitle
          title="What changed"
          description="Word-level differences between the previous and current snapshot."
        />
        <ChangeComparison
          before={record.before}
          after={record.after}
          segments={record.diff_segments}
        />
        <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2">
          <a
            href={record.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 text-[12.5px] font-medium text-[var(--ink-soft)] transition-colors duration-[var(--dur-fast)] hover:text-[var(--ink)]"
          >
            View source
            <ExternalLink size={12} strokeWidth={1.75} />
          </a>
          <span className="mono text-[11.5px] text-[var(--ink-faint)]">
            Snapshot #{record.previous_snapshot_id ?? "?"} → #{record.snapshot_id}
          </span>
        </div>
      </Reveal>

      <div className="grid gap-12 lg:grid-cols-[minmax(0,1fr)_300px] lg:gap-0">
        <Reveal className="min-w-0 space-y-12 lg:pr-12">
          {intel?.business_impact && (
            <section>
              <SectionTitle title="Why it matters" />
              <p className="max-w-[64ch] text-[14px] leading-relaxed">
                {intel.business_impact}
              </p>
              {intel.recommended_action && (
                <>
                  <h3 className="eyebrow mb-2 mt-6">Recommended action</h3>
                  <p className="max-w-[64ch] text-[13px] leading-relaxed text-[var(--ink-soft)]">
                    {intel.recommended_action}
                  </p>
                </>
              )}
            </section>
          )}

          {intel && intel.llm_status !== "ok" && intel.llm_status !== "skipped" && (
            <section className="border-l-2 border-[var(--high)] py-1 pl-4">
              <p className="text-[13.5px] font-medium">AI analysis was unavailable</p>
              <p className="mt-1 max-w-[64ch] text-[13px] leading-relaxed text-[var(--ink-soft)]">
                This write-up was produced by the deterministic rules, not a language
                model. Detection, classification and scoring are unaffected.
              </p>
            </section>
          )}

          {record.is_noise && record.noise_reason && (
            <section>
              <SectionTitle title="Why this was filtered out" />
              <p className="mono text-[12.5px] text-[var(--ink-soft)]">
                {record.noise_reason}
              </p>
              <p className="mt-2 max-w-[64ch] text-[12.5px] leading-relaxed text-[var(--ink-faint)]">
                Discarded changes are kept so the noise-reduction metric stays
                auditable.
              </p>
            </section>
          )}
        </Reveal>

        <Reveal as="aside" index={1} className="min-w-0 space-y-12 lg:border-l lg:border-[var(--line)] lg:pl-12">
          <section>
            <SectionTitle title="Scoring" />
            <Draw className="space-y-4">
              <ScoreRow
                label="Relevance"
                value={record.relevance_score}
                display={`${Math.round(record.relevance_score)}/100`}
                color={severityColor(record.severity)}
              />
              {intel && (
                <ScoreRow
                  label="Analyst confidence"
                  value={intel.confidence * 100}
                  display={`${Math.round(intel.confidence * 100)}%`}
                  color="var(--accent)"
                />
              )}
              <ScoreRow
                label="Classifier confidence"
                value={record.classifier_confidence * 100}
                display={`${Math.round(record.classifier_confidence * 100)}%`}
                color="var(--ink-faint)"
              />
              <ScoreRow
                label="Change magnitude"
                value={record.magnitude * 100}
                display={record.magnitude.toFixed(2)}
                color="var(--ink-faint)"
              />
            </Draw>
          </section>

          <section>
            <SectionTitle title="Detection" />
            <dl className="divide-y divide-[var(--line)] border-t border-[var(--line)]">
              <DetailRow label="Competitor" value={record.competitor_name} />
              <DetailRow label="Page section" value={capitalise(record.location)} />
              <DetailRow label="Detected" value={formatDateTime(record.detected_at)} />
              {intel && <DetailRow label="Analysed by" value={intel.analysed_by} mono />}
              {intel?.llm_model && <DetailRow label="Model" value={intel.llm_model} mono />}
            </dl>
            <p className="mt-3">
              <a
                href={record.source_url}
                target="_blank"
                rel="noopener noreferrer"
                className="mono break-all text-[11px] text-[var(--ink-soft)] transition-colors duration-[var(--dur-fast)] hover:text-[var(--ink)]"
              >
                {record.source_url}
              </a>
            </p>
          </section>
        </Reveal>
      </div>
    </div>
  );
}

function ScoreRow({
  label,
  value,
  display,
  color,
}: {
  label: string;
  value: number;
  display: string;
  color: string;
}) {
  return (
    <div>
      <div className="flex items-baseline justify-between text-[12.5px]">
        <span className="text-[var(--ink-soft)]">{label}</span>
        <span className="tabular font-medium">{display}</span>
      </div>
      <div className="mt-2">
        <Meter value={value} color={color} ariaLabel={`${label}: ${display}`} />
      </div>
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
export default function ChangeDetailPage() {
  return (
    <Suspense fallback={<div className="space-y-6"><Skeleton className="h-[12px] w-48" /><Skeleton className="h-[26px] w-2/3" /><Skeleton className="h-[110px] w-full" /></div>}>
      <ChangeDetailPageContent />
    </Suspense>
  );
}
