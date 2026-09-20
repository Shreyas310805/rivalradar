/**
 * RivalRadar mark.
 *
 * One sweep arc and one detected point, drawn on a 16-unit grid. Monochrome
 * and built from `currentColor`, so it takes the colour of whatever it sits
 * in and never needs a second version for dark mode.
 */
export function Logo({ size = 16, className }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      className={className}
      aria-hidden="true"
      focusable="false"
    >
      <path
        d="M4.6 1.9a7.7 7.7 0 0 1 0 12.2"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        opacity="0.42"
      />
      <path
        d="M4.6 5.6a3.6 3.6 0 0 1 0 4.8"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        opacity="0.72"
      />
      <circle cx="3.5" cy="8" r="1.5" fill="currentColor" />
    </svg>
  );
}

/** Wordmark + mark. The product name is set in the UI face, not a logotype. */
export function Wordmark() {
  return (
    <span className="flex items-center gap-2 text-[var(--ink)]">
      <Logo size={15} />
      <span className="text-[13.5px] font-semibold tracking-[-0.016em]">RivalRadar</span>
    </span>
  );
}
