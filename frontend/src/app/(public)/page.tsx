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
 *  مفيش معاينات داخلية للداشبورد — المهمتم يشوف كل حاجة بنفسها جوه النظام. */

/** JSON-LD structured data — عشان محركات البحث و AI search تفهم المنتج
 *  وتعرضه كـ SoftwareApplication بدل نص عادي. */
const jsonLd = {
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "SoftwareApplication",
      name: "FIHRIST",
      alternateName: "فهرست",
      applicationCategory: "BusinessApplication",
      operatingSystem: "Web",
      description:
        "نظام تشغيل الأعمال بالمحادثة — المحادثات والعملاء والطلبات والأتمتة والذكاء الاصطناعي في سياق عمل واحد.",
      url: "https://sales-os-three-bay.vercel.app",
      offers: {
        "@type": "Offer",
        price: "0",
        priceCurrency: "USD",
        description: "وصول مبكر مجاني لكل الخطط",
      },
      featureList: [
        "إدارة المحادثات متعددة القنوات",
        "إدارة العملاء (CRM)",
        "الطلبات والمخزون",
        "الأتمتة بمسارات ومنطق",
        "ذكاء اصطناعي بأدوات وصرحيات",
        "تحليلات وتقارير",
      ],
      publisher: { "@type": "Organization", name: "FIHRIST" },
    },
    {
      "@type": "Organization",
      name: "FIHRIST",
      alternateName: "فهرست",
      url: "https://sales-os-three-bay.vercel.app",
      email: "7ari9aa@gmail.com",
      slogan: "نظام واحد لكل أعمالك.",
    },
  ],
};

export default function HomePage() {
  return (
    <main aria-label="FIHRIST — الصفحة الرئيسية">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />
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
