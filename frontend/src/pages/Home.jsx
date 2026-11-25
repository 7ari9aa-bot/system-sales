import BusinessPulse from "@/components/dashboard/sections/BusinessPulse";
import NeedsAttention from "@/components/dashboard/sections/NeedsAttention";
import SalesPerformance from "@/components/dashboard/sections/SalesPerformance";
import { InventorySnapshot } from "@/components/dashboard/sections/Snapshots";

/** الداشبورد — صفحة ملخّص نظيفة. كل وظيفة بصفحتها الخاصة:
 *  الذكاء على /ai، المخزون على /cashier/inventory، التحليلات على /analytics.
 *  هنا بس: نبض الأعمال، ما يحتاج انتباه، أداء المبيعات، ولمحة المخزون. */
export default function Home() {
  return (
    <div className="space-y-4 animate-fade-in xl:space-y-5">
      <BusinessPulse />

      <NeedsAttention />

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <div className="xl:col-span-2 min-h-0">
          <SalesPerformance />
        </div>
        <div className="xl:col-span-1 min-h-0">
          <InventorySnapshot />
        </div>
      </div>
    </div>
  );
}
