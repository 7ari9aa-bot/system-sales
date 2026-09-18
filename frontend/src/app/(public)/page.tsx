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
 *  → الأتمتة → التكاملات → الأمان → الأسعار → CTA.
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
      <AutomationSection />
      <Integrations />
      <SecurityTeaser />
      <PricingPreview />
      <FinalCTA />
    </main>
  );
}
