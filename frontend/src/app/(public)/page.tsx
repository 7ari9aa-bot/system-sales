import { Hero } from "@/components/public/hero";
import {
  HowItWorks,
  ContextSection,
  TrySection,
  AutomationSection,
  Integrations,
  SecurityTeaser,
  PricingPreview,
  FinalCTA,
} from "@/components/public/home-sections";
import { DemoChat } from "@/components/public/demo-chat";

/** Homepage — تدرج منطقي: عام → إزاي بيشتغل → السياق → تجربة حقيقية
 *  → العرض (الأسعار) → الأتمتة → التكاملات → الأمان → CTA.
 *  مفيش معاينات داخلية للداشبورد — المهتم يشوف كل حاجة بنفسه جوه النظام. */

export default function HomePage() {
  return (
    <main>
      <Hero />
      <HowItWorks />
      <ContextSection />
      <TrySection>
        <DemoChat />
      </TrySection>
      <PricingPreview />
      <AutomationSection />
      <Integrations />
      <SecurityTeaser />
      <FinalCTA />
    </main>
  );
}
