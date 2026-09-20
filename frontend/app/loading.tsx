import { FeedSkeleton, MetricsSkeleton, Skeleton } from "@/components/Skeletons";

export default function Loading() {
  return (
    <div>
      <div className="mb-10">
        <Skeleton className="h-[22px] w-64" />
        <Skeleton className="mt-3 h-[12px] w-80" />
      </div>
      <MetricsSkeleton />
      <div className="mt-10">
        <FeedSkeleton />
      </div>
    </div>
  );
}
