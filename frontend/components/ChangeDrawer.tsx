"use client";

import { ExternalLink, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { useApi } from "@/hooks/useApi";
import { api } from "@/lib/api";
import { capitalise, formatDateTime, severityColor } from "@/lib/format";
import { MOTION } from "@/lib/motion";
import type { Change } from "@/lib/types";

import { ChangeComparison } from "./DiffView";
import { Draw } from "./Reveal";
import { AnalysisSource } from "./Provenance";
import { SlideOver } from "./SlideOver";
import { ContextLine, DetailRow, ErrorState, Meter, SeverityText } from "./ui";
import { DrawerSkeleton } from "./Skeletons";

/**
 * Change detail drawer.
 *
 * Opening a change should not cost the user their place in the feed, so the
 * detail slides in over it. The full page at /changes/[id] still exists for
 * deep links and sharing — the drawer links to it rather than replacing it.
 *
 * The record is held locally so it survives the closing transition: without
 * that, the panel would empty out and then slide away, which reads as a bug.
 */
export function ChangeDrawer({
  change,
  onClose,
}: {
  change: Change | null;
  onClose: () => void;
}) {
  const [held, setHeld] = useState<Change | null>(change);

  useEffect(() => {
    if (change) {
      setHeld(change);
      return;
    }
    const timer = window.setTimeout(() => setHeld(null), MOTION.overlay);
    return () => window.clearTimeout(timer);
  }, [change]);

  // The list already holds a Change, but the drawer refetches by id because
  // only the detail endpoint returns `diff_segments`.
  const detail = useApi(
    () => (change ? api.getChange(change.id) : Promise.resolve(null)),
    [change?.id],
  );

  const record = (change ? detail.data : null) ?? held;

  return (
    <SlideOver
      open={change !== null}
      onClose={onClose}
      label="Change details"
      className="w-full max-w-[540px]"
    >
      {record && (
        <Body
          record={record}
          loading={detail.loading && !detail.data}
          error={detail.error}
          onRetry={detail.refetch}
          onClose={onClose}
        />
      )}
    </SlideOver>
  );
}

function Body({
  record,
  loading,
  error,
  onRetry,
  onClose,
}: {
  record: Change;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  onClose: () => void;
}) {
  const intel = record.intelligence;

  return (
    <>
      <div className="flex shrink-0 items-start justify-between gap-4 border-b border-[var(--line)] px-7 py-5">
        <div className="min-w-0">
          <ContextLine category={record.category} competitor={record.competitor_name} />
          <h2 className="mt-2 text-[15.5px] font-semibold leading-snug tracking-[-0.014em]">
            {intel?.title ?? `Content changed in ${record.location}`}
          </h2>
          <div className="mt-2.5 flex flex-wrap items-baseline gap-x-4 gap-y-1">
            <SeverityText severity={record.severity} score={record.relevance_score} />
            <span className="text-[11.5px] text-[var(--ink-faint)]">
              {formatDateTime(record.detected_at)}
            </span>
          </div>
        </div>
        <button
          onClick={onClose}
          aria-label="Close"
          className="shrink-0 rounded-[var(--radius-xs)] p-1.5 text-[var(--ink-faint)] transition-colors duration-[var(--dur-fast)] hover:bg-[var(--raised)] hover:text-[var(--ink)] active:scale-[0.94]"
        >
          <X size={15} strokeWidth={1.75} />
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-7 py-7">
        {loading ? (
          <DrawerSkeleton />
        ) : error ? (
          <ErrorState
            title="Could not load this change"
            message={error}
            onRetry={onRetry}
            compact
          />
        ) : (
          <div className="space-y-10">
            {intel?.summary && (
              <div>
                <p className="max-w-[58ch] text-[13.5px] leading-relaxed">
                  {intel.summary}
                </p>
                <p className="mt-2.5">
                  <AnalysisSource status={intel.llm_status} model={intel.llm_model} />
                </p>
              </div>
            )}

            <section>
              <h3 className="eyebrow mb-4">What changed</h3>
              <ChangeComparison
                before={record.before}
                after={record.after}
                segments={record.diff_segments ?? []}
              />
            </section>

            {intel?.business_impact && (
              <section>
                <h3 className="eyebrow mb-4">Why it matters</h3>
                <p className="max-w-[58ch] text-[13px] leading-relaxed">
                  {intel.business_impact}
                </p>
                {intel.recommended_action && (
                  <>
                    <h3 className="eyebrow mb-2.5 mt-6">Recommended action</h3>
                    <p className="max-w-[58ch] text-[13px] leading-relaxed text-[var(--ink-soft)]">
                      {intel.recommended_action}
                    </p>
                  </>
                )}
              </section>
            )}

            {intel && intel.llm_status !== "ok" && intel.llm_status !== "skipped" && (
              <section className="border-l-2 border-[var(--high)] py-1 pl-4">
                <p className="text-[12.5px] leading-relaxed text-[var(--ink-soft)]">
                  This write-up came from the deterministic rules, not a language
                  model. Detection, classification and scoring are unaffected.
                </p>
              </section>
            )}

            {record.is_noise && record.noise_reason && (
              <section>
                <h3 className="eyebrow mb-2.5">Filtered out because</h3>
                <p className="mono text-[12px] text-[var(--ink-soft)]">
                  {record.noise_reason}
                </p>
              </section>
            )}

            <section>
              <h3 className="eyebrow mb-5">Scoring</h3>
              <Draw className="space-y-4">
                <ScoreRow
                  label="Relevance"
                  value={record.relevance_score}
                  display={`${Math.round(record.relevance_score)}/100`}
                  color={severityColor(record.severity)}
                  delay={0}
                />
                {intel && (
                  <ScoreRow
                    label="Analyst confidence"
                    value={intel.confidence * 100}
                    display={`${Math.round(intel.confidence * 100)}%`}
                    color="var(--accent)"
                    delay={70}
                  />
                )}
                <ScoreRow
                  label="Classifier confidence"
                  value={record.classifier_confidence * 100}
                  display={`${Math.round(record.classifier_confidence * 100)}%`}
                  color="var(--ink-faint)"
                  delay={140}
                />
                <ScoreRow
                  label="Change magnitude"
                  value={record.magnitude * 100}
                  display={record.magnitude.toFixed(2)}
                  color="var(--ink-faint)"
                  delay={210}
                />
              </Draw>
            </section>

            <section>
              <h3 className="eyebrow mb-2">Detection</h3>
              <dl className="divide-y divide-[var(--line)]">
                <DetailRow label="Competitor" value={record.competitor_name} />
                <DetailRow label="Page section" value={capitalise(record.location)} />
                <DetailRow label="Change type" value={capitalise(record.change_type)} />
                <DetailRow label="Detected" value={formatDateTime(record.detected_at)} />
                {intel && <DetailRow label="Analysed by" value={intel.analysed_by} mono />}
                {intel?.llm_model && (
                  <DetailRow label="Model" value={intel.llm_model} mono />
                )}
                <DetailRow
                  label="Snapshots"
                  value={`#${record.previous_snapshot_id ?? "?"} → #${record.snapshot_id}`}
                  mono
                />
              </dl>
            </section>
          </div>
        )}
      </div>

      <div className="flex shrink-0 items-center gap-5 border-t border-[var(--line)] px-7 py-4">
        <a
          href={record.source_url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1.5 text-[12.5px] font-medium text-[var(--ink-soft)] transition-colors duration-[var(--dur-fast)] hover:text-[var(--ink)]"
        >
          View source
          <ExternalLink size={12} strokeWidth={1.75} />
        </a>
        <Link
          href={`/changes/detail?id=${record.id}`}
          className="text-[12.5px] font-medium text-[var(--ink-soft)] transition-colors duration-[var(--dur-fast)] hover:text-[var(--ink)]"
        >
          Full comparison
        </Link>
      </div>
    </>
  );
}

function ScoreRow({
  label,
  value,
  display,
  color,
  delay,
}: {
  label: string;
  value: number;
  display: string;
  color: string;
  delay: number;
}) {
  return (
    <div>
      <div className="flex items-baseline justify-between text-[12.5px]">
        <span className="text-[var(--ink-soft)]">{label}</span>
        <span className="tabular font-medium">{display}</span>
      </div>
      <div className="mt-2">
        <Meter
          value={value}
          color={color}
          delay={delay}
          ariaLabel={`${label}: ${display}`}
        />
      </div>
    </div>
  );
}
