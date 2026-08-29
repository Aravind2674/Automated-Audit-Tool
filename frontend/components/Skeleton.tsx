/**
 * Shimmer skeletons shaped like the real layout they stand in for -- a loading
 * state should telegraph "a compliance card is coming here" / "a table row is
 * coming here", never a blank page or a generic centered spinner that gives no
 * sense of what's about to render.
 */
export function SkeletonBlock({ className = "" }: { className?: string }) {
  return <div className={`animate-pulse rounded bg-surface-container ${className}`} />;
}

export function SkeletonRow({ cols = 5 }: { cols?: number }) {
  return (
    <tr className="border-b border-outline-variant">
      {Array.from({ length: cols }).map((_, i) => (
        <td key={i} className="p-sm">
          <SkeletonBlock className="h-4 w-full max-w-[10rem]" />
        </td>
      ))}
    </tr>
  );
}

export function SkeletonCard({ className = "" }: { className?: string }) {
  return (
    <div className={`flex flex-col gap-sm rounded-lg border border-outline-variant bg-surface-container-lowest p-md ${className}`}>
      <SkeletonBlock className="h-3 w-24" />
      <SkeletonBlock className="h-8 w-16" />
    </div>
  );
}

/** Shaped like the real Overview layout, so the transition into real data doesn't jolt. */
export function OverviewSkeleton() {
  return (
    <div className="flex flex-col gap-margin" aria-busy="true" aria-label="Loading dashboard">
      <div className="grid grid-cols-1 gap-md lg:grid-cols-3">
        <div className="flex flex-col items-center justify-center gap-sm rounded-lg border border-outline-variant bg-surface-container-lowest p-lg lg:col-span-1">
          <SkeletonBlock className="h-3 w-32" />
          <SkeletonBlock className="h-16 w-28" />
          <SkeletonBlock className="h-3 w-40" />
        </div>
        <div className="grid grid-cols-1 gap-md md:grid-cols-3 lg:col-span-2">
          <SkeletonCard /><SkeletonCard /><SkeletonCard />
          <SkeletonBlock className="h-24 w-full md:col-span-3" />
        </div>
      </div>
      <div className="rounded-lg border border-outline-variant bg-surface-container-lowest p-md">
        <SkeletonBlock className="mb-md h-4 w-56" />
        <div className="grid grid-cols-2 gap-sm md:grid-cols-4">
          <SkeletonCard /><SkeletonCard /><SkeletonCard /><SkeletonCard />
        </div>
      </div>
      <div className="overflow-hidden rounded-lg border border-outline-variant bg-surface-container-lowest">
        <div className="border-b border-outline-variant bg-surface-container p-md">
          <SkeletonBlock className="h-4 w-48" />
        </div>
        <table className="w-full"><tbody>
          <SkeletonRow /><SkeletonRow /><SkeletonRow /><SkeletonRow />
        </tbody></table>
      </div>
    </div>
  );
}
