import { Hero } from "@/components/public/hero";
import { BusinessSignals } from "@/components/public/signals";
import { ContextGraph, Customer360, InboxPreview } from "@/components/public/context-sections";
import { AISection, Handoff, Automation } from "@/components/public/ai-sections";
import {
  Analytics,
  ControlCenter,
  Pricing,
  Integrations,
  SecuritySection,
  FinalCTA,
} from "@/components/public/ops-sections";

/** Homepage flow: NAVBAR → HERO(تفاعلي) → SIGNALS → CONTEXT → CUSTOMER 360
 *  → INBOX → AI → HUMAN+AI → AUTOMATION → INTELLIGENCE → CONTROL
 *  → PRICING → INTEGRATIONS → SECURITY → FINAL CTA → FOOTER */

export default function HomePage() {
  return (
    <main>
      <Hero />
      <BusinessSignals />
      <ContextGraph />
      <Customer360 />
      <InboxPreview />
      <AISection />
      <Handoff />
      <Automation />
      <Analytics />
      <ControlCenter />
      <Pricing />
      <Integrations />
      <SecuritySection />
      <FinalCTA />
    </main>
  );
}
