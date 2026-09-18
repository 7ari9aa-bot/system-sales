import type { Metadata } from "next";
import { PublicShell } from "@/components/public/shell";
import { AutomationBody } from "@/components/public/page-bodies";

export const metadata: Metadata = {
  title: "الأتمتة — أتمتة بتنفّذ شغل فعلًا — FIHRIST",
  description: "مسارات تشغيلية بحدث وشرط ومنطق — بموافقات بشرية لما يلزم وسجل إصدارات وتشغيل تجريبي واسترجاع بعد الفشل.",
};

export default function AutomationPage() {
  return (
    <PublicShell>
      <AutomationBody />
    </PublicShell>
  );
}
