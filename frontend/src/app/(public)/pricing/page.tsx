import type { Metadata } from "next";
import { PublicShell } from "@/components/public/shell";
import { PricingBody } from "@/components/public/page-bodies";

export const metadata: Metadata = {
  title: "الأسعار والخطط — وصول مبكر مجاني — FIHRIST",
  description: "3 خطط واضحة — البداية والنمو والتوسع. مجانية خلال الوصول المبكر، بدون بطاقة وبدون التزام. مع أسئلة شائعة.",
};

export default function PricingPage() {
  return (
    <PublicShell>
      <PricingBody />
    </PublicShell>
  );
}
