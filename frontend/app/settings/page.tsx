"use client";

import { DetailRow, ErrorState, PageHeader, SectionTitle } from "@/components/ui";
import { Reveal } from "@/components/Reveal";
import { Skeleton } from "@/components/Skeletons";
import { useApi } from "@/hooks/useApi";
import { api } from "@/lib/api";
import { capitalise, formatDateTime } from "@/lib/format";

/**
 * Settings.
 *
 * Where the implementation details live. Which provider and model performed
 * the analysis matters when you are debugging a run, and not at all when you
 * are reading intelligence — so it belongs here rather than on the dashboard
 * masthead.
 *
 * Everything on this page is read-only and comes from /api/stats. Credentials
 * are never sent to the browser: the backend reports only whether a key is
 * configured, never its value.
 */
export default function SettingsPage() {
  const stats = useApi(() => api.getStats(), []);
  const data = stats.data;

  return (
    <div className="animate-page">
      <PageHeader
        title="Settings"
        description="System status for this RivalRadar instance. Configuration is read from the backend environment."
      />

      <div className="mt-12">
      {stats.error ? (
        <ErrorState
          title="Cannot reach the API"
          message={stats.error}
          onRetry={stats.refetch}
        />
      ) : stats.loading && !data ? (
        <div className="space-y-4">
          {[0, 1, 2, 3, 4].map((index) => (
            <Skeleton key={index} className="h-[14px] w-full" />
          ))}
        </div>
      ) : data ? (
        <div className="max-w-[640px] space-y-16">
          <Reveal as="section">
            <SectionTitle
              title="Analysis engine"
              description="Detection, filtering and scoring are always deterministic. A language model only writes the explanations, and never sets a score."
            />
            <dl className="divide-y divide-[var(--line)] border-t border-[var(--line)]">
              <DetailRow
                label="Analyst"
                value={data.llm_is_llm ? data.llm_label : "Deterministic rules"}
              />
              {data.llm_is_llm && <DetailRow label="Model" value={data.llm_model} mono />}
              <DetailRow
                label="API key"
                value={data.llm_configured ? "Configured" : "Not configured"}
              />
              <DetailRow
                label="Last analysis status"
                value={
                  data.llm_last_status ? (
                    <span
                      style={{
                        color:
                          data.llm_last_status === "ok"
                            ? "var(--low)"
                            : data.llm_last_status === "skipped"
                              ? "var(--ink)"
                              : "var(--high)",
                      }}
                    >
                      {capitalise(data.llm_last_status)}
                    </span>
                  ) : (
                    "No analysis run yet"
                  )
                }
              />
            </dl>
            <p className="mt-4 max-w-[62ch] text-[12.5px] leading-relaxed text-[var(--ink-faint)]">
              The API key is read from the backend environment and never leaves it. It
              is not bundled into this interface and is not returned by any endpoint.
            </p>
          </Reveal>

          <Reveal as="section" index={1}>
            <SectionTitle title="Data" />
            <dl className="divide-y divide-[var(--line)] border-t border-[var(--line)]">
              <DetailRow
                label="Tracked competitors"
                value={`${data.tracked_competitors} (${data.active_competitors} monitoring)`}
              />
              <DetailRow label="Tracked pages" value={String(data.tracked_urls)} />
              <DetailRow
                label="Snapshots stored"
                value={data.total_snapshots.toLocaleString()}
              />
              <DetailRow
                label="Changes recorded"
                value={`${data.raw_changes.toLocaleString()} raw, ${data.meaningful_changes.toLocaleString()} meaningful`}
              />
              <DetailRow
                label="Last scan"
                value={data.last_scan ? formatDateTime(data.last_scan) : "Never"}
              />
              <DetailRow
                label="Demo data"
                value={data.demo_mode ? "Enabled" : "Disabled — all records are real"}
              />
            </dl>
          </Reveal>

          <Reveal as="section" index={2}>
            <SectionTitle
              title="Appearance"
              description="The theme is stored in this browser only. Switch it with the moon or sun control at the foot of the sidebar."
            />
          </Reveal>
        </div>
      ) : null}
      </div>
    </div>
  );
}
