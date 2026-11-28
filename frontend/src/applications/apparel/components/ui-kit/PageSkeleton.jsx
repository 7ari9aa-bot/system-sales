import { cn } from "@/applications/apparel/lib/utils";

/**
 * هيكل صفحة أثناء التحميل: عنوان وفلاتر وجدول وامض بدل سطر «جارٍ التحميل…» العاري.
 * النص المسموع مرة واحدة للمحرّكات القارئة (sr-only)، والباقي زخرفة aria-hidden.
 */
export default function PageSkeleton({ label = "جارٍ التحميل…", rows = 5, testId = "cashier-page-loading" }) {
  return (
    <div className="p-4 md:p-6" role="status" aria-busy="true" aria-live="polite" data-testid={testId}>
      <span className="sr-only">{label}</span>
      <div aria-hidden="true" className="space-y-4">
        <div className="flex items-center gap-3">
          <span className="h-7 w-40 animate-pulse rounded bg-muted" />
          <span className="ms-auto h-9 w-28 animate-pulse rounded-lg bg-muted" />
        </div>
        <div className="rounded-xl border border-border bg-card p-3">
          <div className="flex flex-wrap gap-3">
            {Array.from({ length: 3 }).map((_, index) => (
              <span key={index} className={cn("h-8 animate-pulse rounded bg-muted", index === 2 ? "w-24" : "w-36")} />
            ))}
          </div>
        </div>
        <div className="overflow-hidden rounded-xl border border-border bg-card">
          <div className="h-9 animate-pulse bg-muted" />
          {Array.from({ length: rows }).map((_, rowIndex) => (
            <div key={rowIndex} className="flex items-center gap-4 border-t border-border/70 px-3 py-2.5">
              <span className="h-3 w-1/4 animate-pulse rounded bg-muted" />
              <span className={cn("h-3 animate-pulse rounded bg-muted", rowIndex % 2 === 0 ? "w-1/3" : "w-2/5")} />
              <span className="ms-auto h-3 w-16 animate-pulse rounded bg-muted" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
