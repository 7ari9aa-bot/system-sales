// هيكل تحميل لشبكة المخزون: بطاقات وامضة بنفس أبعاد ProductCard بدل سطر "جاري تحميل المخزون".
export default function InventoryGridSkeleton({ count = 6 }) {
  return (
    <section role="status" aria-busy="true" aria-live="polite" data-testid="inventory-grid-loading" className="flex flex-col gap-3">
      <span className="sr-only">جارٍ تحميل المخزون…</span>
      <div>
        <span aria-hidden="true" className="block h-4 w-48 animate-pulse rounded bg-[#efe7da]" />
        <span aria-hidden="true" className="mt-2 block h-3 w-32 animate-pulse rounded bg-[#f2ece2]" />
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: count }).map((_, index) => (
          <div key={index} aria-hidden="true" className="animate-pulse rounded-2xl border border-[#E3DED4] bg-white p-4">
            <div className="h-28 w-full rounded-xl bg-[#f2ece2]" />
            <div className="mt-3 h-4 w-3/4 rounded bg-[#efe7da]" />
            <div className="mt-2 h-3 w-1/2 rounded bg-[#f2ece2]" />
            <div className="mt-4 flex gap-2">
              <div className="h-6 w-16 rounded-full bg-[#f2ece2]" />
              <div className="h-6 w-16 rounded-full bg-[#f2ece2]" />
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
