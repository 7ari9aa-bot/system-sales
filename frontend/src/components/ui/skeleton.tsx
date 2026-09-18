import { cn } from "@/lib/utils";

/** Skeleton — التحميل بهيكل عظمي مش spinners (§106). */
function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("animate-pulse rounded-lg bg-muted", className)} {...props} />;
}

/** هيكل عظمي لصفحة نموذجية (عنوان + بطاقات). */
function PageSkeleton({ cards = 4 }: { cards?: number }) {
  return (
    <div className="space-y-6" aria-busy="true" aria-label="جارٍ التحميل">
      <Skeleton className="h-7 w-40" />
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: cards }).map((_, i) => (
          <Skeleton key={i} className="h-24" />
        ))}
      </div>
      <Skeleton className="h-72" />
    </div>
  );
}

export { Skeleton, PageSkeleton };
