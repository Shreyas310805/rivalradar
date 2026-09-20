/**
 * Loading skeletons.
 *
 * Each one mirrors the shape of the content it stands in for — including its
 * separators — so nothing jumps when data arrives. Shimmer comes from the
 * `.skeleton` class, which is disabled under `prefers-reduced-motion`.
 */

export function Skeleton({
  className = "",
  style,
}: {
  className?: string;
  style?: React.CSSProperties;
}) {
  return <div className={`skeleton ${className}`} style={style} aria-hidden />;
}

export function MetricsSkeleton() {
  return (
    <div className="grid grid-cols-2 border-b border-[var(--line)] pb-8 lg:grid-cols-4">
      {[0, 1, 2, 3].map((index) => (
        <div
          key={index}
          className={`px-5 first:pl-0 ${index < 2 ? "pb-7 lg:pb-0" : ""} ${
            index % 2 === 1
              ? "border-l border-[var(--line)]"
              : "lg:border-l lg:border-[var(--line)] lg:first:border-l-0"
          }`}
        >
          <Skeleton className="h-[26px] w-16" />
          <Skeleton className="mt-3 h-[10px] w-24" />
          <Skeleton className="mt-2 h-[9px] w-20" />
        </div>
      ))}
    </div>
  );
}

export function FeedSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div>
      {Array.from({ length: rows }).map((_, index) => (
        <div key={index} className="flex gap-6 border-b border-[var(--line)] py-5">
          <Skeleton className="hidden h-[10px] w-[54px] shrink-0 sm:block" />
          <div className="min-w-0 flex-1">
            <Skeleton className="h-[10px] w-40" />
            <Skeleton className="mt-3 h-[13px] w-3/5" />
            <Skeleton className="mt-2.5 h-[11px] w-4/5" />
            <Skeleton className="mt-3 h-[10px] w-28" />
          </div>
        </div>
      ))}
    </div>
  );
}

export function CompetitorListSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div>
      {Array.from({ length: rows }).map((_, index) => (
        <div
          key={index}
          className="flex items-center justify-between gap-6 border-b border-[var(--line)] py-5"
        >
          <div className="min-w-0 flex-1">
            <Skeleton className="h-[14px] w-40" />
            <Skeleton className="mt-2 h-[11px] w-28" />
            <Skeleton className="mt-3 h-[10px] w-56" />
          </div>
          <Skeleton className="h-[24px] w-24" />
        </div>
      ))}
    </div>
  );
}

export function PipelineSkeleton() {
  return (
    <div>
      <Skeleton className="h-[10px] w-28" />
      <Skeleton className="mt-4 h-[27px] w-32" />
      <div className="mt-6 border-l border-[var(--line)]">
        {[0, 1, 2, 3].map((index) => (
          <div key={index} className="pb-5 pl-5 last:pb-0">
            <Skeleton className="h-[14px] w-36" />
            <Skeleton className="mt-2 h-[2px] w-full" />
          </div>
        ))}
      </div>
    </div>
  );
}

export function ChartSkeleton({ height = 180 }: { height?: number }) {
  return (
    <div>
      <Skeleton className="h-[10px] w-32" />
      <Skeleton className="mt-3 h-[11px] w-52" />
      <Skeleton className="mt-5 w-full" style={{ height }} />
    </div>
  );
}

export function DrawerSkeleton() {
  return (
    <div className="space-y-6">
      <Skeleton className="h-[11px] w-4/5" />
      <Skeleton className="h-[88px] w-full" />
      <Skeleton className="h-[64px] w-full" />
      <div className="space-y-4">
        {[0, 1, 2].map((index) => (
          <div key={index}>
            <Skeleton className="h-[11px] w-32" />
            <Skeleton className="mt-2 h-[2px] w-full" />
          </div>
        ))}
      </div>
    </div>
  );
}

export function DigestSkeleton() {
  return (
    <div>
      <div className="grid grid-cols-2 gap-y-6 border-y border-[var(--line)] py-6 sm:grid-cols-5">
        {[0, 1, 2, 3, 4].map((index) => (
          <div key={index}>
            <Skeleton className="h-[18px] w-14" />
            <Skeleton className="mt-2 h-[10px] w-20" />
          </div>
        ))}
      </div>
      <div className="mt-10 space-y-3">
        {Array.from({ length: 12 }).map((_, index) => (
          <Skeleton
            key={index}
            className="h-[11px]"
            style={{ width: `${55 + ((index * 7) % 40)}%` }}
          />
        ))}
      </div>
    </div>
  );
}
