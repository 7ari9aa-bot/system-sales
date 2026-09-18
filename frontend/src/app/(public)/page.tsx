import type { Metadata } from "next";
import { Hero } from "@/components/public/hero";
import { BusinessSignals } from "@/components/public/signals";
import { ContextGraph, Customer360, InboxPreview } from "@/components/public/context-sections";
import { AISection, Handoff, Automation } from "@/components/public/ai-sections";
import {
  Analytics,
  ControlCenter,
  Integrations,
  SecuritySection,
  FinalCTA,
} from "@/components/public/ops-sections";

export const metadata: Metadata = {
  title: "سيلز أو إس — نظام تشغيل واحد لشركتك",
  description:
    "العملاء، المحادثات، التجارة، الأتمتة، الذكاء الاصطناعي والتحليلات — كلها متصلة عبر سياق عمل واحد.",
  alternates: { canonical: "/" },
  openGraph: {
    title: "سيلز أو إس — نظام تشغيل واحد لشركتك",
    description:
      "سياق عمل واحد يجمع المحادثات والطلبات والعملاء والأتمتة والذكاء الاصطناعي.",
    type: "website",
    locale: "ar_EG",
  },
};

/** Homepage flow حسب المواصفة: NAVBAR ← HERO ← PRODUCT EXPERIENCE ← SIGNALS
 *  ← CONTEXT ← CUSTOMER 360 ← INBOX ← AI ← HUMAN+AI ← AUTOMATION
 *  ← INTELLIGENCE ← CONTROL ← INTEGRATIONS ← SECURITY ← FINAL CTA ← FOOTER */

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
      <Integrations />
      <SecuritySection />
      <FinalCTA />
    </main>
  );
}
