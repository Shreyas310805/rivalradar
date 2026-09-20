"use client";

import { ArrowLeft, Plus, X } from "lucide-react";
import { useEffect, useState } from "react";

import { useAction } from "@/hooks/useApi";
import { api } from "@/lib/api";
import { hostOf } from "@/lib/format";

import { SlideOver } from "./SlideOver";
import { Button, ErrorState } from "./ui";

/**
 * Add-competitor flow.
 *
 * Three input steps plus a review, rather than one long form: each screen asks
 * one thing, so the URL field is never competing with a list of pages for
 * attention. Progress is a single hairline that fills — four segmented pills
 * would be four more shapes for information one sentence already carries.
 */

type Step = 0 | 1 | 2 | 3;

const STEPS = ["Name", "Website", "Pages", "Review"] as const;

export function AddCompetitorSheet({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}) {
  const [step, setStep] = useState<Step>(0);
  const [name, setName] = useState("");
  const [website, setWebsite] = useState("");
  const [frequency, setFrequency] = useState("daily");
  const [pages, setPages] = useState<string[]>([""]);

  const create = useAction(api.createCompetitor);

  useEffect(() => {
    if (!open) return;
    setStep(0);
    setName("");
    setWebsite("");
    setFrequency("daily");
    setPages([""]);
    create.clearError();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const trackedPages = pages.map((page) => page.trim()).filter(Boolean);
  const canAdvance =
    (step === 0 && name.trim().length > 0) ||
    (step === 1 && website.trim().length > 0) ||
    step === 2 ||
    step === 3;

  async function submit() {
    const created = await create.run({
      name: name.trim(),
      website_url: website.trim(),
      tracking_frequency: frequency,
      tracked_urls: trackedPages.length
        ? trackedPages.map((url) => ({ url }))
        : undefined,
    });
    if (created) onCreated();
  }

  function next() {
    if (step === 3) {
      void submit();
    } else {
      setStep((step + 1) as Step);
    }
  }

  return (
    <SlideOver
      open={open}
      onClose={onClose}
      label="Add competitor"
      className="w-full max-w-[440px]"
    >
      <>
        {/* Header + progress */}
        <div className="shrink-0 border-b border-[var(--line)] px-7 py-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-[15px] font-semibold tracking-[-0.014em]">
                Add competitor
              </h2>
              <p className="mt-1 text-[12.5px] text-[var(--ink-faint)]">
                Step {step + 1} of 4 &middot; {STEPS[step]}
              </p>
            </div>
            <button
              onClick={onClose}
              aria-label="Close"
              className="rounded-[var(--radius-xs)] p-1.5 text-[var(--ink-faint)] transition-colors duration-[var(--dur-fast)] hover:bg-[var(--raised)] hover:text-[var(--ink)] active:scale-[0.94]"
            >
              <X size={15} strokeWidth={1.75} />
            </button>
          </div>

          <div
            className="mt-4 h-[2px] w-full bg-[var(--line)]"
            role="progressbar"
            aria-valuenow={step + 1}
            aria-valuemin={1}
            aria-valuemax={4}
            aria-label="Progress"
          >
            <div
              className="h-full bg-[var(--ink)] transition-[width] duration-[var(--dur-slow)] [transition-timing-function:var(--ease)]"
              style={{ width: `${((step + 1) / 4) * 100}%` }}
            />
          </div>
        </div>

        {/* Steps */}
        <div className="min-h-0 flex-1 overflow-y-auto px-7 py-8">
          <div key={step} className="animate-rise">
            {step === 0 && (
              <Field
                label="Competitor name"
                hint="However you refer to them internally."
              >
                <input
                  autoFocus
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  onKeyDown={(event) => event.key === "Enter" && canAdvance && next()}
                  placeholder="Acme Analytics"
                  maxLength={200}
                  className="input"
                />
              </Field>
            )}

            {step === 1 && (
              <>
                <Field
                  label="Website URL"
                  hint="Any public http(s) address. This page is tracked by default."
                >
                  <input
                    autoFocus
                    value={website}
                    onChange={(event) => setWebsite(event.target.value)}
                    onKeyDown={(event) => event.key === "Enter" && canAdvance && next()}
                    placeholder="https://acme.com/pricing"
                    className="input"
                  />
                </Field>
                <Field label="Scan frequency" hint="How often a scheduled scan runs.">
                  <select
                    value={frequency}
                    onChange={(event) => setFrequency(event.target.value)}
                    className="input"
                  >
                    <option value="hourly">Hourly</option>
                    <option value="daily">Daily</option>
                    <option value="weekly">Weekly</option>
                    <option value="manual">Manual only</option>
                  </select>
                </Field>
              </>
            )}

            {step === 2 && (
              <Field
                label="Additional pages"
                hint="Optional. Pricing, careers and product pages carry the strongest signals."
              >
                <div className="space-y-2">
                  {pages.map((page, index) => (
                    <div key={index} className="flex gap-2">
                      <input
                        autoFocus={index === 0}
                        value={page}
                        onChange={(event) => {
                          const updated = [...pages];
                          updated[index] = event.target.value;
                          setPages(updated);
                        }}
                        placeholder="https://acme.com/careers"
                        className="input"
                      />
                      {pages.length > 1 && (
                        <Button
                          size="sm"
                          variant="ghost"
                          title="Remove this page"
                          onClick={() =>
                            setPages(pages.filter((_, position) => position !== index))
                          }
                        >
                          <X size={13} strokeWidth={2} />
                        </Button>
                      )}
                    </div>
                  ))}
                  <Button
                    size="sm"
                    variant="secondary"
                    onClick={() => setPages([...pages, ""])}
                  >
                    <Plus size={13} strokeWidth={2} />
                    Another page
                  </Button>
                </div>
              </Field>
            )}

            {step === 3 && (
              <div>
                <h3 className="text-[15px] font-semibold tracking-[-0.014em]">{name}</h3>
                <p className="mono mt-1 truncate text-[11.5px] text-[var(--ink-faint)]">
                  {hostOf(website)}
                </p>

                <dl className="mt-6 divide-y divide-[var(--line)] border-y border-[var(--line)] text-[12.5px]">
                  <Row label="Scan frequency" value={frequency} capitalise />
                  <Row
                    label="Pages tracked"
                    value={`${trackedPages.length || 1} page${
                      (trackedPages.length || 1) === 1 ? "" : "s"
                    }`}
                  />
                </dl>

                <ul className="mt-4 space-y-1.5">
                  {(trackedPages.length ? trackedPages : [website]).map((url) => (
                    <li
                      key={url}
                      className="mono truncate text-[11.5px] text-[var(--ink-soft)]"
                    >
                      {url}
                    </li>
                  ))}
                </ul>

                <p className="mt-6 max-w-[46ch] text-[12.5px] leading-relaxed text-[var(--ink-soft)]">
                  The first scan stores a baseline snapshot. Changes are reported from
                  the second scan onward.
                </p>
              </div>
            )}

            {create.error && (
              <div className="mt-6">
                <ErrorState
                  title="Could not add this competitor"
                  message={create.error}
                  compact
                />
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="flex shrink-0 items-center justify-between gap-2 border-t border-[var(--line)] px-7 py-4">
          {step > 0 ? (
            <Button variant="ghost" size="sm" onClick={() => setStep((step - 1) as Step)}>
              <ArrowLeft size={13} strokeWidth={2} />
              Back
            </Button>
          ) : (
            <span />
          )}
          <Button onClick={next} disabled={!canAdvance || create.pending}>
            {step === 3
              ? create.pending
                ? "Starting…"
                : "Start monitoring"
              : "Continue"}
          </Button>
        </div>
      </>
    </SlideOver>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="mb-6 block last:mb-0">
      <span className="field-label mb-2">{label}</span>
      {children}
      {hint && (
        <span className="mt-2 block text-[12px] leading-relaxed text-[var(--ink-faint)]">
          {hint}
        </span>
      )}
    </label>
  );
}

function Row({
  label,
  value,
  capitalise,
}: {
  label: string;
  value: string;
  /** Only for values that are lowercase enum slugs, never counted strings. */
  capitalise?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between py-2.5">
      <dt className="text-[var(--ink-faint)]">{label}</dt>
      <dd className={`font-medium ${capitalise ? "capitalize" : ""}`}>{value}</dd>
    </div>
  );
}
