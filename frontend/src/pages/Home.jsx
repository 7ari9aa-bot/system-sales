import React from "react";
import BusinessPulse from "@/components/dashboard/sections/BusinessPulse";
import NeedsAttention from "@/components/dashboard/sections/NeedsAttention";
import SalesPerformance from "@/components/dashboard/sections/SalesPerformance";
import YourAI from "@/components/dashboard/sections/YourAI";
import BusinessInsights from "@/components/dashboard/sections/BusinessInsights";
import { InventorySnapshot, MarketingSnapshot } from "@/components/dashboard/sections/Snapshots";

export default function Home() {
  return (
    <div className="space-y-3.5 animate-fade-in xl:space-y-5">
      <BusinessPulse />

      <NeedsAttention />

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <div className="xl:col-span-2 min-h-0">
          <SalesPerformance />
        </div>
        <div className="xl:col-span-1 min-h-0">
          <YourAI />
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <div className="xl:col-span-1 min-h-0">
          <BusinessInsights />
        </div>
        <div className="xl:col-span-2 grid grid-cols-1 sm:grid-cols-2 gap-4">
          <InventorySnapshot />
          <MarketingSnapshot />
        </div>
      </div>
    </div>
  );
}